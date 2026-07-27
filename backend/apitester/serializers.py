from rest_framework import serializers

from .models import ImportedRequest, TestCase, TestRun
from .test_generator import (
    available_categories,
    body_field_options,
    detect_dynamic_headers,
    header_field_options,
)


class ImportedRequestSerializer(serializers.ModelSerializer):
    available_test_categories = serializers.SerializerMethodField()
    body_field_options = serializers.SerializerMethodField()
    header_field_options = serializers.SerializerMethodField()
    dynamic_headers = serializers.SerializerMethodField()

    class Meta:
        model = ImportedRequest
        fields = [
            'id', 'raw_curl', 'method', 'url', 'headers', 'body', 'body_raw',
            'is_json_body', 'created_at', 'available_test_categories',
            'body_field_options', 'header_field_options', 'dynamic_headers',
        ]
        read_only_fields = fields

    def get_available_test_categories(self, obj):
        return available_categories(obj)

    def get_body_field_options(self, obj):
        return body_field_options(obj)

    def get_header_field_options(self, obj):
        return header_field_options(obj)

    def get_dynamic_headers(self, obj):
        return detect_dynamic_headers(obj.headers)


class ImportedRequestListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportedRequest
        fields = ['id', 'method', 'url', 'created_at']


class TestCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestCase
        fields = [
            'id', 'category', 'description',
            'request_method', 'request_url', 'request_headers',
            'request_body', 'request_body_raw', 'body_mode',
            'status_code', 'response_headers', 'response_body',
            'latency_ms', 'error', 'outcome', 'executed_at',
            'rate_limit_retries', 'rate_limit_wait_seconds',
        ]


class TestRunSerializer(serializers.ModelSerializer):
    test_cases = TestCaseSerializer(many=True, read_only=True)
    imported_request = ImportedRequestListSerializer(read_only=True)

    class Meta:
        model = TestRun
        fields = [
            'id', 'imported_request', 'categories', 'body_field_tests', 'header_tests',
            'status', 'created_at', 'completed_at', 'test_cases',
        ]


class TestRunListSerializer(serializers.ModelSerializer):
    imported_request = ImportedRequestListSerializer(read_only=True)

    class Meta:
        model = TestRun
        fields = ['id', 'imported_request', 'categories', 'status', 'created_at', 'completed_at']
