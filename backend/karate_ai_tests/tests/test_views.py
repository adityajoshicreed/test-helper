import tempfile
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from karate_ai_tests.models import KarateAiTestCaseJob


class _SyncThread:
    """Stand-in for threading.Thread that runs its target immediately, in
    the calling thread, when .start() is called -- makes the create-job
    view's background execution deterministic in tests (see the identical
    helper in karate_tests.tests.test_views)."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class CreateKarateAiJobViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_missing_reports_dir_returns_400(self):
        response = self.client.post(
            '/api/karate-ai/jobs/',
            {'excel_path': '/tmp/out.xlsx', 'ollama_model': 'llama3.1'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(KarateAiTestCaseJob.objects.count(), 0)

    def test_wrong_excel_extension_returns_400(self):
        with tempfile.TemporaryDirectory() as d:
            response = self.client.post(
                '/api/karate-ai/jobs/',
                {'reports_dir': d, 'excel_path': '/tmp/out.csv', 'ollama_model': 'llama3.1'},
                format='json',
            )
            self.assertEqual(response.status_code, 400)

    def test_missing_ollama_model_returns_400(self):
        with tempfile.TemporaryDirectory() as d:
            response = self.client.post(
                '/api/karate-ai/jobs/',
                {'reports_dir': d, 'excel_path': '/tmp/out.xlsx'},
                format='json',
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(KarateAiTestCaseJob.objects.count(), 0)

    def test_invalid_ollama_base_url_scheme_returns_400(self):
        with tempfile.TemporaryDirectory() as d:
            response = self.client.post(
                '/api/karate-ai/jobs/',
                {
                    'reports_dir': d, 'excel_path': '/tmp/out.xlsx',
                    'ollama_model': 'llama3.1', 'ollama_base_url': 'notaurl',
                },
                format='json',
            )
            self.assertEqual(response.status_code, 400)


class CreateKarateAiJobSuccessViewTests(TestCase):
    @patch('karate_ai_tests.views.threading.Thread', _SyncThread)
    def test_ollama_base_url_defaults_and_fields_are_stored(self):
        with tempfile.TemporaryDirectory() as d:
            response = APIClient().post(
                '/api/karate-ai/jobs/',
                {
                    'reports_dir': d,
                    'excel_path': '/tmp/out.xlsx',
                    'ollama_model': 'llama3.1',
                    'lob': 'Payments',
                    'labels': 'smoke, api',
                },
                format='json',
            )
            self.assertEqual(response.status_code, 201)
            body = response.json()
            self.assertEqual(body['ollama_base_url'], 'http://localhost:11434')
            self.assertEqual(body['ollama_model'], 'llama3.1')
            self.assertEqual(body['lob'], 'Payments')
            self.assertEqual(body['labels'], 'smoke, api')

            # The thread runs synchronously (see _SyncThread), so by the
            # time the request returns, generate() has already finished --
            # in this case failing, since the reports dir is empty (no AI
            # call is ever attempted for a job with no scenarios).
            self.assertEqual(body['status'], 'failed')


class KarateAiJobDetailViewTests(TestCase):
    def test_detail_returns_job_fields(self):
        job = KarateAiTestCaseJob.objects.create(
            reports_dir='/tmp/reports',
            excel_path='/tmp/out.xlsx',
            ollama_base_url='http://localhost:11434',
            ollama_model='llama3.1',
            status=KarateAiTestCaseJob.STATUS_RUNNING,
        )
        response = APIClient().get(f'/api/karate-ai/jobs/{job.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'running')

    def test_list_returns_summary_fields(self):
        KarateAiTestCaseJob.objects.create(
            reports_dir='/tmp/reports',
            excel_path='/tmp/out.xlsx',
            ollama_base_url='http://localhost:11434',
            ollama_model='llama3.1',
            status=KarateAiTestCaseJob.STATUS_COMPLETED,
            scenario_count=3,
        )
        response = APIClient().get('/api/karate-ai/jobs/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['scenario_count'], 3)
        self.assertEqual(body[0]['ollama_model'], 'llama3.1')
