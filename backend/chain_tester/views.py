import threading

from django.db import connection, models
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
    generate_test_cases,
)

from .models import ApiChain, ChainRun, ChainStep, ChainTestCase
from .runner import run_chain
from .serializers import (
    ApiChainListSerializer,
    ApiChainSerializer,
    ChainRunListSerializer,
    ChainRunSerializer,
    ChainStepSerializer,
)


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


def _clean_extract_rules(raw):
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value for key, value in raw.items()
        if isinstance(key, str) and key and isinstance(value, str) and value
    }


def _run_chain_in_background(chain_run_id, pairs):
    """Runs on a separate thread from the request that created the
    ChainRun, so the API can return immediately and the frontend can poll
    for progress -- mirrors apitester.views._run_test_cases_in_background."""
    try:
        run_chain(chain_run_id, pairs)
    except Exception:
        ChainRun.objects.filter(pk=chain_run_id).update(
            status=ChainRun.STATUS_FAILED, completed_at=timezone.now()
        )
        raise
    finally:
        connection.close()


class ApiChainListCreateView(APIView):
    def get(self, request):
        chains = ApiChain.objects.all()
        return Response(ApiChainListSerializer(chains, many=True).data)

    def post(self, request):
        name = request.data.get('name', '')
        if not isinstance(name, str):
            name = ''
        chain = ApiChain.objects.create(name=name)
        return Response(ApiChainSerializer(chain).data, status=status.HTTP_201_CREATED)


class ApiChainDetailView(generics.RetrieveAPIView):
    queryset = ApiChain.objects.all()
    serializer_class = ApiChainSerializer


class ChainStepCreateView(APIView):
    def post(self, request, pk):
        chain = get_object_or_404(ApiChain, pk=pk)
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

        refresh_mode = request.data.get('refresh_mode', ChainStep.REFRESH_ONCE)
        if refresh_mode not in (ChainStep.REFRESH_ONCE, ChainStep.REFRESH_PER_TEST):
            refresh_mode = ChainStep.REFRESH_ONCE

        extract_rules = _clean_extract_rules(request.data.get('extract_rules', {}))

        next_order = (chain.steps.aggregate(models.Max('order'))['order__max'] or 0) + 1
        step = ChainStep.objects.create(
            chain=chain,
            order=next_order,
            raw_curl=raw_curl,
            method=parsed.method,
            url=parsed.url,
            headers=parsed.headers,
            body=parsed.body,
            body_raw=parsed.body_raw,
            is_json_body=parsed.is_json_body,
            refresh_mode=refresh_mode,
            extract_rules=extract_rules,
        )
        return Response(ChainStepSerializer(step).data, status=status.HTTP_201_CREATED)


class CreateChainRunView(APIView):
    def post(self, request, pk):
        chain = get_object_or_404(ApiChain, pk=pk)
        steps = list(chain.steps.order_by('order'))
        if not steps:
            return Response(
                {'error': 'Add at least one step before running this chain.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        final_step = steps[-1]

        requested = request.data.get('categories', [])
        if not isinstance(requested, list):
            return Response(
                {'error': '"categories" must be a list of category codes.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        categories = [c for c in requested if c in BLANKET_CATEGORIES]
        body_field_tests = _clean_field_tests(request.data.get('body_field_tests', {}), BODY_FIELD_TEST_CODES)
        header_tests = _clean_field_tests(request.data.get('header_tests', {}), HEADER_TEST_CODES)

        # Generation runs against the raw (still-templated) final step --
        # {{var}} placeholders are just ordinary strings to the mutation
        # engine; they're resolved later, right before each case executes.
        generated = generate_test_cases(final_step, categories, body_field_tests, header_tests)

        chain_run = ChainRun.objects.create(
            chain=chain,
            categories=categories,
            body_field_tests=body_field_tests,
            header_tests=header_tests,
            status=ChainRun.STATUS_RUNNING,
        )

        pairs = []
        for case_data in generated:
            chain_test_case = ChainTestCase.objects.create(
                chain_run=chain_run,
                category=case_data['category'],
                description=case_data['description'],
                request_method=case_data['request_method'],
                request_url=case_data['request_url'],
                request_headers=case_data['request_headers'],
                request_body=case_data['request_body'],
                request_body_raw=case_data['request_body_raw'],
                body_mode=case_data['body_mode'],
            )
            pairs.append((chain_test_case, case_data))

        if pairs:
            thread = threading.Thread(
                target=_run_chain_in_background, args=(chain_run.id, pairs), daemon=True
            )
            thread.start()
        else:
            chain_run.status = ChainRun.STATUS_COMPLETED
            chain_run.completed_at = timezone.now()
            chain_run.save(update_fields=['status', 'completed_at'])

        return Response(ChainRunSerializer(chain_run).data, status=status.HTTP_201_CREATED)


class ChainRunListView(generics.ListAPIView):
    queryset = ChainRun.objects.all()
    serializer_class = ChainRunListSerializer


class ChainRunDetailView(generics.RetrieveAPIView):
    queryset = ChainRun.objects.all()
    serializer_class = ChainRunSerializer
