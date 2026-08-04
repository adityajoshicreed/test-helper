from rest_framework import serializers

from .models import LoadTestPlan, LoadTestResult, PlannedLoadTest


class LoadTestResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoadTestResult
        fields = [
            'id', 'jmeter_csv_filename', 'server_metrics_csv_filename',
            'sample_count', 'error_count', 'error_rate_percent',
            'actual_duration_seconds', 'actual_tps',
            'avg_response_time_ms', 'min_response_time_ms', 'max_response_time_ms',
            'p50_response_time_ms', 'p90_response_time_ms', 'p95_response_time_ms', 'p99_response_time_ms',
            'response_time_series', 'throughput_series', 'cpu_ram_series',
            'warnings', 'created_at',
        ]


class PlannedLoadTestSerializer(serializers.ModelSerializer):
    result = LoadTestResultSerializer(read_only=True)

    class Meta:
        model = PlannedLoadTest
        fields = [
            'id', 'order', 'name', 'planned_duration_minutes', 'planned_tps',
            'jmeter_csv_filename', 'server_metrics_csv_filename', 'status',
            'created_at', 'result',
        ]


class LoadTestPlanSerializer(serializers.ModelSerializer):
    tests = PlannedLoadTestSerializer(many=True, read_only=True)

    class Meta:
        model = LoadTestPlan
        fields = ['id', 'name', 'api_name', 'created_at', 'tests']


class LoadTestPlanListSerializer(serializers.ModelSerializer):
    test_count = serializers.SerializerMethodField()
    recorded_count = serializers.SerializerMethodField()

    class Meta:
        model = LoadTestPlan
        fields = ['id', 'name', 'api_name', 'created_at', 'test_count', 'recorded_count']

    def get_test_count(self, obj):
        return obj.tests.count()

    def get_recorded_count(self, obj):
        return obj.tests.filter(status=PlannedLoadTest.STATUS_RECORDED).count()
