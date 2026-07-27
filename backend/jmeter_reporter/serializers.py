from rest_framework import serializers

from .models import JmeterReportJob


class JmeterReportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = JmeterReportJob
        fields = [
            'id', 'csv_filename', 'output_dir', 'jmeter_bin', 'command', 'status',
            'return_code', 'stdout', 'stderr', 'report_index_path', 'error',
            'created_at', 'completed_at',
        ]
        read_only_fields = fields


class JmeterReportJobListSerializer(serializers.ModelSerializer):
    class Meta:
        model = JmeterReportJob
        fields = ['id', 'csv_filename', 'output_dir', 'status', 'created_at', 'completed_at']
