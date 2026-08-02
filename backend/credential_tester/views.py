import threading

from django.db import connection
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apitester.curl_parser import CurlParseError, parse_curl
from apitester.test_generator import (
    BLANKET_CATEGORIES,
    BODY_FIELD_TEST_CODES,
    HEADER_TEST_CODES,
    _get_at_path,
    available_categories,
    body_field_options,
    detect_dynamic_headers,
    generate_test_cases,
    header_field_options,
)

from .models import CredentialRun, CredentialTestCase
from .runner import run_credential_run
from .serializers import CredentialRunListSerializer, CredentialRunSerializer


def _clean_field_tests(raw, valid_codes):
    """Same filtering as apitester.views._clean_field_tests -- drops
    anything malformed rather than erroring."""
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


def _clean_credential_fields(raw, headers, body):
    """Validates each declared credential field actually exists in the
    parsed request. Returns (cleaned_fields, error_message) -- exactly one
    of the two is non-empty/None."""
    if not isinstance(raw, list):
        return None, '"credential_fields" must be a list.'
    cleaned = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None, 'Each credential field must be an object with "location" and "key".'
        location = entry.get('location')
        key = entry.get('key')
        if location not in ('header', 'body') or not isinstance(key, str) or not key:
            return None, 'Each credential field needs a "location" of "header" or "body" and a non-empty "key".'
        if location == 'header':
            if not isinstance(headers, dict) or key not in headers:
                return None, f"Header '{key}' was not found in the parsed request."
        else:
            if not isinstance(body, dict):
                return None, f"Body path '{key}' can't be checked -- the request body isn't a JSON object."
            try:
                _get_at_path(body, key)
            except (KeyError, IndexError, TypeError):
                return None, f"Body path '{key}' was not found in the parsed request body."
        cleaned.append({'location': location, 'key': key})
    return cleaned, None


def _run_in_background(run_id):
    """Runs on a separate thread from the request that created/resumed the
    run, so the API can return immediately and the frontend can poll for
    progress -- mirrors apitester/chain_tester's background-thread pattern."""
    try:
        run_credential_run(run_id)
    except Exception:
        CredentialRun.objects.filter(pk=run_id).update(
            status=CredentialRun.STATUS_FAILED, completed_at=timezone.now()
        )
        raise
    finally:
        connection.close()


class ParseCurlPreviewView(APIView):
    """Parses a curl command and returns everything the frontend needs to
    let the user mark expiring credential fields and pick mutation tests --
    without persisting anything. A real CredentialRun only gets created on
    the final POST /runs/ submission."""

    def post(self, request):
        raw_curl = request.data.get('raw_curl', '')
        if not isinstance(raw_curl, str) or not raw_curl.strip():
            return Response(
                {'error': 'Provide a non-empty "raw_curl" string.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed = parse_curl(raw_curl)
        except CurlParseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'raw_curl': raw_curl,
            'method': parsed.method,
            'url': parsed.url,
            'headers': parsed.headers,
            'body': parsed.body,
            'body_raw': parsed.body_raw,
            'is_json_body': parsed.is_json_body,
            'available_test_categories': available_categories(parsed),
            'body_field_options': body_field_options(parsed),
            'header_field_options': header_field_options(parsed),
            'dynamic_headers': detect_dynamic_headers(parsed.headers),
        })


class CredentialRunListCreateView(APIView):
    def get(self, request):
        runs = CredentialRun.objects.all()
        return Response(CredentialRunListSerializer(runs, many=True).data)

    def post(self, request):
        raw_curl = request.data.get('raw_curl', '')
        if not isinstance(raw_curl, str) or not raw_curl.strip():
            return Response(
                {'error': 'Provide a non-empty "raw_curl" string.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed = parse_curl(raw_curl)
        except CurlParseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        expiration_status_code = request.data.get('expiration_status_code')
        if expiration_status_code is not None:
            try:
                expiration_status_code = int(expiration_status_code)
            except (TypeError, ValueError):
                return Response(
                    {'error': '"expiration_status_code" must be an integer.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        expiration_message_contains = request.data.get('expiration_message_contains', '') or ''
        if not isinstance(expiration_message_contains, str):
            expiration_message_contains = ''
        if expiration_status_code is None and not expiration_message_contains.strip():
            return Response(
                {'error': 'Provide an expiration status code, a message to look for, or both.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        credential_fields, field_error = _clean_credential_fields(
            request.data.get('credential_fields', []), parsed.headers, parsed.body
        )
        if field_error:
            return Response({'error': field_error}, status=status.HTTP_400_BAD_REQUEST)
        if not credential_fields:
            return Response(
                {'error': 'Mark at least one header or body field as an expiring credential.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_values = request.data.get('current_values', {})
        if not isinstance(current_values, dict):
            return Response({'error': '"current_values" must be an object.'}, status=status.HTTP_400_BAD_REQUEST)
        missing = [f['key'] for f in credential_fields if f['key'] not in current_values]
        if missing:
            return Response(
                {'error': f"Provide a current value for: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        requested = request.data.get('categories', [])
        if not isinstance(requested, list):
            return Response(
                {'error': '"categories" must be a list of category codes.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        categories = [c for c in requested if c in BLANKET_CATEGORIES]
        body_field_tests = _clean_field_tests(request.data.get('body_field_tests', {}), BODY_FIELD_TEST_CODES)
        header_tests = _clean_field_tests(request.data.get('header_tests', {}), HEADER_TEST_CODES)
        verify_ssl = bool(request.data.get('verify_ssl', True))

        # Generation runs against the parsed curl directly -- ParsedCurl
        # already has the .method/.url/.headers/.body/.body_raw/.is_json_body
        # shape generate_test_cases() needs.
        generated = generate_test_cases(parsed, categories, body_field_tests, header_tests)

        run = CredentialRun.objects.create(
            raw_curl=raw_curl,
            method=parsed.method, url=parsed.url, headers=parsed.headers,
            body=parsed.body, body_raw=parsed.body_raw, is_json_body=parsed.is_json_body,
            credential_fields=credential_fields, current_values=current_values,
            expiration_status_code=expiration_status_code,
            expiration_message_contains=expiration_message_contains,
            categories=categories, body_field_tests=body_field_tests, header_tests=header_tests,
            verify_ssl=verify_ssl,
            status=CredentialRun.STATUS_RUNNING,
        )

        for case_data in generated:
            CredentialTestCase.objects.create(
                run=run,
                category=case_data['category'],
                description=case_data['description'],
                request_method=case_data['request_method'],
                request_url=case_data['request_url'],
                request_headers=case_data['request_headers'],
                request_body=case_data['request_body'],
                request_body_raw=case_data['request_body_raw'],
                body_mode=case_data['body_mode'],
            )

        if generated:
            thread = threading.Thread(target=_run_in_background, args=(run.id,), daemon=True)
            thread.start()
            # thread.start() only guarantees the thread has been launched,
            # not that it's finished -- but if it happens to finish very
            # quickly (or, in tests, runs synchronously), `run` in memory
            # here is still the pre-execution snapshot from .create()
            # above, since the thread updates its own separately-fetched
            # instance. Refresh so the response reflects real current state.
            run.refresh_from_db()
        else:
            run.status = CredentialRun.STATUS_COMPLETED
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'completed_at'])

        return Response(CredentialRunSerializer(run).data, status=status.HTTP_201_CREATED)


class ResumeCredentialRunView(APIView):
    def post(self, request, pk):
        run = get_object_or_404(CredentialRun, pk=pk)
        if run.status != CredentialRun.STATUS_PAUSED:
            return Response(
                {'error': f"Run is '{run.status}', not paused -- nothing to resume."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_values = request.data.get('current_values', {})
        if not isinstance(new_values, dict) or not new_values:
            return Response(
                {'error': 'Provide "current_values" with a fresh value for each credential field.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        missing = [f['key'] for f in run.credential_fields if f['key'] not in new_values]
        if missing:
            return Response(
                {'error': f"Provide a fresh value for: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        run.current_values = new_values
        run.pause_reason = ''
        run.status = CredentialRun.STATUS_RUNNING
        run.save()

        thread = threading.Thread(target=_run_in_background, args=(run.id,), daemon=True)
        thread.start()
        run.refresh_from_db()

        return Response(CredentialRunSerializer(run).data)


class CredentialRunDetailView(generics.RetrieveAPIView):
    queryset = CredentialRun.objects.all()
    serializer_class = CredentialRunSerializer
