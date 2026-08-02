from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from credential_tester import runner
from credential_tester.models import CredentialRun, CredentialTestCase


def mock_response(status_code, text='{}'):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.text = text
    return resp


class ApplyCredentialValuesTests(SimpleTestCase):
    def test_overrides_header_value(self):
        case_data = {'request_headers': {'Authorization': 'Bearer stale'}, 'body_mode': 'none', 'request_body': None}
        runner.apply_credential_values(
            case_data, [{'location': 'header', 'key': 'Authorization'}], {'Authorization': 'Bearer fresh'}
        )
        self.assertEqual(case_data['request_headers']['Authorization'], 'Bearer fresh')

    def test_overrides_body_path_value(self):
        case_data = {'request_headers': {}, 'body_mode': 'json', 'request_body': {'token': 'stale'}}
        runner.apply_credential_values(case_data, [{'location': 'body', 'key': 'token'}], {'token': 'fresh'})
        self.assertEqual(case_data['request_body']['token'], 'fresh')

    def test_overrides_nested_body_path_value(self):
        case_data = {'request_headers': {}, 'body_mode': 'json', 'request_body': {'auth': {'token': 'stale'}}}
        runner.apply_credential_values(
            case_data, [{'location': 'body', 'key': 'auth.token'}], {'auth.token': 'fresh'}
        )
        self.assertEqual(case_data['request_body']['auth']['token'], 'fresh')

    def test_skips_header_a_mutation_already_removed(self):
        # e.g. this specific case is the 'header_missing' mutation for
        # Authorization -- re-adding it would silently undo that test.
        case_data = {'request_headers': {}, 'body_mode': 'none', 'request_body': None}
        runner.apply_credential_values(
            case_data, [{'location': 'header', 'key': 'Authorization'}], {'Authorization': 'Bearer fresh'}
        )
        self.assertEqual(case_data['request_headers'], {})

    def test_skips_body_path_when_body_mode_is_not_json(self):
        case_data = {'request_headers': {}, 'body_mode': 'raw', 'request_body': None, 'request_body_raw': '{invalid'}
        runner.apply_credential_values(case_data, [{'location': 'body', 'key': 'token'}], {'token': 'fresh'})
        self.assertIsNone(case_data['request_body'])

    def test_skips_body_path_missing_from_a_whole_body_mutation_without_crashing(self):
        # e.g. this case is "body replaced with {}" -- the path just isn't there.
        case_data = {'request_headers': {}, 'body_mode': 'json', 'request_body': {}}
        runner.apply_credential_values(
            case_data, [{'location': 'body', 'key': 'auth.token'}], {'auth.token': 'fresh'}
        )
        self.assertEqual(case_data['request_body'], {})

    def test_skips_body_path_when_body_replaced_with_a_list_without_crashing(self):
        case_data = {'request_headers': {}, 'body_mode': 'json', 'request_body': ['unexpected', 'array']}
        runner.apply_credential_values(case_data, [{'location': 'body', 'key': 'token'}], {'token': 'fresh'})
        self.assertEqual(case_data['request_body'], ['unexpected', 'array'])

    def test_ignores_a_declared_field_with_no_current_value(self):
        case_data = {'request_headers': {'X': '1'}, 'body_mode': 'none', 'request_body': None}
        runner.apply_credential_values(case_data, [{'location': 'header', 'key': 'X'}], {})
        self.assertEqual(case_data['request_headers'], {'X': '1'})

    def test_no_credential_fields_is_a_no_op(self):
        case_data = {'request_headers': {'X': '1'}, 'body_mode': 'none', 'request_body': None}
        runner.apply_credential_values(case_data, [], {})
        self.assertEqual(case_data['request_headers'], {'X': '1'})


class IsExpiredTests(SimpleTestCase):
    def test_matches_on_status_code(self):
        self.assertTrue(runner.is_expired(401, 'anything', 401, ''))

    def test_matches_on_message_substring_case_insensitive(self):
        self.assertTrue(runner.is_expired(200, 'Your TOKEN Expired', None, 'token expired'))

    def test_either_condition_is_enough_when_both_configured(self):
        self.assertTrue(runner.is_expired(401, 'unrelated body', 401, 'token expired'))
        self.assertTrue(runner.is_expired(200, 'your token expired', 401, 'token expired'))

    def test_no_match_when_neither_condition_is_met(self):
        self.assertFalse(runner.is_expired(403, 'forbidden', 401, 'token expired'))

    def test_never_matches_when_neither_signal_is_configured(self):
        self.assertFalse(runner.is_expired(401, 'token expired', None, ''))

    def test_empty_response_body_does_not_crash_message_match(self):
        self.assertFalse(runner.is_expired(200, None, None, 'token expired'))


class RunCredentialRunTests(TestCase):
    def _make_run(self, **overrides):
        defaults = dict(
            raw_curl="curl -H 'Authorization: Bearer tok-1' https://api.example.com/data",
            method='GET', url='https://api.example.com/data',
            headers={'Authorization': 'Bearer tok-1'}, body=None, body_raw=None, is_json_body=False,
            credential_fields=[{'location': 'header', 'key': 'Authorization'}],
            current_values={'Authorization': 'Bearer tok-1'},
            expiration_status_code=401, expiration_message_contains='',
            categories=[], body_field_tests={}, header_tests={}, verify_ssl=True,
            status=CredentialRun.STATUS_RUNNING,
        )
        defaults.update(overrides)
        return CredentialRun.objects.create(**defaults)

    def _add_cases(self, run, n):
        cases = []
        for i in range(n):
            cases.append(CredentialTestCase.objects.create(
                run=run, category='baseline' if i == 0 else 'http_method',
                description=f'case {i}',
                request_method='GET', request_url=run.url,
                request_headers=dict(run.headers), request_body=None, request_body_raw=None,
                body_mode='none',
            ))
        return cases

    @patch('apitester.test_executor.requests.request')
    def test_pauses_when_response_matches_expiration_signal(self, mock_request):
        run = self._make_run()
        cases = self._add_cases(run, 3)

        mock_request.side_effect = [
            mock_response(200, '{"ok": true}'),  # case 0 succeeds
            mock_response(401, 'Unauthorized'),  # case 1 triggers the pause
        ]

        runner.run_credential_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, CredentialRun.STATUS_PAUSED)
        self.assertEqual(run.pause_count, 1)
        self.assertIn('#2', run.pause_reason)
        self.assertIn('401', run.pause_reason)
        self.assertEqual(mock_request.call_count, 2)

        cases[0].refresh_from_db()
        self.assertIsNotNone(cases[0].executed_at)
        self.assertEqual(cases[0].status_code, 200)

        # The case that triggered the pause is left pending -- no result
        # was written for it, so it's naturally retried first on resume.
        cases[1].refresh_from_db()
        self.assertIsNone(cases[1].executed_at)
        self.assertIsNone(cases[1].status_code)

        cases[2].refresh_from_db()
        self.assertIsNone(cases[2].executed_at)

    @patch('apitester.test_executor.requests.request')
    def test_resume_retries_the_paused_case_first_with_the_fresh_value(self, mock_request):
        run = self._make_run()
        cases = self._add_cases(run, 2)

        mock_request.side_effect = [mock_response(401, 'Unauthorized')]  # case 0 pauses immediately
        runner.run_credential_run(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, CredentialRun.STATUS_PAUSED)

        # What the resume view does: overwrite current_values, flip back to running.
        run.current_values = {'Authorization': 'Bearer tok-2'}
        run.status = CredentialRun.STATUS_RUNNING
        run.save()

        mock_request.reset_mock()
        mock_request.side_effect = [
            mock_response(200, '{"ok": true}'),  # case 0 retried, now succeeds
            mock_response(200, '{"ok": true}'),  # case 1
        ]
        runner.run_credential_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, CredentialRun.STATUS_COMPLETED)
        self.assertIsNotNone(run.completed_at)

        cases[0].refresh_from_db()
        self.assertEqual(cases[0].status_code, 200)
        self.assertEqual(cases[0].credential_values_used, {'Authorization': 'Bearer tok-2'})

        # Prove the fresh value was actually sent, not the stale one.
        sent_headers = mock_request.call_args_list[0].kwargs['headers']
        self.assertEqual(sent_headers['Authorization'], 'Bearer tok-2')

    @patch('apitester.test_executor.requests.request')
    def test_can_pause_more_than_once_in_the_same_run(self, mock_request):
        run = self._make_run()
        self._add_cases(run, 2)

        mock_request.side_effect = [mock_response(401, 'Unauthorized')]
        runner.run_credential_run(run.id)
        run.refresh_from_db()
        self.assertEqual(run.pause_count, 1)

        run.current_values = {'Authorization': 'Bearer tok-2'}
        run.status = CredentialRun.STATUS_RUNNING
        run.save()

        mock_request.side_effect = [mock_response(401, 'Unauthorized')]  # expires again right away
        runner.run_credential_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, CredentialRun.STATUS_PAUSED)
        self.assertEqual(run.pause_count, 2)

    @patch('apitester.test_executor.requests.request')
    def test_completes_when_nothing_ever_expires(self, mock_request):
        run = self._make_run()
        self._add_cases(run, 2)
        mock_request.side_effect = [mock_response(200, '{}'), mock_response(200, '{}')]

        runner.run_credential_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, CredentialRun.STATUS_COMPLETED)
        self.assertIsNotNone(run.completed_at)

    @patch('apitester.test_executor.requests.request')
    def test_verify_ssl_false_is_passed_to_every_request(self, mock_request):
        run = self._make_run(verify_ssl=False)
        self._add_cases(run, 1)
        mock_request.side_effect = [mock_response(200, '{}')]

        runner.run_credential_run(run.id)

        self.assertFalse(mock_request.call_args_list[0].kwargs['verify'])
