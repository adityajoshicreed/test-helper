from django.db import models


class LoadTestPlan(models.Model):
    name = models.CharField(max_length=255)
    api_name = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name or f'Plan #{self.pk}'


class PlannedLoadTest(models.Model):
    STATUS_PLANNED = 'planned'
    STATUS_RECORDED = 'recorded'
    STATUS_CHOICES = [
        (STATUS_PLANNED, 'Planned'),
        (STATUS_RECORDED, 'Recorded'),
    ]

    plan = models.ForeignKey(LoadTestPlan, related_name='tests', on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    planned_duration_minutes = models.FloatField()
    planned_tps = models.FloatField()
    # Informational only until the test is actually recorded -- just what
    # the user intends to name the files JMeter/their metrics collector
    # will produce, so they don't have to remember it later.
    jmeter_csv_filename = models.CharField(max_length=255, blank=True, default='')
    server_metrics_csv_filename = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['plan', 'order'], name='unique_plan_test_order'),
        ]

    def __str__(self):
        return f'{self.name} (test #{self.order} of plan {self.plan_id})'


class LoadTestResult(models.Model):
    """The parsed/aggregated outcome of actually running a PlannedLoadTest --
    created once, when the user uploads the two result CSVs. Not editable
    afterwards (start a new planned test if you need to re-record)."""
    planned_test = models.OneToOneField(PlannedLoadTest, related_name='result', on_delete=models.CASCADE)

    jmeter_csv_filename = models.CharField(max_length=255)
    server_metrics_csv_filename = models.CharField(max_length=255)

    sample_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    error_rate_percent = models.FloatField(null=True, blank=True)
    actual_duration_seconds = models.FloatField(null=True, blank=True)
    actual_tps = models.FloatField(null=True, blank=True)
    avg_response_time_ms = models.FloatField(null=True, blank=True)
    min_response_time_ms = models.FloatField(null=True, blank=True)
    max_response_time_ms = models.FloatField(null=True, blank=True)
    p50_response_time_ms = models.FloatField(null=True, blank=True)
    p90_response_time_ms = models.FloatField(null=True, blank=True)
    p95_response_time_ms = models.FloatField(null=True, blank=True)
    p99_response_time_ms = models.FloatField(null=True, blank=True)

    # Bucketed time series for charts -- see load_test_tracker.runner.bucket_series.
    # response_time_series: [{"t": minutes_elapsed, "avg": ms, "p95": ms}, ...]
    # throughput_series:    [{"t": minutes_elapsed, "tps": float}, ...]
    # cpu_ram_series:       [{"t": minutes_elapsed, "cpu_percent": float, "ram_percent": float}, ...]
    response_time_series = models.JSONField(default=list)
    throughput_series = models.JSONField(default=list)
    cpu_ram_series = models.JSONField(default=list)

    warnings = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Result for {self.planned_test}'
