from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apitester.test_generator import generate_test_cases
from chain_tester import runner
from chain_tester.models import ApiChain, ChainRun, ChainStep, ChainStepResult, ChainTestCase


def mock_response(status_code, text='{}'):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.text = text
    return resp


class SubstituteTests(SimpleTestCase):
    def test_replaces_single_placeholder(self):
        self.assertEqual(runner.substitute('Bearer {{token}}', {'token': 'abc'}), 'Bearer abc')

    def test_leaves_unresolved_placeholder_as_is(self):
        self.assertEqual(runner.substitute('{{missing}}', {}), '{{missing}}')

    def test_stringifies_non_string_context_values(self):
        self.assertEqual(runner.substitute('id={{id}}', {'id': 5}), 'id=5')

    def test_recurses_into_dict(self):
        result = runner.substitute({'Authorization': 'Bearer {{token}}'}, {'token': 'abc'})
        self.assertEqual(result, {'Authorization': 'Bearer abc'})

    def test_recurses_into_list(self):
        result = runner.substitute(['{{a}}', '{{b}}'], {'a': '1', 'b': '2'})
        self.assertEqual(result, ['1', '2'])

    def test_recurses_into_nested_structure(self):
        result = runner.substitute({'items': ['{{a}}', {'x': '{{b}}'}]}, {'a': '1', 'b': '2'})
        self.assertEqual(result, {'items': ['1', {'x': '2'}]})

    def test_non_string_values_pass_through_unchanged(self):
        self.assertEqual(runner.substitute(42, {}), 42)
        self.assertIsNone(runner.substitute(None, {}))
        self.assertEqual(runner.substitute(True, {}), True)


class ExtractValuesTests(SimpleTestCase):
    def test_extracts_body_path(self):
        result = runner.extract_values({'token': 'body.token'}, 200, '{"token": "abc123"}')
        self.assertEqual(result, {'token': 'abc123'})

    def test_body_prefix_is_optional(self):
        result = runner.extract_values({'id': 'id'}, 200, '{"id": 42}')
        self.assertEqual(result, {'id': 42})

    def test_extracts_status_code_special_path(self):
        result = runner.extract_values({'code': 'status_code'}, 201, '{}')
        self.assertEqual(result, {'code': 201})

    def test_missing_path_resolves_to_none(self):
        result = runner.extract_values({'missing': 'body.nope'}, 200, '{"a": 1}')
        self.assertEqual(result, {'missing': None})

    def test_non_json_body_resolves_to_none(self):
        result = runner.extract_values({'x': 'body.y'}, 200, 'not json')
        self.assertEqual(result, {'x': None})

    def test_empty_response_body_resolves_to_none(self):
        result = runner.extract_values({'x': 'body.y'}, 204, None)
        self.assertEqual(result, {'x': None})

    def test_extracts_nested_path(self):
        result = runner.extract_values({'city': 'body.address.city'}, 200, '{"address": {"city": "NY"}}')
        self.assertEqual(result, {'city': 'NY'})

    def test_extracts_array_index_path(self):
        result = runner.extract_values({'first': 'body.items[0].id'}, 200, '{"items": [{"id": 1}]}')
        self.assertEqual(result, {'first': 1})

    def test_no_rules_returns_empty_dict(self):
        self.assertEqual(runner.extract_values({}, 200, '{"a": 1}'), {})


class RunChainTests(TestCase):
    def _build_chain(self):
        """A 3-step chain: 'once' login -> 'per_test' token fetch -> final
        step (the API under test) that sends the fetched token as a header."""
        chain = ApiChain.objects.create(name='test chain')
        ChainStep.objects.create(
            chain=chain, order=1, raw_curl='curl https://api.example.com/login',
            method='GET', url='https://api.example.com/login', headers={},
            body=None, body_raw=None, is_json_body=False,
            refresh_mode=ChainStep.REFRESH_ONCE,
            extract_rules={'session': 'body.session_id'},
        )
        ChainStep.objects.create(
            chain=chain, order=2, raw_curl='curl https://api.example.com/token',
            method='GET', url='https://api.example.com/token?session={{session}}', headers={},
            body=None, body_raw=None, is_json_body=False,
            refresh_mode=ChainStep.REFRESH_PER_TEST,
            extract_rules={'token': 'body.token'},
        )
        ChainStep.objects.create(
            chain=chain, order=3, raw_curl='curl https://api.example.com/protected',
            method='POST', url='https://api.example.com/protected',
            headers={'Authorization': 'Bearer {{token}}'},
            body={'foo': 'bar'}, body_raw=None, is_json_body=True,
            refresh_mode=ChainStep.REFRESH_ONCE, extract_rules={},
        )
        return chain

    def _create_run_and_pairs(self, chain, verify_ssl=True, **selection):
        final_step = chain.steps.order_by('order').last()
        generated = generate_test_cases(final_step, **selection)
        chain_run = ChainRun.objects.create(chain=chain, status=ChainRun.STATUS_RUNNING, verify_ssl=verify_ssl)
        pairs = []
        for case_data in generated:
            chain_test_case = ChainTestCase.objects.create(
                chain_run=chain_run,
                category=case_data['category'],
                description=case_data['description'],
                request_method=case_data['request_method'],
                request_url=case_data['request_url'],
                request_headers=case_data['request_headers'],
                request_body=case_data['request_body'],
                request_body_raw=case_data['request_body_raw'],
                body_mode=case_data['body_mode'],
            )
            pairs.append((chain_test_case, case_data))
        return chain_run, pairs

    @patch('apitester.test_executor.requests.request')
    def test_per_test_step_refreshes_before_every_generated_case(self, mock_request):
        chain = self._build_chain()
        chain_run, pairs = self._create_run_and_pairs(
            chain, body_field_tests={'foo': ['body_field_null']}
        )
        # baseline + one body_field_null mutation = 2 cases.
        self.assertEqual(len(pairs), 2)

        mock_request.side_effect = [
            mock_response(200, '{"session_id": "sess-A"}'),  # step 1, once
            mock_response(200, '{"token": "tok-1"}'),  # step 2 refresh, case 1
            mock_response(200, '{"ok": true}'),  # final step, case 1
            mock_response(200, '{"token": "tok-2"}'),  # step 2 refresh, case 2
            mock_response(200, '{"ok": true}'),  # final step, case 2
        ]

        runner.run_chain(chain_run.id, pairs)

        self.assertEqual(mock_request.call_count, 5)

        chain_run.refresh_from_db()
        self.assertEqual(chain_run.status, ChainRun.STATUS_COMPLETED)

        cases = list(ChainTestCase.objects.filter(chain_run=chain_run).order_by('id'))
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].context_snapshot, {'session': 'sess-A', 'token': 'tok-1'})
        self.assertEqual(cases[1].context_snapshot, {'session': 'sess-A', 'token': 'tok-2'})
        # The token actually sent differs per case -- proving a fresh value
        # was substituted for each, not one cached value reused for both.
        self.assertEqual(cases[0].request_headers['Authorization'], 'Bearer tok-1')
        self.assertEqual(cases[1].request_headers['Authorization'], 'Bearer tok-2')
        self.assertEqual(cases[0].status_code, 200)
        self.assertEqual(cases[1].status_code, 200)

        # Only the LATEST per_test refresh is kept, not a history of every one.
        step2 = chain.steps.get(order=2)
        step2_result = ChainStepResult.objects.get(chain_run=chain_run, step=step2)
        self.assertEqual(step2_result.extracted, {'token': 'tok-2'})

        step1 = chain.steps.get(order=1)
        step1_result = ChainStepResult.objects.get(chain_run=chain_run, step=step1)
        self.assertEqual(step1_result.extracted, {'session': 'sess-A'})

    @patch('apitester.test_executor.requests.request')
    def test_once_step_runs_a_single_time_regardless_of_case_count(self, mock_request):
        chain = self._build_chain()
        chain_run, pairs = self._create_run_and_pairs(
            chain, body_field_tests={'foo': ['body_field_null', 'body_field_wrong_type']}
        )
        # baseline + 2 mutations = 3 cases; step 1 ('once') should still only fire once.
        self.assertEqual(len(pairs), 3)

        mock_request.side_effect = [
            mock_response(200, '{"session_id": "sess-A"}'),
            mock_response(200, '{"token": "t1"}'), mock_response(200, '{}'),
            mock_response(200, '{"token": "t2"}'), mock_response(200, '{}'),
            mock_response(200, '{"token": "t3"}'), mock_response(200, '{}'),
        ]

        runner.run_chain(chain_run.id, pairs)

        login_calls = [c for c in mock_request.call_args_list if 'login' in c.args[1]]
        self.assertEqual(len(login_calls), 1)

    @patch('apitester.test_executor.requests.request')
    def test_setup_step_hard_failure_aborts_run_without_executing_cases(self, mock_request):
        import requests as requests_module

        chain = self._build_chain()
        chain_run, pairs = self._create_run_and_pairs(chain, categories=['http_method'])
        self.assertGreater(len(pairs), 0)

        mock_request.side_effect = requests_module.exceptions.ConnectionError('boom')

        runner.run_chain(chain_run.id, pairs)

        chain_run.refresh_from_db()
        self.assertEqual(chain_run.status, ChainRun.STATUS_FAILED)
        self.assertIn('Setup step 1', chain_run.error)
        self.assertIn('boom', chain_run.error)

        # Nothing downstream of the failed setup step ever ran.
        self.assertEqual(mock_request.call_count, 1)
        executed = ChainTestCase.objects.filter(chain_run=chain_run, executed_at__isnull=False)
        self.assertEqual(executed.count(), 0)

    @patch('apitester.test_executor.requests.request')
    def test_per_test_refresh_failure_marks_only_that_case_as_error(self, mock_request):
        chain = self._build_chain()
        chain_run, pairs = self._create_run_and_pairs(
            chain, body_field_tests={'foo': ['body_field_null']}
        )
        self.assertEqual(len(pairs), 2)

        import requests as requests_module

        mock_request.side_effect = [
            mock_response(200, '{"session_id": "sess-A"}'),  # step 1, once
            requests_module.exceptions.ConnectionError('token service down'),  # step2 refresh, case 1
            mock_response(200, '{"token": "tok-2"}'),  # step2 refresh, case 2
            mock_response(200, '{"ok": true}'),  # final step, case 2
        ]

        runner.run_chain(chain_run.id, pairs)

        chain_run.refresh_from_db()
        # The run as a whole still completes -- one flaky refresh doesn't abort it.
        self.assertEqual(chain_run.status, ChainRun.STATUS_COMPLETED)

        cases = list(ChainTestCase.objects.filter(chain_run=chain_run).order_by('id'))
        self.assertEqual(cases[0].outcome, ChainTestCase.OUTCOME_ERROR)
        self.assertIn('token service down', cases[0].error)
        self.assertIsNone(cases[0].status_code)

        self.assertEqual(cases[1].status_code, 200)
        self.assertEqual(cases[1].context_snapshot, {'session': 'sess-A', 'token': 'tok-2'})

    @patch('apitester.test_executor.requests.request')
    def test_verify_ssl_false_on_run_is_passed_to_every_request(self, mock_request):
        chain = self._build_chain()
        chain_run, pairs = self._create_run_and_pairs(chain, verify_ssl=False)
        self.assertEqual(len(pairs), 1)  # baseline only

        mock_request.side_effect = [
            mock_response(200, '{"session_id": "sess-A"}'),  # step 1, once
            mock_response(200, '{"token": "tok-1"}'),  # step 2 refresh
            mock_response(200, '{"ok": true}'),  # final step
        ]

        runner.run_chain(chain_run.id, pairs)

        self.assertEqual(mock_request.call_count, 3)
        for call in mock_request.call_args_list:
            self.assertFalse(call.kwargs['verify'])
