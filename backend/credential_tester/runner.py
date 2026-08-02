"""Runs a CredentialRun's mutation matrix against a single endpoint whose
auth token/header value goes stale after some uses or some time.

Every generated case gets the run's current credential value(s) stamped
onto it right before it executes (apply_credential_values) -- so a case
generated once, up front, always uses the latest known-good value rather
than whatever literal value happened to be in the original curl.

The moment a response matches the configured expiration signal
(is_expired), the run pauses: that case is left pending (no result is
written for it) and nothing further executes. Resuming is just calling
run_credential_run() again after the view has overwritten current_values
with fresh input -- the loop always picks up the lowest-id pending case
first, which is exactly the one that triggered the pause, so it's retried
with the fresh values before anything else continues.
"""
import copy

from django.utils import timezone

from apitester.test_executor import execute_test_case
from apitester.test_generator import _set_at_path

from .models import CredentialRun


def apply_credential_values(case_data, credential_fields, current_values):
    """Overwrites each declared credential field's current value onto a
    generated case, in place. Applied unconditionally -- including to a
    case that happens to be mutating that same field/header (e.g. a
    "missing header" test on a header also marked as an expiring
    credential) -- the override wins in that rare overlap; see the
    "Known limitations" note in the README rather than special-casing it
    here.

    Silently skipped wherever the field/path doesn't apply to this
    specific case -- e.g. a header a "remove header" mutation already
    deleted, or a body whose shape this mutation replaced entirely (empty
    object, null, an array instead of an object, ...). Nothing meaningful
    to overwrite in those cases.
    """
    for field in credential_fields or []:
        key = field.get('key')
        if key is None or key not in current_values:
            continue
        value = current_values[key]

        if field.get('location') == 'header':
            headers = case_data.get('request_headers')
            if isinstance(headers, dict) and key in headers:
                headers[key] = value
        elif field.get('location') == 'body':
            if case_data.get('body_mode') == 'json':
                try:
                    _set_at_path(case_data['request_body'], key, value)
                except (KeyError, IndexError, TypeError):
                    pass


def is_expired(status_code, response_body, expiration_status_code, expiration_message_contains):
    """A response counts as 'expired' if the configured status code
    matches OR the configured message substring is found in the response
    body (case-insensitive) -- either one is enough when both are set.
    Never true if neither is configured."""
    if expiration_status_code is not None and status_code == expiration_status_code:
        return True
    if expiration_message_contains and expiration_message_contains.lower() in (response_body or '').lower():
        return True
    return False


def _case_data_from_test_case(test_case):
    """Rebuilds an execute_test_case()-shaped dict from a pending
    CredentialTestCase row -- these were pre-created by the view from
    generate_test_cases() output, so this is just reading those same
    fields back."""
    return {
        'category': test_case.category,
        'description': test_case.description,
        'request_method': test_case.request_method,
        'request_url': test_case.request_url,
        'request_headers': dict(test_case.request_headers or {}),
        'request_body': copy.deepcopy(test_case.request_body),
        'request_body_raw': test_case.request_body_raw,
        'body_mode': test_case.body_mode,
    }


def _save_result(test_case, result, credential_values_used):
    """Mirrors apitester.test_executor.run_and_save's field assignment --
    kept as a small local copy (rather than modifying that function) so
    apitester's own tests and behavior stay untouched, plus one extra
    field (credential_values_used) that only this tool needs."""
    test_case.status_code = result['status_code']
    test_case.response_headers = result['response_headers']
    test_case.response_body = result['response_body']
    test_case.latency_ms = result['latency_ms']
    test_case.error = result['error']
    test_case.outcome = result['outcome']
    test_case.executed_at = result['executed_at']
    test_case.rate_limit_retries = result['rate_limit_retries']
    test_case.rate_limit_wait_seconds = result['rate_limit_wait_seconds']
    test_case.credential_values_used = credential_values_used
    test_case.save()


def run_credential_run(run_id):
    """Orchestrates one CredentialRun: executes pending cases in order,
    substituting the run's current credential values into each one first.
    Pauses (and returns) the instant a response matches the expiration
    signal, leaving that case pending for the next call -- whether that's
    this same background thread continuing, or a fresh one spawned after
    the view records new credential values on resume."""
    run = CredentialRun.objects.get(pk=run_id)

    while True:
        test_case = run.test_cases.filter(executed_at__isnull=True).order_by('id').first()
        if test_case is None:
            break

        case_data = _case_data_from_test_case(test_case)
        apply_credential_values(case_data, run.credential_fields, run.current_values)

        result = execute_test_case(case_data, verify_ssl=run.verify_ssl)

        if is_expired(
            result['status_code'], result['response_body'],
            run.expiration_status_code, run.expiration_message_contains,
        ):
            position = run.test_cases.filter(executed_at__isnull=False).count() + 1
            run.status = CredentialRun.STATUS_PAUSED
            run.pause_count += 1
            run.pause_reason = (
                f"Test #{position} ('{test_case.description}') got a response matching your "
                f"expiration signal (status {result['status_code']})."
            )
            run.save()
            return

        _save_result(test_case, result, dict(run.current_values))

    run.status = CredentialRun.STATUS_COMPLETED
    run.completed_at = timezone.now()
    run.save()
