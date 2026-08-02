from rest_framework import serializers

from .models import CredentialRun, CredentialTestCase


class CredentialTestCaseSerializer(serializers.ModelSerializer):
    # Mirrors apitester.TestCaseSerializer's field list exactly (plus
    # credential_values_used) so TestRunResults/TestRunProgress work
    # unmodified.
    class Meta:
        model = CredentialTestCase
        fields = [
            'id', 'category', 'description',
            'request_method', 'request_url', 'request_headers',
            'request_body', 'request_body_raw', 'body_mode',
            'status_code', 'response_headers', 'response_body',
            'latency_ms', 'error', 'outcome', 'executed_at',
            'rate_limit_retries', 'rate_limit_wait_seconds',
            'credential_values_used',
        ]


class CredentialRunSerializer(serializers.ModelSerializer):
    test_cases = CredentialTestCaseSerializer(many=True, read_only=True)

    class Meta:
        model = CredentialRun
        fields = [
            'id', 'raw_curl', 'method', 'url', 'headers', 'body', 'body_raw', 'is_json_body',
            'credential_fields', 'current_values', 'expiration_status_code', 'expiration_message_contains',
            'categories', 'body_field_tests', 'header_tests', 'verify_ssl',
            'status', 'pause_count', 'pause_reason', 'error',
            'created_at', 'completed_at', 'test_cases',
        ]


class CredentialRunListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CredentialRun
        fields = ['id', 'method', 'url', 'status', 'pause_count', 'created_at', 'completed_at']
