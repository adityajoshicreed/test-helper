import threading

from django.db import connection
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

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


def _run_test_cases_in_background(test_run_id, pairs):
    """Runs on a separate thread from the request that created the TestRun,
    so the API can return immediately with the (pending) test cases and the
    frontend can poll for progress as each one's executed_at gets set."""
    try:
        for test_case, case_data in pairs:
            run_and_save(test_case, case_data)
        TestRun.objects.filter(pk=test_run_id).update(
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

        generated = generate_test_cases(imported_request, categories, body_field_tests, header_tests)

        test_run = TestRun.objects.create(
            imported_request=imported_request,
            categories=categories,
            body_field_tests=body_field_tests,
            header_tests=header_tests,
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
                target=_run_test_cases_in_background, args=(test_run.id, pairs), daemon=True
            )
            thread.start()
        else:
            test_run.status = TestRun.STATUS_COMPLETED
            test_run.completed_at = timezone.now()
            test_run.save(update_fields=['status', 'completed_at'])

        return Response(TestRunSerializer(test_run).data, status=status.HTTP_201_CREATED)


class TestRunListView(generics.ListAPIView):
    queryset = TestRun.objects.all()
    serializer_class = TestRunListSerializer


class TestRunDetailView(generics.RetrieveAPIView):
    queryset = TestRun.objects.all()
    serializer_class = TestRunSerializer
