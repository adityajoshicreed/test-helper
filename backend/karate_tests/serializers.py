from rest_framework import serializers

from .models import KarateTestCaseJob


class KarateTestCaseJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = KarateTestCaseJob
        fields = [
            'id', 'reports_dir', 'excel_path', 'environment', 'pre_requisite',
            'created_by', 'sprint', 'status', 'feature_count', 'scenario_count',
            'step_count', 'warnings', 'error', 'created_at', 'completed_at',
        ]
        read_only_fields = fields


class KarateTestCaseJobListSerializer(serializers.ModelSerializer):
    class Meta:
        model = KarateTestCaseJob
        fields = ['id', 'reports_dir', 'excel_path', 'status', 'scenario_count', 'created_at', 'completed_at']
