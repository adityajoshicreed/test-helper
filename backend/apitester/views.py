import json
import threading

from django.db import connection
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from karate_tests.runner import PreflightError, build_curl, validate_excel_path, write_excel

from .curl_parser import CurlParseError, parse_curl
from .models import ImportedRequest, TestCase, TestRun
from .serializers import (
    ImportedRequestListSerializer,
    ImportedRequestSerializer,
    TestRunListSerializer,
    TestRunSerializer,
)
from .test_executor import run_and_save
from .test_generator import (
    BLANKET_CATEGORIES,
    BODY_FIELD_TEST_CODES,
    HEADER_TEST_CODES,
    generate_test_cases,
)


def _run_test_cases_in_background(test_run_id, pairs, verify_ssl):
    """Runs on a separate thread from the request that created the TestRun,
    so the API can return immediately with the (pending) test cases and the
    frontend can poll for progress as each one's executed_at gets set.

    Checks `stop_requested` before firing each case, so a user hitting Stop
    takes effect after the currently in-flight request finishes (that one
    HTTP call can't be interrupted mid-flight) rather than after every
    remaining case has run."""
    try:
        for test_case, case_data in pairs:
            if TestRun.objects.filter(pk=test_run_id, stop_requested=True).exists():
                TestRun.objects.filter(pk=test_run_id).update(
                    status=TestRun.STATUS_STOPPED, completed_at=timezone.now()
                )
                return
            run_and_save(test_case, case_data, verify_ssl=verify_ssl)
        TestRun.objects.filter(pk=test_run_id, status=TestRun.STATUS_RUNNING).update(
            status=TestRun.STATUS_COMPLETED, completed_at=timezone.now()
        )
    except Exception:
        TestRun.objects.filter(pk=test_run_id).update(
            status=TestRun.STATUS_FAILED, completed_at=timezone.now()
        )
        raise
    finally:
        connection.close()


def _clean_field_tests(raw, valid_codes):
    """Filters a {name: [test codes]} payload down to known codes, dropping
    anything malformed rather than erroring -- unknown/stale codes are just
    silently ignored (e.g. the UI sent something for a field that no longer
    exists on this request)."""
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for name, codes in raw.items():
        if not isinstance(codes, list):
            continue
        kept = [c for c in codes if c in valid_codes]
        if kept:
            cleaned[name] = kept
    return cleaned


class ImportCurlView(APIView):
    def post(self, request):
        raw_curl = request.data.get('curl', '')
        if not isinstance(raw_curl, str) or not raw_curl.strip():
            return Response(
                {'error': 'Provide a non-empty "curl" string.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parsed = parse_curl(raw_curl)
        except CurlParseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        imported = ImportedRequest.objects.create(
            raw_curl=raw_curl,
            method=parsed.method,
            url=parsed.url,
            headers=parsed.headers,
            body=parsed.body,
            body_raw=parsed.body_raw,
            is_json_body=parsed.is_json_body,
        )
        return Response(
            ImportedRequestSerializer(imported).data, status=status.HTTP_201_CREATED
        )


class ImportedRequestListView(generics.ListAPIView):
    queryset = ImportedRequest.objects.all()
    serializer_class = ImportedRequestListSerializer


class ImportedRequestDetailView(generics.RetrieveAPIView):
    queryset = ImportedRequest.objects.all()
    serializer_class = ImportedRequestSerializer


class CreateTestRunView(APIView):
    def post(self, request, pk):
        imported_request = get_object_or_404(ImportedRequest, pk=pk)
        requested = request.data.get('categories', [])
        if not isinstance(requested, list):
            return Response(
                {'error': '"categories" must be a list of category codes.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        categories = [c for c in requested if c in BLANKET_CATEGORIES]
        body_field_tests = _clean_field_tests(request.data.get('body_field_tests', {}), BODY_FIELD_TEST_CODES)
        header_tests = _clean_field_tests(request.data.get('header_tests', {}), HEADER_TEST_CODES)
        verify_ssl = request.data.get('verify_ssl', True)
        if not isinstance(verify_ssl, bool):
            verify_ssl = True

        generated = generate_test_cases(imported_request, categories, body_field_tests, header_tests)

        test_run = TestRun.objects.create(
            imported_request=imported_request,
            categories=categories,
            body_field_tests=body_field_tests,
            header_tests=header_tests,
            verify_ssl=verify_ssl,
            status=TestRun.STATUS_RUNNING,
        )

        pairs = []
        for case_data in generated:
            test_case = TestCase.objects.create(
                test_run=test_run,
                category=case_data['category'],
                description=case_data['description'],
                request_method=case_data['request_method'],
                request_url=case_data['request_url'],
                request_headers=case_data['request_headers'],
                request_body=case_data['request_body'],
                request_body_raw=case_data['request_body_raw'],
                body_mode=case_data['body_mode'],
            )
            pairs.append((test_case, case_data))

        if pairs:
            thread = threading.Thread(
                target=_run_test_cases_in_background, args=(test_run.id, pairs, verify_ssl), daemon=True
            )
            thread.start()
        else:
            test_run.status = TestRun.STATUS_COMPLETED
            test_run.completed_at = timezone.now()
            test_run.save(update_fields=['status', 'completed_at'])

        return Response(TestRunSerializer(test_run).data, status=status.HTTP_201_CREATED)


class StopTestRunView(APIView):
    def post(self, request, pk):
        test_run = get_object_or_404(TestRun, pk=pk)
        if test_run.status != TestRun.STATUS_RUNNING:
            return Response(
                {'error': f"Test run is '{test_run.status}', not running -- nothing to stop."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        test_run.stop_requested = True
        test_run.save(update_fields=['stop_requested'])
        return Response(TestRunSerializer(test_run).data)


def _request_body_for_excel(test_case):
    if test_case.body_mode == 'json':
        return json.dumps(test_case.request_body) if test_case.request_body is not None else None
    if test_case.body_mode == 'raw':
        return test_case.request_body_raw
    return None


def _build_excel_cases(executed_cases):
    """Turns executed apitester TestCase rows into the [{name, steps}] shape
    karate_tests.runner.write_excel expects -- each API-tested case is a
    single real HTTP call, so it maps to exactly one case with exactly one
    step (unlike a Karate scenario, which can chain several calls)."""
    cases = []
    for tc in executed_cases:
        curl = build_curl(tc.request_method, tc.request_url, tc.request_headers, _request_body_for_excel(tc))
        cases.append({
            'name': f'{tc.category}: {tc.description}',
            'steps': [{
                'curl': curl,
                'status_code': tc.status_code,
                'response_body': tc.error if tc.error else tc.response_body,
            }],
        })
    return cases


class ExportTestRunExcelView(APIView):
    def post(self, request, pk):
        test_run = get_object_or_404(TestRun, pk=pk)
        if test_run.status in (TestRun.STATUS_PENDING, TestRun.STATUS_RUNNING):
            return Response(
                {'error': "Test run is still in progress -- wait for it to finish (or stop it) before exporting."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        executed_cases = list(test_run.test_cases.filter(executed_at__isnull=False).order_by('id'))
        if not executed_cases:
            return Response(
                {'error': 'This test run has no executed test cases to export.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            excel_path = validate_excel_path(request.data.get('excel_path', ''))
        except PreflightError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            write_excel(
                _build_excel_cases(executed_cases), excel_path,
                environment=request.data.get('environment', ''),
                pre_requisite=request.data.get('pre_requisite', ''),
                created_by=request.data.get('created_by', ''),
                sprint=request.data.get('sprint', ''),
                lob=request.data.get('lob', ''),
                vertical=request.data.get('vertical', ''),
                feasible_for_automation=request.data.get('feasible_for_automation', ''),
                test_case_applicability=request.data.get('test_case_applicability', ''),
                labels=request.data.get('labels', ''),
                test_case_status=request.data.get('test_case_status', ''),
            )
        except OSError as exc:
            return Response({'error': f'Could not write the Excel file: {exc}'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'excel_path': excel_path, 'exported_case_count': len(executed_cases)})


class TestRunListView(generics.ListAPIView):
    queryset = TestRun.objects.all()
    serializer_class = TestRunListSerializer


class TestRunDetailView(generics.RetrieveAPIView):
    queryset = TestRun.objects.all()
    serializer_class = TestRunSerializer
