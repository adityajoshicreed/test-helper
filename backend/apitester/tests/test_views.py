from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from apitester.models import ImportedRequest, TestRun


class _SyncThread:
    """Stand-in for threading.Thread that runs its target immediately, in
    the calling thread, when .start() is called -- same pattern used by
    credential_tester's tests, so the background-execution code path can be
    exercised deterministically instead of racing a real thread against the
    test's own transaction teardown."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class StopTestRunViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _import(self):
        response = self.client.post(
            '/api/import-curl/', {'curl': 'curl https://api.example.com/x'}, format='json'
        )
        return response.json()

    def test_stop_on_completed_run_returns_400(self):
        imported = self._import()
        run = TestRun.objects.create(
            imported_request_id=imported['id'], status=TestRun.STATUS_COMPLETED
        )
        response = self.client.post(f'/api/test-runs/{run.id}/stop/')
        self.assertEqual(response.status_code, 400)
        run.refresh_from_db()
        self.assertFalse(run.stop_requested)

    def test_stop_on_already_stopped_run_returns_400(self):
        imported = self._import()
        run = TestRun.objects.create(
            imported_request_id=imported['id'], status=TestRun.STATUS_STOPPED
        )
        response = self.client.post(f'/api/test-runs/{run.id}/stop/')
        self.assertEqual(response.status_code, 400)

    def test_stop_on_running_run_sets_flag_but_leaves_status_running(self):
        # Flipping the status is the background thread's job, once it next
        # checks the flag -- the view itself only requests the stop.
        imported = self._import()
        run = TestRun.objects.create(
            imported_request_id=imported['id'], status=TestRun.STATUS_RUNNING
        )
        response = self.client.post(f'/api/test-runs/{run.id}/stop/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['stop_requested'])
        self.assertEqual(body['status'], 'running')
        run.refresh_from_db()
        self.assertTrue(run.stop_requested)
        self.assertEqual(run.status, TestRun.STATUS_RUNNING)


class BackgroundRunnerStopBehaviorTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('apitester.views.threading.Thread', _SyncThread)
    @patch('apitester.test_executor.requests.request')
    def test_setting_stop_requested_mid_run_halts_remaining_cases(self, mock_request):
        response_stub = MagicMock(status_code=200, headers={}, text='{}')
        imported = self.client.post(
            '/api/import-curl/', {'curl': 'curl https://api.example.com/x'}, format='json'
        ).json()

        call_count = {'n': 0}

        def side_effect(method, url, **kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                # Simulate a user clicking Stop while the first case's
                # request is still in flight.
                TestRun.objects.filter(imported_request_id=imported['id']).update(stop_requested=True)
            return response_stub

        mock_request.side_effect = side_effect

        # 'http_method' generates several cases on top of the always-included
        # baseline, so there's at least one still-pending case for the
        # background runner to skip once it notices the stop flag.
        response = self.client.post(
            f'/api/imported-requests/{imported["id"]}/test-runs/',
            {'categories': ['http_method']},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        run_id = response.json()['id']

        run = TestRun.objects.get(pk=run_id)
        self.assertEqual(run.status, TestRun.STATUS_STOPPED)
        self.assertIsNotNone(run.completed_at)
        self.assertTrue(run.test_cases.count() > 1)
        # Only the first case (in flight when Stop was clicked) actually ran.
        self.assertEqual(call_count['n'], 1)
        executed = [tc for tc in run.test_cases.all() if tc.executed_at]
        pending = [tc for tc in run.test_cases.all() if not tc.executed_at]
        self.assertEqual(len(executed), 1)
        self.assertTrue(len(pending) >= 1)

    @patch('apitester.views.threading.Thread', _SyncThread)
    @patch('apitester.test_executor.requests.request')
    def test_run_completes_normally_when_never_stopped(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200, headers={}, text='{}')
        imported = self.client.post(
            '/api/import-curl/', {'curl': 'curl https://api.example.com/x'}, format='json'
        ).json()

        response = self.client.post(
            f'/api/imported-requests/{imported["id"]}/test-runs/', {'categories': []}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        run = TestRun.objects.get(pk=response.json()['id'])
        self.assertEqual(run.status, TestRun.STATUS_COMPLETED)
        self.assertFalse(run.stop_requested)
