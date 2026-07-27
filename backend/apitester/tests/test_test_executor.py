from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apitester import test_executor


def make_case(**overrides):
    defaults = dict(
        category='baseline',
        request_method='GET',
        request_url='https://api.example.com/x',
        request_headers={},
        request_body=None,
        request_body_raw=None,
        body_mode='none',
    )
    defaults.update(overrides)
    return defaults


def mock_response(status_code, headers=None, text='{}'):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text
    return resp


class RetryAfterParsingTests(SimpleTestCase):
    def test_parses_integer_seconds(self):
        self.assertEqual(test_executor._parse_retry_after('5'), 5.0)

    def test_parses_float_seconds(self):
        self.assertEqual(test_executor._parse_retry_after('2.5'), 2.5)

    def test_returns_none_for_missing_header(self):
        self.assertIsNone(test_executor._parse_retry_after(None))

    def test_returns_none_for_unparseable_value(self):
        self.assertIsNone(test_executor._parse_retry_after('not-a-date-or-number'))

    def test_caps_at_max_retry_after(self):
        wait = test_executor._rate_limit_wait_seconds(0, '9999')
        self.assertEqual(wait, test_executor.MAX_RETRY_AFTER_SECONDS)


class BackoffTests(SimpleTestCase):
    def test_exponential_backoff_without_retry_after_header(self):
        self.assertEqual(test_executor._rate_limit_wait_seconds(0, None), test_executor.BASE_BACKOFF_SECONDS)
        self.assertEqual(test_executor._rate_limit_wait_seconds(1, None), test_executor.BASE_BACKOFF_SECONDS * 2)
        self.assertEqual(test_executor._rate_limit_wait_seconds(2, None), test_executor.BASE_BACKOFF_SECONDS * 4)

    def test_backoff_caps_at_max(self):
        wait = test_executor._rate_limit_wait_seconds(10, None)
        self.assertEqual(wait, test_executor.MAX_BACKOFF_SECONDS)


class ExecuteTestCaseRateLimitTests(SimpleTestCase):
    @patch('apitester.test_executor.time.sleep')
    @patch('apitester.test_executor.requests.request')
    def test_retries_on_429_and_succeeds(self, mock_request, mock_sleep):
        mock_request.side_effect = [
            mock_response(429, {'Retry-After': '2'}),
            mock_response(200),
        ]
        result = test_executor.execute_test_case(make_case())
        self.assertEqual(result['status_code'], 200)
        self.assertEqual(result['rate_limit_retries'], 1)
        self.assertEqual(result['rate_limit_wait_seconds'], 2.0)
        self.assertEqual(result['outcome'], 'info')  # baseline, succeeded after retry
        mock_sleep.assert_called_once_with(2.0)
        self.assertEqual(mock_request.call_count, 2)

    @patch('apitester.test_executor.time.sleep')
    @patch('apitester.test_executor.requests.request')
    def test_gives_up_after_max_retries_and_marks_rate_limited(self, mock_request, mock_sleep):
        mock_request.side_effect = [mock_response(429) for _ in range(test_executor.MAX_RATE_LIMIT_RETRIES + 1)]
        result = test_executor.execute_test_case(make_case())
        self.assertEqual(result['status_code'], 429)
        self.assertEqual(result['outcome'], 'rate_limited')
        self.assertEqual(result['rate_limit_retries'], test_executor.MAX_RATE_LIMIT_RETRIES)
        self.assertEqual(mock_request.call_count, test_executor.MAX_RATE_LIMIT_RETRIES + 1)
        self.assertEqual(mock_sleep.call_count, test_executor.MAX_RATE_LIMIT_RETRIES)

    @patch('apitester.test_executor.time.sleep')
    @patch('apitester.test_executor.requests.request')
    def test_no_retry_when_not_rate_limited(self, mock_request, mock_sleep):
        mock_request.return_value = mock_response(404)
        result = test_executor.execute_test_case(make_case(category='body_field_null'))
        self.assertEqual(result['rate_limit_retries'], 0)
        self.assertEqual(result['outcome'], 'handled')
        mock_sleep.assert_not_called()
        self.assertEqual(mock_request.call_count, 1)

    @patch('apitester.test_executor.time.sleep')
    @patch('apitester.test_executor.requests.request')
    def test_falls_back_to_backoff_without_retry_after_header(self, mock_request, mock_sleep):
        mock_request.side_effect = [mock_response(429), mock_response(200)]
        test_executor.execute_test_case(make_case())
        mock_sleep.assert_called_once_with(test_executor.BASE_BACKOFF_SECONDS)

    @patch('apitester.test_executor.time.sleep')
    @patch('apitester.test_executor.requests.request')
    def test_network_error_is_not_retried(self, mock_request, mock_sleep):
        import requests as requests_module
        mock_request.side_effect = requests_module.exceptions.ConnectionError('boom')
        result = test_executor.execute_test_case(make_case())
        self.assertEqual(result['error'], 'boom')
        self.assertEqual(result['outcome'], 'error')
        self.assertEqual(result['rate_limit_retries'], 0)
        mock_sleep.assert_not_called()
        self.assertEqual(mock_request.call_count, 1)
