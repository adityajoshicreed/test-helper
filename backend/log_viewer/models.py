from django.db import models


class LogViewJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    PATTERN_SOURCE_LOG4J_XML = 'log4j_xml'
    PATTERN_SOURCE_DEFAULT = 'default'
    PATTERN_SOURCE_CHOICES = [
        (PATTERN_SOURCE_LOG4J_XML, 'log4j XML'),
        (PATTERN_SOURCE_DEFAULT, 'Default (Spring Boot)'),
    ]

    logs_dir = models.CharField(max_length=1000)
    log4j_xml_path = models.CharField(max_length=1000, blank=True, default='')

    pattern_source = models.CharField(max_length=20, choices=PATTERN_SOURCE_CHOICES, blank=True, default='')
    conversion_pattern = models.CharField(max_length=500, blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    file_count = models.IntegerField(default=0)
    entry_count = models.IntegerField(default=0)
    warnings = models.JSONField(default=list)
    error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'LogViewJob #{self.pk} ({self.status})'


class LogEntry(models.Model):
    job = models.ForeignKey(LogViewJob, related_name='entries', on_delete=models.CASCADE)

    # Stable original order (file-mtime order, then line order within a file)
    # -- used as the sort fallback whenever a line's timestamp couldn't be
    # parsed, and as the tiebreaker within an identical timestamp.
    seq = models.IntegerField()

    source_file = models.CharField(max_length=255)
    line_number = models.IntegerField()

    timestamp = models.DateTimeField(null=True, blank=True, db_index=True)
    level = models.CharField(max_length=10, blank=True, default='', db_index=True)
    thread = models.CharField(max_length=255, blank=True, default='')
    logger = models.CharField(max_length=255, blank=True, default='')
    # Includes any continuation lines (stack traces, multi-line bodies, ...)
    # that followed this entry's first line before the next line matched the
    # pattern again.
    message = models.TextField(blank=True, default='')

    # Heuristic quick-filter flags -- a hint for debugging, not a real HTTP
    # transaction parser (see log_viewer.runner._classify_request_response).
    is_request_like = models.BooleanField(default=False)
    is_response_like = models.BooleanField(default=False)

    class Meta:
        ordering = ['seq']

    def __str__(self):
        return f'{self.source_file}:{self.line_number} [{self.level}]'
