from django.db import models


class KarateAiTestCaseJob(models.Model):
    """Same job shape as karate_tests.KarateTestCaseJob (parses the same
    Karate HTML reports into the same Excel column set), plus the local
    Ollama connection details and a per-scenario AI-enhancement tally --
    how many scenarios got an AI-written step description/expected result
    vs. fell back to the default text (see karate_ai_tests.runner)."""

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

    reports_dir = models.CharField(max_length=1000)
    excel_path = models.CharField(max_length=1000)
    ollama_base_url = models.CharField(max_length=500)
    ollama_model = models.CharField(max_length=255)
    environment = models.CharField(max_length=255, blank=True, default='')
    pre_requisite = models.TextField(blank=True, default='')
    created_by = models.CharField(max_length=255, blank=True, default='')
    sprint = models.CharField(max_length=255, blank=True, default='')
    lob = models.CharField(max_length=255, blank=True, default='')
    vertical = models.CharField(max_length=255, blank=True, default='')
    feasible_for_automation = models.CharField(max_length=255, blank=True, default='')
    test_case_applicability = models.CharField(max_length=255, blank=True, default='')
    labels = models.CharField(max_length=255, blank=True, default='')
    # Renamed from the Excel column's plain "Status" to avoid colliding with
    # this job's own pending/running/completed/failed `status` below.
    test_case_status = models.CharField(max_length=255, blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    feature_count = models.IntegerField(default=0)
    scenario_count = models.IntegerField(default=0)
    step_count = models.IntegerField(default=0)
    ai_enhanced_scenario_count = models.IntegerField(default=0)
    warnings = models.JSONField(default=list)
    error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'KarateAiTestCaseJob #{self.pk} ({self.status})'
