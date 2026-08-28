from rest_framework import serializers

from .models import ManualTestCase, ManualTestStep, ManualTestSuite


class ManualTestStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ManualTestStep
        fields = ['id', 'order', 'description', 'test_data', 'expected_result', 'actual_result']


class ManualTestCaseSerializer(serializers.ModelSerializer):
    steps = ManualTestStepSerializer(many=True, read_only=True)

    class Meta:
        model = ManualTestCase
        fields = [
            'id', 'order', 'name', 'description', 'environment', 'pre_requisite',
            'created_by', 'sprint', 'lob', 'vertical', 'feasible_for_automation',
            'test_case_applicability', 'labels', 'test_case_status', 'created_at', 'steps',
        ]


class ManualTestSuiteSerializer(serializers.ModelSerializer):
    test_cases = ManualTestCaseSerializer(many=True, read_only=True)

    class Meta:
        model = ManualTestSuite
        fields = ['id', 'name', 'created_at', 'test_cases']


class ManualTestSuiteListSerializer(serializers.ModelSerializer):
    test_case_count = serializers.SerializerMethodField()
    step_count = serializers.SerializerMethodField()

    class Meta:
        model = ManualTestSuite
        fields = ['id', 'name', 'created_at', 'test_case_count', 'step_count']

    def get_test_case_count(self, obj):
        return obj.test_cases.count()

    def get_step_count(self, obj):
        return ManualTestStep.objects.filter(test_case__suite=obj).count()
