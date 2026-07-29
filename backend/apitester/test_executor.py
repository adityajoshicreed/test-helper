"""Fires a single generated test case as a real HTTP request and classifies
the outcome with a heuristic label. The heuristic is a hint, not a verdict --
the full request/response is always surfaced so the user makes the final call.

Running many generated variants against the same endpoint in quick succession
is exactly the kind of traffic that trips an API's rate limiter, and a 429
says nothing about whether a given mutation was handled correctly -- so 429s
are retried with backoff (honoring Retry-After when the server sends one)
rather than being recorded as a normal test result.
"""
import email.utils
import time
from datetime import datetime, timezone

import requests

DEFAULT_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BODY_CHARS = 20000

# Retry/backoff tuning for HTTP 429 (Too Many Requests). Capped on both axes
# so one misbehaving target can't stall an entire test run: at most 3 retries,
# and even a server-provided Retry-After is trusted only up to 15s.
MAX_RATE_LIMIT_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 10.0
MAX_RETRY_AFTER_SECONDS = 15.0

_MUTATION_CATEGORIES = {
    'body_field_null', 'body_field_empty', 'body_field_wrong_type', 'body_field_missing',
    'body_whole', 'header_missing', 'header_empty',
}


def _parse_retry_after(value):
    """Parses a Retry-After header: either delay-seconds or an HTTP-date."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())


def _rate_limit_wait_seconds(attempt, retry_after_header):
    """How long to wait before retrying a 429 -- the server's Retry-After if
    it sent one (capped), otherwise exponential backoff (1s, 2s, 4s, ...)."""
    retry_after = _parse_retry_after(retry_after_header)
    if retry_after is not None:
        return min(retry_after, MAX_RETRY_AFTER_SECONDS)
    return min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)


def _classify_outcome(category, status_code, error):
    if error:
        return 'error'
    if status_code == 429:
        return 'rate_limited'
    if category == 'baseline':
        return 'info'
    if category == 'http_method':
        if status_code in (404, 405):
            return 'handled'
        if status_code is not None and 200 <= status_code < 300:
            return 'review'
        return 'info'
    if category in _MUTATION_CATEGORIES:
        if status_code is not None and 400 <= status_code < 500:
            return 'handled'
        if status_code is not None and 200 <= status_code < 300:
            return 'review'
        return 'info'
    return 'info'


def execute_test_case(case: dict, verify_ssl: bool = True) -> dict:
    """`case` is a dict shaped like the generator output (or TestCase fields).
    Returns a dict of result fields to merge onto the TestCase. On a 429,
    retries with backoff before giving up and recording the rate-limited
    result -- `rate_limit_retries`/`rate_limit_wait_seconds` report what
    happened so the UI can show it.

    `verify_ssl=False` skips TLS certificate verification, for targets
    behind a self-signed or internal-CA certificate."""
    method = case['request_method']
    url = case['request_url']
    headers = dict(case.get('request_headers') or {})
    body_mode = case.get('body_mode', 'none')

    request_kwargs = {'headers': headers, 'timeout': DEFAULT_TIMEOUT_SECONDS, 'verify': verify_ssl}
    if body_mode == 'json':
        request_kwargs['json'] = case.get('request_body')
    elif body_mode == 'raw':
        request_kwargs['data'] = (case.get('request_body_raw') or '').encode('utf-8')

    result = {
        'status_code': None,
        'response_headers': None,
        'response_body': None,
        'latency_ms': None,
        'error': None,
        'executed_at': None,
        'rate_limit_retries': 0,
        'rate_limit_wait_seconds': 0.0,
    }

    attempt = 0
    while True:
        start = time.monotonic()
        try:
            response = requests.request(method, url, **request_kwargs)
        except requests.exceptions.SSLError as exc:
            result['latency_ms'] = round((time.monotonic() - start) * 1000, 2)
            result['error'] = (
                f'SSL certificate verification failed: {exc}. If this target uses a '
                'self-signed or internal certificate, enable "Skip SSL certificate '
                'verification" and run again.'
            )
            break
        except requests.RequestException as exc:
            result['latency_ms'] = round((time.monotonic() - start) * 1000, 2)
            result['error'] = str(exc)
            break

        result['latency_ms'] = round((time.monotonic() - start) * 1000, 2)
        result['status_code'] = response.status_code
        result['response_headers'] = dict(response.headers)
        result['response_body'] = (response.text or '')[:MAX_RESPONSE_BODY_CHARS]
        result['error'] = None

        if response.status_code != 429 or attempt >= MAX_RATE_LIMIT_RETRIES:
            break

        wait_seconds = _rate_limit_wait_seconds(attempt, response.headers.get('Retry-After'))
        result['rate_limit_retries'] += 1
        result['rate_limit_wait_seconds'] += wait_seconds
        time.sleep(wait_seconds)
        attempt += 1

    result['executed_at'] = datetime.now(timezone.utc)
    result['outcome'] = _classify_outcome(case['category'], result['status_code'], result['error'])
    return result


def run_and_save(test_case, case_data, verify_ssl: bool = True):
    """Executes one already-persisted (pending) TestCase row and writes the
    result onto it -- used by the background runner so progress is visible
    to pollers as each row's executed_at flips from null to set."""
    result = execute_test_case(case_data, verify_ssl=verify_ssl)
    test_case.status_code = result['status_code']
    test_case.response_headers = result['response_headers']
    test_case.response_body = result['response_body']
    test_case.latency_ms = result['latency_ms']
    test_case.error = result['error']
    test_case.outcome = result['outcome']
    test_case.executed_at = result['executed_at']
    test_case.rate_limit_retries = result['rate_limit_retries']
    test_case.rate_limit_wait_seconds = result['rate_limit_wait_seconds']
    test_case.save()
