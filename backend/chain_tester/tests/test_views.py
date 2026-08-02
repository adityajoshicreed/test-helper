from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from chain_tester.models import ApiChain, ChainRun, ChainStep, ChainTestCase


class _SyncThread:
    """Stand-in for threading.Thread that runs its target immediately, in
    the calling thread, when .start() is called -- makes the create-run
    view's background execution deterministic in tests instead of racing
    a real background thread's writes against the test's own transaction
    teardown (the actual cause of intermittent "database table is locked"
    errors seen when running the full suite together)."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class CreateChainAndStepsTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_chain(self):
        response = self.client.post('/api/chains/chains/', {'name': 'my chain'}, format='json')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['name'], 'my chain')
        self.assertEqual(body['steps'], [])

    def test_add_step_parses_curl_and_assigns_order(self):
        chain = ApiChain.objects.create(name='c')
        response = self.client.post(
            f'/api/chains/chains/{chain.id}/steps/',
            {'raw_curl': "curl -X POST https://api.example.com/login -d '{\"user\":\"a\"}'"},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['order'], 1)
        self.assertEqual(body['method'], 'POST')
        self.assertEqual(body['url'], 'https://api.example.com/login')
        self.assertEqual(body['refresh_mode'], 'once')

    def test_second_step_gets_next_order(self):
        chain = ApiChain.objects.create(name='c')
        self.client.post(
            f'/api/chains/chains/{chain.id}/steps/', {'raw_curl': 'curl https://api.example.com/a'}, format='json'
        )
        response = self.client.post(
            f'/api/chains/chains/{chain.id}/steps/', {'raw_curl': 'curl https://api.example.com/b'}, format='json'
        )
        self.assertEqual(response.json()['order'], 2)

    def test_invalid_curl_returns_400(self):
        # curl_parser is intentionally lenient about *content* (any bare
        # token is treated as a URL) -- what it actually rejects is malformed
        # shell syntax, e.g. an unterminated quote.
        chain = ApiChain.objects.create(name='c')
        response = self.client.post(
            f'/api/chains/chains/{chain.id}/steps/', {'raw_curl': "curl 'unterminated"}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_only_the_last_step_would_show_body_field_options_for_its_own_body(self):
        chain = ApiChain.objects.create(name='c')
        self.client.post(
            f'/api/chains/chains/{chain.id}/steps/',
            {'raw_curl': "curl https://api.example.com/a -d '{\"x\":1}'"},
            format='json',
        )
        self.client.post(
            f'/api/chains/chains/{chain.id}/steps/',
            {'raw_curl': "curl https://api.example.com/b -d '{\"y\":2}'"},
            format='json',
        )
        detail = self.client.get(f'/api/chains/chains/{chain.id}/').json()
        steps = detail['steps']
        self.assertEqual(len(steps), 2)
        # Each step's options describe its own body -- 'x' on step 1, 'y' on step 2.
        step1_fields = {o['field'] for o in steps[0]['body_field_options']}
        step2_fields = {o['field'] for o in steps[1]['body_field_options']}
        self.assertEqual(step1_fields, {'x'})
        self.assertEqual(step2_fields, {'y'})

    def test_extract_rules_and_refresh_mode_are_stored(self):
        chain = ApiChain.objects.create(name='c')
        response = self.client.post(
            f'/api/chains/chains/{chain.id}/steps/',
            {
                'raw_curl': 'curl https://api.example.com/login',
                'refresh_mode': 'per_test',
                'extract_rules': {'token': 'body.token'},
            },
            format='json',
        )
        body = response.json()
        self.assertEqual(body['refresh_mode'], 'per_test')
        self.assertEqual(body['extract_rules'], {'token': 'body.token'})

    def test_invalid_refresh_mode_falls_back_to_once(self):
        chain = ApiChain.objects.create(name='c')
        response = self.client.post(
            f'/api/chains/chains/{chain.id}/steps/',
            {'raw_curl': 'curl https://api.example.com/login', 'refresh_mode': 'garbage'},
            format='json',
        )
        self.assertEqual(response.json()['refresh_mode'], 'once')


class CreateChainRunNoStepsTests(TestCase):
    def test_no_steps_returns_400(self):
        chain = ApiChain.objects.create(name='c')
        response = APIClient().post(f'/api/chains/chains/{chain.id}/runs/', {}, format='json')
        self.assertEqual(response.status_code, 400)


class CreateChainRunViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('chain_tester.views.threading.Thread', _SyncThread)
    @patch('apitester.test_executor.requests.request')
    def test_creates_run_with_pending_cases_and_spawns_background_execution(self, mock_request):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.text = '{}'
        mock_request.return_value = resp

        chain = ApiChain.objects.create(name='c')
        ChainStep.objects.create(
            chain=chain, order=1, raw_curl='curl https://api.example.com/x',
            method='GET', url='https://api.example.com/x', headers={},
            body={'a': 1}, body_raw=None, is_json_body=True,
        )
        response = self.client.post(
            f'/api/chains/chains/{chain.id}/runs/',
            {'body_field_tests': {'a': ['body_field_null']}},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        # The thread runs synchronously (see _SyncThread), so by the time
        # the request returns, execution has already completed.
        self.assertEqual(body['status'], 'completed')
        # baseline + 1 mutation.
        self.assertEqual(len(body['test_cases']), 2)


class ChainRunListDetailViewTests(TestCase):
    def test_list_and_detail(self):
        chain = ApiChain.objects.create(name='c')
        run = ChainRun.objects.create(chain=chain, status=ChainRun.STATUS_COMPLETED)
        ChainTestCase.objects.create(
            chain_run=run, category='baseline', description='Baseline',
            request_method='GET', request_url='https://x', request_headers={},
            body_mode='none',
        )

        list_response = APIClient().get('/api/chains/runs/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        detail_response = APIClient().get(f'/api/chains/runs/{run.id}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(len(detail_response.json()['test_cases']), 1)
