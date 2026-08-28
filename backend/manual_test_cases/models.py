from django.db import models


class ManualTestSuite(models.Model):
    """A container for hand-authored test cases -- the "New" view builds one
    up interactively (add a case, add its steps, add another case, ...) and
    "Export to Excel" writes the whole thing out in one go."""
    name = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name or f'Suite #{self.pk}'


class ManualTestCase(models.Model):
    """One row of the same field set the Karate Test Case Generator's Excel
    sheet uses, entered by hand instead of derived from a report."""
    suite = models.ForeignKey(ManualTestSuite, related_name='test_cases', on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    environment = models.CharField(max_length=255, blank=True, default='')
    pre_requisite = models.TextField(blank=True, default='')
    created_by = models.CharField(max_length=255, blank=True, default='')
    sprint = models.CharField(max_length=255, blank=True, default='')
    lob = models.CharField(max_length=255, blank=True, default='')
    vertical = models.CharField(max_length=255, blank=True, default='')
    feasible_for_automation = models.CharField(max_length=255, blank=True, default='')
    test_case_applicability = models.CharField(max_length=255, blank=True, default='')
    labels = models.CharField(max_length=255, blank=True, default='')
    # Renamed from the Excel column's plain "Status" to avoid ambiguity with
    # other models' run-status fields, matching karate_tests.KarateTestCaseJob.
    test_case_status = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['suite', 'order'], name='unique_suite_case_order'),
        ]

    def __str__(self):
        return f'{self.name} (case #{self.order} of suite {self.suite_id})'


class ManualTestStep(models.Model):
    test_case = models.ForeignKey(ManualTestCase, related_name='steps', on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    description = models.TextField(blank=True, default='')
    test_data = models.TextField(blank=True, default='')
    expected_result = models.TextField(blank=True, default='')
    actual_result = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['test_case', 'order'], name='unique_case_step_order'),
        ]

    def __str__(self):
        return f'Step {self.order} of case {self.test_case_id}'
