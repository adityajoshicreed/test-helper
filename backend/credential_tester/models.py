from django.db import models


class CredentialRun(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_PAUSED = 'paused_awaiting_credentials'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_PAUSED, 'Paused (awaiting fresh credentials)'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    raw_curl = models.TextField()

    # Parsed fields -- same shape as apitester.ImportedRequest, so this model
    # can be fed directly into apitester.test_generator's functions.
    method = models.CharField(max_length=10)
    url = models.TextField()
    headers = models.JSONField(default=dict)
    body = models.JSONField(null=True, blank=True)
    body_raw = models.TextField(null=True, blank=True)
    is_json_body = models.BooleanField(default=False)

    # [{"location": "header"|"body", "key": "<header name or body path>"}]
    credential_fields = models.JSONField(default=list)
    # {key: value} -- current value for each declared credential field.
    # Overwritten wholesale every time the run is resumed with fresh values.
    current_values = models.JSONField(default=dict)

    expiration_status_code = models.IntegerField(null=True, blank=True)
    expiration_message_contains = models.CharField(max_length=500, blank=True, default='')

    categories = models.JSONField(default=list)
    body_field_tests = models.JSONField(default=dict)
    header_tests = models.JSONField(default=dict)
    verify_ssl = models.BooleanField(default=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    pause_count = models.IntegerField(default=0)
    pause_reason = models.TextField(blank=True, default='')
    error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'CredentialRun #{self.pk} ({self.status})'


class CredentialTestCase(models.Model):
    """Mirrors apitester.TestCase field-for-field so the same result-writing
    logic (and the frontend's TestRunResults/TestRunProgress) works with no
    changes at all."""
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

    run = models.ForeignKey(CredentialRun, related_name='test_cases', on_delete=models.CASCADE)
    category = models.CharField(max_length=50)
    description = models.CharField(max_length=255)

    request_method = models.CharField(max_length=10)
    request_url = models.TextField()
    request_headers = models.JSONField(default=dict)
    request_body = models.JSONField(null=True, blank=True)
    request_body_raw = models.TextField(null=True, blank=True)
    body_mode = models.CharField(max_length=10, default='none')

    status_code = models.IntegerField(null=True, blank=True)
    response_headers = models.JSONField(null=True, blank=True)
    response_body = models.TextField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    rate_limit_retries = models.IntegerField(default=0)
    rate_limit_wait_seconds = models.FloatField(default=0)

    # Snapshot of current_values actually used when this case executed, for
    # debugging -- e.g. confirming a retry after resume really used the new
    # value and not a stale one.
    credential_values_used = models.JSONField(default=dict)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.category}: {self.description}'
