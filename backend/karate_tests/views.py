import threading

from django.db import connection
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import KarateTestCaseJob
from .runner import PreflightError, generate, validate_excel_path, validate_reports_dir
from .serializers import KarateTestCaseJobListSerializer, KarateTestCaseJobSerializer


def _run_job_in_background(job_id):
    try:
        job = KarateTestCaseJob.objects.get(pk=job_id)
        generate(job)
    finally:
        connection.close()


class KarateTestCaseJobListCreateView(APIView):
    def get(self, request):
        jobs = KarateTestCaseJob.objects.all()
        return Response(KarateTestCaseJobListSerializer(jobs, many=True).data)

    def post(self, request):
        data = request.data
        try:
            reports_dir = validate_reports_dir(data.get('reports_dir', ''))
            excel_path = validate_excel_path(data.get('excel_path', ''))
        except PreflightError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        job = KarateTestCaseJob.objects.create(
            reports_dir=reports_dir,
            excel_path=excel_path,
            environment=data.get('environment', ''),
            pre_requisite=data.get('pre_requisite', ''),
            created_by=data.get('created_by', ''),
            sprint=data.get('sprint', ''),
            status=KarateTestCaseJob.STATUS_RUNNING,
        )

        thread = threading.Thread(target=_run_job_in_background, args=(job.id,), daemon=True)
        thread.start()

        return Response(KarateTestCaseJobSerializer(job).data, status=status.HTTP_201_CREATED)


class KarateTestCaseJobDetailView(generics.RetrieveAPIView):
    queryset = KarateTestCaseJob.objects.all()
    serializer_class = KarateTestCaseJobSerializer
