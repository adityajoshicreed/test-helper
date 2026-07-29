from django.db import models


class ApiChain(models.Model):
    name = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name or f'Chain #{self.pk}'


class ChainStep(models.Model):
    REFRESH_ONCE = 'once'
    REFRESH_PER_TEST = 'per_test'
    REFRESH_CHOICES = [
        (REFRESH_ONCE, 'Once'),
        (REFRESH_PER_TEST, 'Per test'),
    ]

    chain = models.ForeignKey(ApiChain, related_name='steps', on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    raw_curl = models.TextField()

    # Parsed fields -- same shape as apitester.ImportedRequest, so this model
    # can be fed directly into apitester.test_generator's functions.
    method = models.CharField(max_length=10)
    url = models.TextField()
    headers = models.JSONField(default=dict)
    body = models.JSONField(null=True, blank=True)
    body_raw = models.TextField(null=True, blank=True)
    is_json_body = models.BooleanField(default=False)

    refresh_mode = models.CharField(max_length=10, choices=REFRESH_CHOICES, default=REFRESH_ONCE)
    # {var_name: "body.path.to.value"} -- "status_code" is a special-cased path.
    extract_rules = models.JSONField(default=dict)

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['chain', 'order'], name='unique_chain_step_order'),
        ]

    def __str__(self):
        return f'Step {self.order}: {self.method} {self.url}'


class ChainRun(models.Model):
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

    chain = models.ForeignKey(ApiChain, related_name='runs', on_delete=models.CASCADE)
    categories = models.JSONField(default=list)
    body_field_tests = models.JSONField(default=dict)
    header_tests = models.JSONField(default=dict)
    # False skips TLS certificate verification (for every step in the
    # chain), for targets behind a self-signed or internal-CA certificate.
    verify_ssl = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'ChainRun #{self.pk} ({self.status})'


class ChainStepResult(models.Model):
    """Latest execution snapshot of a setup step (not the final one) for a
    run. For a 'per_test' step this row is overwritten on every refresh --
    only the most recent state matters for debugging, not a full history of
    every re-run."""
    chain_run = models.ForeignKey(ChainRun, related_name='step_results', on_delete=models.CASCADE)
    step = models.ForeignKey(ChainStep, on_delete=models.CASCADE)
    status_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    extracted = models.JSONField(default=dict)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['step__order']

    def __str__(self):
        return f'Result for {self.step} (run #{self.chain_run_id})'


class ChainTestCase(models.Model):
    """Mirrors apitester.TestCase field-for-field so test_executor.run_and_save()
    works on it unmodified."""
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

    chain_run = models.ForeignKey(ChainRun, related_name='test_cases', on_delete=models.CASCADE)
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

    # Resolved {{var}} values actually used for this specific mutation, for
    # debugging why a particular test failed.
    context_snapshot = models.JSONField(default=dict)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.category}: {self.description}'
