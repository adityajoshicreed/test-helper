from rest_framework import serializers

from .models import LogEntry, LogViewJob


class LogViewJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = LogViewJob
        fields = [
            'id', 'logs_dir', 'log4j_xml_path', 'pattern_source', 'conversion_pattern',
            'status', 'file_count', 'entry_count', 'warnings', 'error',
            'created_at', 'completed_at',
        ]
        read_only_fields = fields


class LogViewJobListSerializer(serializers.ModelSerializer):
    class Meta:
        model = LogViewJob
        fields = ['id', 'logs_dir', 'log4j_xml_path', 'status', 'file_count', 'entry_count', 'created_at']


class LogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LogEntry
        fields = [
            'id', 'seq', 'source_file', 'line_number', 'timestamp', 'level', 'thread',
            'logger', 'message', 'is_request_like', 'is_response_like',
        ]
