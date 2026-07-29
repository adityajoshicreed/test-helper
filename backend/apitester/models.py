from django.db import models


class ImportedRequest(models.Model):
    raw_curl = models.TextField()
    method = models.CharField(max_length=10)
    url = models.TextField()
    headers = models.JSONField(default=dict)
    body = models.JSONField(null=True, blank=True)
    body_raw = models.TextField(null=True, blank=True)
    is_json_body = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.method} {self.url}'


class TestRun(models.Model):
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

    imported_request = models.ForeignKey(
        ImportedRequest, related_name='test_runs', on_delete=models.CASCADE
    )
    categories = models.JSONField(default=list)
    body_field_tests = models.JSONField(default=dict)
    header_tests = models.JSONField(default=dict)
    # False skips TLS certificate verification, for targets behind a
    # self-signed or internal-CA certificate.
    verify_ssl = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'TestRun #{self.pk} ({self.status})'


class TestCase(models.Model):
    OUTCOME_HANDLED = 'handled'
    OUTCOME_REVIEW = 'review'
    OUTCOME_ERROR = 'error'
    OUTCOME_INFO = 'info'
    OUTCOME_RATE_LIMITED = 'rate_limited'
    OUTCOME_CHOICES = [
        (OUTCOME_HANDLED, 'Handled'),
        (OUTCOME_REVIEW, 'Review'),
        (OUTCOME_ERROR, 'Error'),
        (OUTCOME_INFO, 'Info'),
        (OUTCOME_RATE_LIMITED, 'Rate limited'),
    ]

    test_run = models.ForeignKey(
        TestRun, related_name='test_cases', on_delete=models.CASCADE
    )
    category = models.CharField(max_length=50)
    description = models.CharField(max_length=255)

    request_method = models.CharField(max_length=10)
    request_url = models.TextField()
    request_headers = models.JSONField(default=dict)
    request_body = models.JSONField(null=True, blank=True)
    request_body_raw = models.TextField(null=True, blank=True)
    # 'none' = no body sent, 'json' = send request_body as JSON, 'raw' = send request_body_raw verbatim
    body_mode = models.CharField(max_length=10, default='none')

    status_code = models.IntegerField(null=True, blank=True)
    response_headers = models.JSONField(null=True, blank=True)
    response_body = models.TextField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    outcome = models.CharField(
        max_length=20, choices=OUTCOME_CHOICES, null=True, blank=True
    )
    executed_at = models.DateTimeField(null=True, blank=True)
    rate_limit_retries = models.IntegerField(default=0)
    rate_limit_wait_seconds = models.FloatField(default=0)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.category}: {self.description}'
