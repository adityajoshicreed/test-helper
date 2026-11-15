from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from apitester.models import TestRun
from apitester.views import _run_test_cases_in_background
from chain_tester.models import ApiChain, ChainRun, ChainStep
from chain_tester.runner import run_chain
from credential_tester.models import CredentialRun
from credential_tester.runner import run_credential_run


class PacingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        imported = self.client.post('/api/import-curl/', {
            'curl': 'curl https://example.com -H "X-Test: value"',
        }, format='json').json()
        chain = ApiChain.objects.create(name='paced')
        ChainStep.objects.create(chain=chain, order=1, raw_curl='curl https://example.com',
                                 method='GET', url='https://example.com', headers={'X-Test': 'value'})
        self.targets = [
            (f'/api/imported-requests/{imported["id"]}/test-runs/', {}, TestRun),
            (f'/api/chains/chains/{chain.id}/runs/', {}, ChainRun),
            ('/api/credential-tests/runs/', {
                'raw_curl': 'curl https://example.com -H "Authorization: token" -H "X-Test: value"',
                'credential_fields': [{'location': 'header', 'key': 'Authorization'}],
                'current_values': {'Authorization': 'token'}, 'expiration_status_code': 401,
            }, CredentialRun),
        ]

    def create_run(self, url, payload, delay):
        selection = {'header_tests': {'X-Test': ['header_missing', 'header_empty']}}
        if delay is not None:
            selection['delay_seconds'] = delay
        with patch('threading.Thread'):
            response = self.client.post(url, {**payload, **selection}, format='json')
        return response

    def execute(self, run):
        cases = list(run.test_cases.all())
        pairs = [(case, {field: getattr(case, field) for field in (
            'category', 'request_method', 'request_url', 'request_headers',
            'request_body', 'request_body_raw', 'body_mode',
        )}) for case in cases]
        if isinstance(run, TestRun):
            _run_test_cases_in_background(run.id, pairs, True)
        elif isinstance(run, ChainRun):
            run_chain(run.id, pairs)
        else:
            run_credential_run(run.id)

    def test_all_runners_wait_only_between_cases_and_persist_delay(self):
        for url, payload, model in self.targets:
            for delay in (0.25, None):
                with self.subTest(url=url, delay=delay):
                    response = self.create_run(url, payload, delay)
                    self.assertEqual(response.status_code, 201, response.data)
                    self.assertEqual(response.data['delay_seconds'], delay or 0)
                    run = model.objects.get(pk=response.data['id'])
                    events = []
                    def send(*args, **kwargs):
                        events.append('request')
                        return Mock(status_code=200, headers={}, text='{}')
                    with patch('apitester.test_executor.requests.request', side_effect=send), \
                         patch('apitester.pacing.time.sleep', side_effect=lambda seconds: events.append(seconds)):
                        self.execute(run)
                    expected = ['request', 0.25, 'request', 0.25, 'request'] if delay else ['request'] * 3
                    self.assertEqual(events, expected)
                    run.refresh_from_db()
                    self.assertEqual(run.status, 'completed')

    def test_invalid_delays_rejected_without_creating_runs(self):
        for url, payload, model in self.targets:
            for value in (-1, 61, 'slow', True, [], {}):
                with self.subTest(url=url, value=value):
                    before = model.objects.count()
                    response = self.create_run(url, payload, value)
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn('delay_seconds', response.data['error'])
                    self.assertEqual(model.objects.count(), before)

    def test_stop_during_delay_prevents_next_request(self):
        url, payload, model = self.targets[0]
        response = self.create_run(url, payload, 0.5)
        run = model.objects.get(pk=response.data['id'])
        def stop(seconds):
            model.objects.filter(pk=run.id).update(stop_requested=True)
        with patch('apitester.test_executor.requests.request', return_value=Mock(status_code=200, headers={}, text='{}')) as send, \
             patch('apitester.pacing.time.sleep', side_effect=stop):
            self.execute(run)
        self.assertEqual(send.call_count, 1)
        run.refresh_from_db()
        self.assertEqual(run.status, 'stopped')

    def test_credentials_resume_retains_delay_and_retries_pending_case(self):
        url, payload, model = self.targets[2]
        response = self.create_run(url, payload, 0.25)
        run = model.objects.get(pk=response.data['id'])
        with patch('apitester.test_executor.requests.request', side_effect=[
            Mock(status_code=200, headers={}, text='{}'), Mock(status_code=401, headers={}, text='expired'),
        ]), patch('apitester.pacing.time.sleep') as sleep:
            self.execute(run)
            sleep.assert_called_once_with(0.25)
        run.refresh_from_db()
        self.assertEqual(run.status, 'paused_awaiting_credentials')
        self.assertEqual(run.test_cases.filter(executed_at__isnull=False).count(), 1)
        with patch('credential_tester.views.threading.Thread'):
            response = self.client.post(f'/api/credential-tests/runs/{run.id}/resume/',
                                        {'current_values': {'Authorization': 'fresh'}}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        with patch('apitester.test_executor.requests.request', return_value=Mock(status_code=200, headers={}, text='{}')) as send, \
             patch('apitester.pacing.time.sleep') as sleep:
            self.execute(run)
            self.assertEqual(send.call_count, 2)
            sleep.assert_called_once_with(0.25)
        run.refresh_from_db()
        self.assertEqual(run.delay_seconds, 0.25)
        self.assertEqual(run.status, 'completed')
