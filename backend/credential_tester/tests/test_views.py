from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from credential_tester.models import CredentialRun, CredentialTestCase


class _SyncThread:
    """Stand-in for threading.Thread that runs its target immediately, in
    the calling thread, when .start() is called. Used to test the
    create/resume views' background-execution code path deterministically
    -- a real background thread racing its writes against the test's own
    transaction teardown is exactly the kind of flakiness that caused
    "database table is locked" errors across this project's test suite."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class ParseCurlPreviewViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_parses_curl_and_returns_matrix_options(self):
        response = self.client.post(
            '/api/credential-tests/parse-curl/',
            {'raw_curl': "curl -H 'Authorization: Bearer tok-1' https://api.example.com/x -d '{\"token\":\"t\"}'"},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['method'], 'POST')
        self.assertEqual(body['headers']['Authorization'], 'Bearer tok-1')
        self.assertEqual(body['body'], {'token': 't'})
        self.assertIn('body_field_options', body)
        self.assertIn('header_field_options', body)
        self.assertIn('available_test_categories', body)

    def test_missing_curl_returns_400(self):
        response = self.client.post('/api/credential-tests/parse-curl/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_invalid_curl_returns_400(self):
        response = self.client.post(
            '/api/credential-tests/parse-curl/', {'raw_curl': "curl 'unterminated"}, format='json'
        )
        self.assertEqual(response.status_code, 400)


class CreateCredentialRunValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.base_payload = {
            'raw_curl': "curl -H 'Authorization: Bearer tok-1' https://api.example.com/data",
            'credential_fields': [{'location': 'header', 'key': 'Authorization'}],
            'current_values': {'Authorization': 'Bearer tok-1'},
            'expiration_status_code': 401,
        }

    def test_missing_expiration_signal_returns_400(self):
        payload = dict(self.base_payload)
        del payload['expiration_status_code']
        response = self.client.post('/api/credential-tests/runs/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(CredentialRun.objects.count(), 0)

    def test_credential_field_referencing_unknown_header_returns_400(self):
        payload = dict(self.base_payload)
        payload['credential_fields'] = [{'location': 'header', 'key': 'X-Nope'}]
        response = self.client.post('/api/credential-tests/runs/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('X-Nope', response.json()['error'])

    def test_credential_field_referencing_unknown_body_path_returns_400(self):
        payload = dict(self.base_payload)
        payload['credential_fields'] = [{'location': 'body', 'key': 'nope'}]
        response = self.client.post('/api/credential-tests/runs/', payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_no_credential_fields_returns_400(self):
        payload = dict(self.base_payload)
        payload['credential_fields'] = []
        response = self.client.post('/api/credential-tests/runs/', payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_missing_current_value_for_declared_field_returns_400(self):
        payload = dict(self.base_payload)
        payload['current_values'] = {}
        response = self.client.post('/api/credential-tests/runs/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Authorization', response.json()['error'])

    def test_invalid_curl_returns_400(self):
        payload = dict(self.base_payload)
        payload['raw_curl'] = "curl 'unterminated"
        response = self.client.post('/api/credential-tests/runs/', payload, format='json')
        self.assertEqual(response.status_code, 400)


class CreateCredentialRunSuccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('credential_tester.views.threading.Thread', _SyncThread)
    @patch('apitester.test_executor.requests.request')
    def test_creates_run_with_pending_cases_and_spawns_background_execution(self, mock_request):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.text = '{}'
        mock_request.return_value = resp

        payload = {
            'raw_curl': "curl -H 'Authorization: Bearer tok-1' https://api.example.com/data -d '{\"a\": 1}'",
            'credential_fields': [{'location': 'header', 'key': 'Authorization'}],
            'current_values': {'Authorization': 'Bearer tok-1'},
            'expiration_status_code': 401,
            'body_field_tests': {'a': ['body_field_null']},
        }
        response = self.client.post('/api/credential-tests/runs/', payload, format='json')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        # The thread runs synchronously (see _SyncThread), so by the time
        # the request returns, execution has already completed.
        self.assertEqual(body['status'], 'completed')
        # baseline + 1 mutation.
        self.assertEqual(len(body['test_cases']), 2)

        run = CredentialRun.objects.get(pk=body['id'])
        self.assertEqual(run.status, CredentialRun.STATUS_COMPLETED)
        for case in run.test_cases.all():
            self.assertEqual(case.status_code, 200)
            self.assertEqual(case.credential_values_used, {'Authorization': 'Bearer tok-1'})


class ResumeCredentialRunViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _make_paused_run(self):
        run = CredentialRun.objects.create(
            raw_curl="curl -H 'Authorization: Bearer tok-1' https://api.example.com/data",
            method='GET', url='https://api.example.com/data',
            headers={'Authorization': 'Bearer tok-1'}, body=None, body_raw=None, is_json_body=False,
            credential_fields=[{'location': 'header', 'key': 'Authorization'}],
            current_values={'Authorization': 'Bearer tok-1'},
            expiration_status_code=401, expiration_message_contains='',
            status=CredentialRun.STATUS_PAUSED, pause_count=1,
            pause_reason="Test #1 ('Baseline') got a response matching your expiration signal (status 401).",
        )
        CredentialTestCase.objects.create(
            run=run, category='baseline', description='Baseline',
            request_method='GET', request_url=run.url, request_headers=dict(run.headers),
            body_mode='none',
        )
        return run

    def test_resume_requires_fresh_value_for_every_declared_field(self):
        run = self._make_paused_run()
        response = self.client.post(f'/api/credential-tests/runs/{run.id}/resume/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_resume_on_a_non_paused_run_returns_400(self):
        run = self._make_paused_run()
        run.status = CredentialRun.STATUS_COMPLETED
        run.save()
        response = self.client.post(
            f'/api/credential-tests/runs/{run.id}/resume/',
            {'current_values': {'Authorization': 'Bearer tok-2'}},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    @patch('credential_tester.views.threading.Thread')
    def test_resume_updates_values_and_flips_status_to_running(self, mock_thread):
        # Patch out the background thread entirely -- this test only checks
        # the view's own state transition, not execution.
        run = self._make_paused_run()
        response = self.client.post(
            f'/api/credential-tests/runs/{run.id}/resume/',
            {'current_values': {'Authorization': 'Bearer tok-2'}},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['status'], 'running')
        self.assertEqual(body['current_values'], {'Authorization': 'Bearer tok-2'})
        self.assertEqual(body['pause_reason'], '')
        mock_thread.assert_called_once()


class CredentialRunListDetailViewTests(TestCase):
    def test_list_and_detail(self):
        run = CredentialRun.objects.create(
            raw_curl='curl https://x', method='GET', url='https://x',
            headers={}, body=None, body_raw=None, is_json_body=False,
            credential_fields=[], current_values={},
            status=CredentialRun.STATUS_COMPLETED,
        )
        CredentialTestCase.objects.create(
            run=run, category='baseline', description='Baseline',
            request_method='GET', request_url='https://x', request_headers={},
            body_mode='none',
        )

        list_response = APIClient().get('/api/credential-tests/runs/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        detail_response = APIClient().get(f'/api/credential-tests/runs/{run.id}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(len(detail_response.json()['test_cases']), 1)
