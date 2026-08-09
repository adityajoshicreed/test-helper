import threading
from datetime import datetime, timezone as dt_timezone

from django.db import connection
from django.db.models import Q, Value
from django.db.models.fields import DateTimeField
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LogEntry, LogViewJob
from .runner import PreflightError, generate, validate_log4j_xml_path, validate_logs_dir
from .serializers import LogEntrySerializer, LogViewJobListSerializer, LogViewJobSerializer

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100
VALID_LEVELS = {'TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'}

# Used as Coalesce fallbacks so entries with no parsed timestamp sort to the
# end of the list regardless of sort direction, instead of cluttering
# whichever end NULL happens to sort to on the DB backend in use.
_FAR_FUTURE = datetime(9999, 12, 31, tzinfo=dt_timezone.utc)
_FAR_PAST = datetime(1, 1, 1, tzinfo=dt_timezone.utc)


def _run_job_in_background(job_id):
    try:
        job = LogViewJob.objects.get(pk=job_id)
        generate(job)
    finally:
        connection.close()


class LogViewJobListCreateView(APIView):
    def get(self, request):
        jobs = LogViewJob.objects.all()
        return Response(LogViewJobListSerializer(jobs, many=True).data)

    def post(self, request):
        try:
            logs_dir = validate_logs_dir(request.data.get('logs_dir', ''))
            log4j_xml_path = validate_log4j_xml_path(request.data.get('log4j_xml_path', ''))
        except PreflightError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        job = LogViewJob.objects.create(
            logs_dir=logs_dir,
            log4j_xml_path=log4j_xml_path,
            status=LogViewJob.STATUS_RUNNING,
        )

        thread = threading.Thread(target=_run_job_in_background, args=(job.id,), daemon=True)
        thread.start()
        # If the thread finishes quickly (or, in tests, runs synchronously),
        # `job` here is still the pre-execution snapshot from .create() above.
        job.refresh_from_db()

        return Response(LogViewJobSerializer(job).data, status=status.HTTP_201_CREATED)


class LogViewJobDetailView(generics.RetrieveAPIView):
    queryset = LogViewJob.objects.all()
    serializer_class = LogViewJobSerializer


class LogEntryListView(APIView):
    def get(self, request, pk):
        job = get_object_or_404(LogViewJob, pk=pk)
        qs = job.entries.all()

        levels = [lvl.strip().upper() for lvl in request.query_params.get('level', '').split(',') if lvl.strip()]
        levels = [lvl for lvl in levels if lvl in VALID_LEVELS]
        if levels:
            qs = qs.filter(level__in=levels)

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(Q(message__icontains=search) | Q(logger__icontains=search) | Q(thread__icontains=search))

        logger_filter = request.query_params.get('logger', '').strip()
        if logger_filter:
            qs = qs.filter(logger__icontains=logger_filter)

        request_response_filter = request.query_params.get('filter', '').strip().lower()
        if request_response_filter == 'request':
            qs = qs.filter(is_request_like=True)
        elif request_response_filter == 'response':
            qs = qs.filter(is_response_like=True)

        order = request.query_params.get('order', 'asc').strip().lower()
        order = order if order in ('asc', 'desc') else 'asc'
        sort = request.query_params.get('sort', 'timestamp').strip().lower()

        if sort == 'seq':
            qs = qs.order_by('seq' if order == 'asc' else '-seq')
        else:
            fallback = _FAR_FUTURE if order == 'asc' else _FAR_PAST
            qs = qs.annotate(_sort_ts=Coalesce('timestamp', Value(fallback, output_field=DateTimeField())))
            qs = qs.order_by(
                '_sort_ts' if order == 'asc' else '-_sort_ts',
                'seq' if order == 'asc' else '-seq',
            )

        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except ValueError:
            page = 1
        try:
            page_size = int(request.query_params.get('page_size', DEFAULT_PAGE_SIZE))
        except ValueError:
            page_size = DEFAULT_PAGE_SIZE
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))

        count = qs.count()
        total_pages = max(1, -(-count // page_size))  # ceil division
        start = (page - 1) * page_size
        results = qs[start:start + page_size]

        return Response({
            'count': count,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'results': LogEntrySerializer(results, many=True).data,
        })
