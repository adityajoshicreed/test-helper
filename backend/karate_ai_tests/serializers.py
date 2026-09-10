from rest_framework import serializers

from .models import KarateAiTestCaseJob


class KarateAiTestCaseJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = KarateAiTestCaseJob
        fields = [
            'id', 'reports_dir', 'excel_path', 'ollama_base_url', 'ollama_model',
            'environment', 'pre_requisite', 'created_by', 'sprint', 'lob', 'vertical',
            'feasible_for_automation', 'test_case_applicability', 'labels', 'test_case_status',
            'status', 'feature_count', 'scenario_count', 'step_count', 'ai_enhanced_scenario_count',
            'warnings', 'error', 'created_at', 'completed_at',
        ]
        read_only_fields = fields


class KarateAiTestCaseJobListSerializer(serializers.ModelSerializer):
    class Meta:
        model = KarateAiTestCaseJob
        fields = ['id', 'reports_dir', 'excel_path', 'ollama_model', 'status', 'scenario_count', 'created_at', 'completed_at']
