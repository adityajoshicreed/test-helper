import os
import tempfile
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from log_viewer.models import LogEntry, LogViewJob


class _SyncThread:
    """Stand-in for threading.Thread that runs its target immediately, in
    the calling thread, when .start() is called -- same pattern used
    throughout this codebase's other background-job tests (karate_tests,
    apitester, credential_tester) to make execution deterministic instead of
    racing a real thread against the test's own transaction teardown."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class CreateLogViewJobViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_missing_logs_dir_returns_400(self):
        response = self.client.post('/api/logs/jobs/', {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(LogViewJob.objects.count(), 0)

    def test_relative_logs_dir_returns_400(self):
        response = self.client.post('/api/logs/jobs/', {'logs_dir': 'relative/path'})
        self.assertEqual(response.status_code, 400)

    def test_nonexistent_logs_dir_returns_400(self):
        response = self.client.post('/api/logs/jobs/', {'logs_dir': '/tmp/qa-helper-tool-does-not-exist-xyz'})
        self.assertEqual(response.status_code, 400)

    def test_relative_log4j_xml_path_returns_400_even_with_valid_logs_dir(self):
        with tempfile.TemporaryDirectory() as d:
            response = self.client.post('/api/logs/jobs/', {'logs_dir': d, 'log4j_xml_path': 'relative.xml'})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(LogViewJob.objects.count(), 0)

    @patch('log_viewer.views.threading.Thread', _SyncThread)
    def test_valid_folder_with_no_log_files_completes_as_failed(self):
        with tempfile.TemporaryDirectory() as d:
            response = self.client.post('/api/logs/jobs/', {'logs_dir': d})
            self.assertEqual(response.status_code, 201)
            body = response.json()
            self.assertEqual(body['status'], 'failed')
            self.assertIn('No .log files found', body['error'])

    @patch('log_viewer.views.threading.Thread', _SyncThread)
    def test_valid_folder_with_a_log_file_completes_with_default_pattern(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'app.log'), 'w') as f:
                f.write('2024-01-15 10:00:00.000  INFO 1 --- [main] c.e.Foo : hello\n')
            response = self.client.post('/api/logs/jobs/', {'logs_dir': d})
            self.assertEqual(response.status_code, 201)
            body = response.json()
            self.assertEqual(body['status'], 'completed')
            self.assertEqual(body['pattern_source'], 'default')
            self.assertEqual(body['entry_count'], 1)
            self.assertEqual(body['file_count'], 1)


class LogEntryListViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.job = LogViewJob.objects.create(logs_dir='/tmp/x', status=LogViewJob.STATUS_COMPLETED)
        self._make(seq=1, level='INFO', logger='com.example.Foo', thread='main',
                    message='GET /orders/5', is_request_like=True)
        self._make(seq=2, level='ERROR', logger='com.example.Bar', thread='worker-1',
                    message='completed with status=500', is_response_like=True)
        self._make(seq=3, level='DEBUG', logger='com.example.Foo', thread='main',
                    message='verbose detail here')
        self._make(seq=4, level='WARN', logger='com.example.Baz', thread='main',
                    message='slow query', timestamp=None)

    def _make(self, **overrides):
        defaults = dict(job=self.job, source_file='app.log', line_number=overrides.get('seq', 1))
        defaults.update(overrides)
        return LogEntry.objects.create(**defaults)

    def _get(self, params=None):
        return self.client.get(f'/api/logs/jobs/{self.job.id}/entries/', params or {})

    def test_returns_all_entries_by_default(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['count'], 4)
        self.assertEqual(len(body['results']), 4)

    def test_filters_by_level(self):
        response = self._get({'level': 'ERROR,WARN'})
        body = response.json()
        self.assertEqual(body['count'], 2)
        levels = {r['level'] for r in body['results']}
        self.assertEqual(levels, {'ERROR', 'WARN'})

    def test_search_matches_message(self):
        response = self._get({'search': 'orders'})
        body = response.json()
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['results'][0]['message'], 'GET /orders/5')

    def test_search_matches_logger_too(self):
        response = self._get({'search': 'Baz'})
        body = response.json()
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['results'][0]['logger'], 'com.example.Baz')

    def test_logger_filter_is_substring_match(self):
        response = self._get({'logger': 'Foo'})
        body = response.json()
        self.assertEqual(body['count'], 2)

    def test_request_quick_filter(self):
        response = self._get({'filter': 'request'})
        body = response.json()
        self.assertEqual(body['count'], 1)
        self.assertTrue(body['results'][0]['is_request_like'])

    def test_response_quick_filter(self):
        response = self._get({'filter': 'response'})
        body = response.json()
        self.assertEqual(body['count'], 1)
        self.assertTrue(body['results'][0]['is_response_like'])

    def test_sort_by_seq_desc(self):
        response = self._get({'sort': 'seq', 'order': 'desc'})
        body = response.json()
        self.assertEqual([r['seq'] for r in body['results']], [4, 3, 2, 1])

    def test_pagination(self):
        response = self._get({'sort': 'seq', 'order': 'asc', 'page': 2, 'page_size': 2})
        body = response.json()
        self.assertEqual(body['page'], 2)
        self.assertEqual(body['total_pages'], 2)
        self.assertEqual([r['seq'] for r in body['results']], [3, 4])

    def test_unknown_job_returns_404(self):
        response = self.client.get('/api/logs/jobs/999999/entries/')
        self.assertEqual(response.status_code, 404)


class LogViewJobListDetailViewTests(TestCase):
    def test_list_and_detail(self):
        job = LogViewJob.objects.create(logs_dir='/tmp/x', status=LogViewJob.STATUS_COMPLETED, entry_count=2)

        list_response = APIClient().get('/api/logs/jobs/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        detail_response = APIClient().get(f'/api/logs/jobs/{job.id}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()['entry_count'], 2)
