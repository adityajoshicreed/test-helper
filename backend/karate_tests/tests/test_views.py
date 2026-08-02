import tempfile
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from karate_tests.models import KarateTestCaseJob


class _SyncThread:
    """Stand-in for threading.Thread that runs its target immediately, in
    the calling thread, when .start() is called -- makes the create-job
    view's background execution deterministic in tests instead of racing
    a real background thread's writes against the test's own transaction
    teardown (the actual cause of intermittent "database table is locked"
    errors seen when running the full suite together)."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class CreateKarateJobViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_missing_reports_dir_returns_400(self):
        response = self.client.post(
            '/api/karate/jobs/', {'excel_path': '/tmp/out.xlsx'}, format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(KarateTestCaseJob.objects.count(), 0)

    def test_relative_reports_dir_returns_400(self):
        response = self.client.post(
            '/api/karate/jobs/',
            {'reports_dir': 'relative/path', 'excel_path': '/tmp/out.xlsx'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_wrong_excel_extension_returns_400(self):
        with tempfile.TemporaryDirectory() as d:
            response = self.client.post(
                '/api/karate/jobs/',
                {'reports_dir': d, 'excel_path': '/tmp/out.csv'},
                format='json',
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(KarateTestCaseJob.objects.count(), 0)

    def test_nonexistent_reports_dir_returns_400(self):
        response = self.client.post(
            '/api/karate/jobs/',
            {'reports_dir': '/tmp/qa-helper-tool-nope-xyz', 'excel_path': '/tmp/out.xlsx'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class CreateKarateJobSuccessViewTests(TestCase):
    @patch('karate_tests.views.threading.Thread', _SyncThread)
    def test_new_excel_column_fields_are_stored_and_returned(self):
        with tempfile.TemporaryDirectory() as d:
            response = APIClient().post(
                '/api/karate/jobs/',
                {
                    'reports_dir': d,
                    'excel_path': '/tmp/out.xlsx',
                    'lob': 'Payments',
                    'vertical': 'Retail',
                    'feasible_for_automation': 'Yes',
                    'test_case_applicability': 'Regression',
                    'labels': 'smoke, api',
                    'test_case_status': 'Active',
                },
                format='json',
            )
            self.assertEqual(response.status_code, 201)
            body = response.json()
            self.assertEqual(body['lob'], 'Payments')
            self.assertEqual(body['vertical'], 'Retail')
            self.assertEqual(body['feasible_for_automation'], 'Yes')
            self.assertEqual(body['test_case_applicability'], 'Regression')
            self.assertEqual(body['labels'], 'smoke, api')
            self.assertEqual(body['test_case_status'], 'Active')

            # The thread runs synchronously (see _SyncThread), so by the
            # time the request returns, generate() has already finished --
            # in this case failing, since the reports dir is empty.
            self.assertEqual(body['status'], 'failed')


class KarateJobDetailViewTests(TestCase):
    def test_detail_returns_job_fields(self):
        job = KarateTestCaseJob.objects.create(
            reports_dir='/tmp/reports',
            excel_path='/tmp/out.xlsx',
            status=KarateTestCaseJob.STATUS_RUNNING,
        )
        response = APIClient().get(f'/api/karate/jobs/{job.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'running')

    def test_list_returns_summary_fields(self):
        KarateTestCaseJob.objects.create(
            reports_dir='/tmp/reports',
            excel_path='/tmp/out.xlsx',
            status=KarateTestCaseJob.STATUS_COMPLETED,
            scenario_count=3,
        )
        response = APIClient().get('/api/karate/jobs/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['scenario_count'], 3)
