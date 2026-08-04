from django.db import models as django_models
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LoadTestPlan, PlannedLoadTest
from .runner import PreflightError, record_result
from .serializers import LoadTestPlanListSerializer, LoadTestPlanSerializer, PlannedLoadTestSerializer


class LoadTestPlanListCreateView(APIView):
    def get(self, request):
        plans = LoadTestPlan.objects.all()
        return Response(LoadTestPlanListSerializer(plans, many=True).data)

    def post(self, request):
        name = request.data.get('name', '')
        if not isinstance(name, str) or not name.strip():
            return Response(
                {'error': 'Provide a non-empty "name" for the plan.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        api_name = request.data.get('api_name', '')
        if not isinstance(api_name, str):
            api_name = ''
        plan = LoadTestPlan.objects.create(name=name.strip(), api_name=api_name.strip())
        return Response(LoadTestPlanSerializer(plan).data, status=status.HTTP_201_CREATED)


class LoadTestPlanDetailView(generics.RetrieveAPIView):
    queryset = LoadTestPlan.objects.all()
    serializer_class = LoadTestPlanSerializer


class PlannedLoadTestCreateView(APIView):
    def post(self, request, pk):
        plan = get_object_or_404(LoadTestPlan, pk=pk)

        name = request.data.get('name', '')
        if not isinstance(name, str) or not name.strip():
            return Response(
                {'error': 'Provide a non-empty "name" for the test.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            planned_duration_minutes = float(request.data.get('planned_duration_minutes'))
            planned_tps = float(request.data.get('planned_tps'))
        except (TypeError, ValueError):
            return Response(
                {'error': '"planned_duration_minutes" and "planned_tps" must be numbers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if planned_duration_minutes <= 0 or planned_tps <= 0:
            return Response(
                {'error': '"planned_duration_minutes" and "planned_tps" must be positive numbers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        jmeter_csv_filename = request.data.get('jmeter_csv_filename', '') or ''
        server_metrics_csv_filename = request.data.get('server_metrics_csv_filename', '') or ''

        next_order = (plan.tests.aggregate(django_models.Max('order'))['order__max'] or 0) + 1
        planned_test = PlannedLoadTest.objects.create(
            plan=plan,
            order=next_order,
            name=name.strip(),
            planned_duration_minutes=planned_duration_minutes,
            planned_tps=planned_tps,
            jmeter_csv_filename=jmeter_csv_filename.strip() if isinstance(jmeter_csv_filename, str) else '',
            server_metrics_csv_filename=(
                server_metrics_csv_filename.strip() if isinstance(server_metrics_csv_filename, str) else ''
            ),
        )
        return Response(PlannedLoadTestSerializer(planned_test).data, status=status.HTTP_201_CREATED)


class RecordLoadTestResultView(APIView):
    def post(self, request, pk):
        planned_test = get_object_or_404(PlannedLoadTest, pk=pk)
        if planned_test.status == PlannedLoadTest.STATUS_RECORDED:
            return Response(
                {'error': 'This test already has a recorded result -- add a new planned test to record again.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        jmeter_file = request.FILES.get('jmeter_csv')
        server_metrics_file = request.FILES.get('server_metrics_csv')
        if not jmeter_file or not server_metrics_file:
            return Response(
                {'error': 'Provide both "jmeter_csv" and "server_metrics_csv" files.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            record_result(planned_test, jmeter_file, server_metrics_file)
        except PreflightError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PlannedLoadTestSerializer(planned_test).data, status=status.HTTP_201_CREATED)
