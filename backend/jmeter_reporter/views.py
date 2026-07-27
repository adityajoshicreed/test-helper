import os
import threading
import uuid

from django.conf import settings
from django.db import connection
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.static import serve as static_serve
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import JmeterReportJob
from .runner import PreflightError, resolve_jmeter_bin, run_report, validate_output_dir
from .serializers import JmeterReportJobListSerializer, JmeterReportJobSerializer

UPLOAD_DIR = os.path.join(settings.BASE_DIR, 'jmeter_uploads')


def _save_uploaded_csv(uploaded_file):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # uuid prefix avoids collisions; basename strips any path components from
    # the original filename so it can't be used to escape the upload dir.
    safe_name = f'{uuid.uuid4().hex}_{os.path.basename(uploaded_file.name)}'
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, 'wb') as f:
        for chunk in uploaded_file.chunks():
            f.write(chunk)
    return dest_path


def _run_job_in_background(job_id, csv_path):
    try:
        job = JmeterReportJob.objects.get(pk=job_id)
        run_report(job, csv_path)
    finally:
        connection.close()


class JmeterReportJobListCreateView(APIView):
    def get(self, request):
        jobs = JmeterReportJob.objects.all()
        return Response(JmeterReportJobListSerializer(jobs, many=True).data)

    def post(self, request):
        uploaded_file = request.FILES.get('csv_file')
        if not uploaded_file:
            return Response(
                {'error': 'Provide a "csv_file" (the JMeter results CSV/JTL file).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            output_dir = validate_output_dir(request.data.get('output_dir', ''))
            jmeter_bin = resolve_jmeter_bin(request.data.get('jmeter_bin', ''))
        except PreflightError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        csv_path = _save_uploaded_csv(uploaded_file)

        job = JmeterReportJob.objects.create(
            csv_filename=uploaded_file.name,
            output_dir=output_dir,
            jmeter_bin=jmeter_bin,
            status=JmeterReportJob.STATUS_RUNNING,
        )

        thread = threading.Thread(
            target=_run_job_in_background, args=(job.id, csv_path), daemon=True
        )
        thread.start()

        return Response(JmeterReportJobSerializer(job).data, status=status.HTTP_201_CREATED)


class JmeterReportJobDetailView(generics.RetrieveAPIView):
    queryset = JmeterReportJob.objects.all()
    serializer_class = JmeterReportJobSerializer


class JmeterReportFileView(APIView):
    """Serves the generated HTML report (index.html and its assets)
    straight out of the job's output_dir. django.views.static.serve guards
    against path traversal outside document_root."""

    def get(self, request, pk, subpath=''):
        job = get_object_or_404(JmeterReportJob, pk=pk)
        if job.status != JmeterReportJob.STATUS_COMPLETED or not job.report_index_path:
            raise Http404('Report not available.')
        path = subpath or 'index.html'
        return static_serve(request, path, document_root=job.output_dir)
