from rest_framework import serializers

from apitester.test_generator import (
    available_categories,
    body_field_options,
    detect_dynamic_headers,
    header_field_options,
)

from .models import ApiChain, ChainRun, ChainStep, ChainStepResult, ChainTestCase


class ChainStepSerializer(serializers.ModelSerializer):
    # Same field names as apitester.ImportedRequestSerializer's computed
    # fields, so a step can be fed directly into the existing
    # ParsedRequestView component on the frontend.
    available_test_categories = serializers.SerializerMethodField()
    body_field_options = serializers.SerializerMethodField()
    header_field_options = serializers.SerializerMethodField()
    dynamic_headers = serializers.SerializerMethodField()

    class Meta:
        model = ChainStep
        fields = [
            'id', 'order', 'raw_curl', 'method', 'url', 'headers', 'body', 'body_raw',
            'is_json_body', 'refresh_mode', 'extract_rules',
            'available_test_categories', 'body_field_options', 'header_field_options',
            'dynamic_headers',
        ]
        read_only_fields = [f for f in fields if f not in ('refresh_mode', 'extract_rules')]

    def get_available_test_categories(self, obj):
        return available_categories(obj)

    def get_body_field_options(self, obj):
        return body_field_options(obj)

    def get_header_field_options(self, obj):
        return header_field_options(obj)

    def get_dynamic_headers(self, obj):
        return detect_dynamic_headers(obj.headers)


class ChainStepListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChainStep
        fields = ['id', 'order', 'method', 'url', 'refresh_mode']


class ApiChainSerializer(serializers.ModelSerializer):
    steps = ChainStepSerializer(many=True, read_only=True)

    class Meta:
        model = ApiChain
        fields = ['id', 'name', 'created_at', 'steps']


class ApiChainListSerializer(serializers.ModelSerializer):
    step_count = serializers.SerializerMethodField()

    class Meta:
        model = ApiChain
        fields = ['id', 'name', 'created_at', 'step_count']

    def get_step_count(self, obj):
        return obj.steps.count()


class ChainStepResultSerializer(serializers.ModelSerializer):
    step = ChainStepListSerializer(read_only=True)

    class Meta:
        model = ChainStepResult
        fields = ['id', 'step', 'status_code', 'response_body', 'error', 'extracted', 'executed_at']


class ChainTestCaseSerializer(serializers.ModelSerializer):
    # Mirrors apitester.TestCaseSerializer's field list exactly (plus
    # context_snapshot) so TestRunResults/TestRunProgress work unmodified.
    class Meta:
        model = ChainTestCase
        fields = [
            'id', 'category', 'description',
            'request_method', 'request_url', 'request_headers',
            'request_body', 'request_body_raw', 'body_mode',
            'status_code', 'response_headers', 'response_body',
            'latency_ms', 'error', 'outcome', 'executed_at',
            'rate_limit_retries', 'rate_limit_wait_seconds',
            'context_snapshot',
        ]


class ChainRunSerializer(serializers.ModelSerializer):
    test_cases = ChainTestCaseSerializer(many=True, read_only=True)
    step_results = ChainStepResultSerializer(many=True, read_only=True)
    chain = ApiChainListSerializer(read_only=True)

    class Meta:
        model = ChainRun
        fields = [
            'id', 'chain', 'categories', 'body_field_tests', 'header_tests', 'verify_ssl',
            'status', 'error', 'created_at', 'completed_at', 'step_results', 'test_cases',
        ]


class ChainRunListSerializer(serializers.ModelSerializer):
    chain = ApiChainListSerializer(read_only=True)

    class Meta:
        model = ChainRun
        fields = ['id', 'chain', 'status', 'created_at', 'completed_at']
