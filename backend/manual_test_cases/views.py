from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from karate_tests.runner import PreflightError, validate_excel_path

from .models import ManualTestCase, ManualTestStep, ManualTestSuite
from .runner import export_suite_to_excel
from .serializers import (
    ManualTestCaseSerializer,
    ManualTestStepSerializer,
    ManualTestSuiteListSerializer,
    ManualTestSuiteSerializer,
)

_CASE_TEXT_FIELDS = (
    'description', 'environment', 'pre_requisite', 'created_by', 'sprint', 'lob', 'vertical',
    'feasible_for_automation', 'test_case_applicability', 'labels', 'test_case_status',
)


def _clean_str(data, key):
    value = data.get(key, '')
    return value.strip() if isinstance(value, str) else ''


class ManualTestSuiteListCreateView(APIView):
    def get(self, request):
        suites = ManualTestSuite.objects.all()
        return Response(ManualTestSuiteListSerializer(suites, many=True).data)

    def post(self, request):
        suite = ManualTestSuite.objects.create(name=_clean_str(request.data, 'name'))
        return Response(ManualTestSuiteSerializer(suite).data, status=status.HTTP_201_CREATED)


class ManualTestSuiteDetailView(generics.RetrieveAPIView):
    queryset = ManualTestSuite.objects.all()
    serializer_class = ManualTestSuiteSerializer


class ManualTestCaseCreateView(APIView):
    def post(self, request, pk):
        suite = get_object_or_404(ManualTestSuite, pk=pk)
        name = _clean_str(request.data, 'name')
        if not name:
            return Response(
                {'error': 'Provide a non-empty "name" for the test case.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        next_order = (suite.test_cases.aggregate(models.Max('order'))['order__max'] or 0) + 1
        case = ManualTestCase.objects.create(
            suite=suite,
            order=next_order,
            name=name,
            **{field: _clean_str(request.data, field) for field in _CASE_TEXT_FIELDS},
        )
        return Response(ManualTestCaseSerializer(case).data, status=status.HTTP_201_CREATED)


class ManualTestStepCreateView(APIView):
    def post(self, request, pk):
        case = get_object_or_404(ManualTestCase, pk=pk)

        description = _clean_str(request.data, 'description')
        test_data = _clean_str(request.data, 'test_data')
        expected_result = _clean_str(request.data, 'expected_result')
        actual_result = _clean_str(request.data, 'actual_result')
        if not any([description, test_data, expected_result, actual_result]):
            return Response(
                {'error': 'Provide at least one of Step Description / Test Data / Expected Result / Actual Result.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        next_order = (case.steps.aggregate(models.Max('order'))['order__max'] or 0) + 1
        step = ManualTestStep.objects.create(
            test_case=case,
            order=next_order,
            description=description,
            test_data=test_data,
            expected_result=expected_result,
            actual_result=actual_result,
        )
        return Response(ManualTestStepSerializer(step).data, status=status.HTTP_201_CREATED)


class ExportManualTestSuiteExcelView(APIView):
    def post(self, request, pk):
        suite = get_object_or_404(ManualTestSuite, pk=pk)
        cases = list(suite.test_cases.order_by('order'))
        if not cases:
            return Response(
                {'error': 'Add at least one test case before exporting.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            excel_path = validate_excel_path(request.data.get('excel_path', ''))
        except PreflightError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            step_count = export_suite_to_excel(cases, excel_path)
        except OSError as exc:
            return Response({'error': f'Could not write the Excel file: {exc}'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'excel_path': excel_path,
            'exported_case_count': len(cases),
            'exported_step_count': step_count,
        })
