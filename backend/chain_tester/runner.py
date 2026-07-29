"""Executes an ApiChain.

Setup steps (every step except the last) build up a shared variable context
by running once, in order -- a step marked 'per_test' gets re-run to
refresh its value before each generated test case of the final step, since
a value like a single-use token would otherwise go stale after its first
use and break every case after the first for reasons that have nothing to
do with the mutation actually being tested.

The final step's mutation cases are generated once, up front, straight from
apitester.test_generator against the *raw* (still-templated) step -- a
{{var}} placeholder is just an ordinary string to that code, so generation
doesn't need to know or care about substitution. Placeholders are only
resolved right before a case is actually sent.
"""
import json
import re

from django.utils import timezone

from apitester.test_executor import execute_test_case, run_and_save
from apitester.test_generator import _parse_path

from .models import ChainRun, ChainStep, ChainStepResult, ChainTestCase

_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')


def substitute(value, context):
    """Recursively replaces {{var}} in strings; dict/list values are walked
    recursively. An unresolved (unknown) variable name is left as literal
    text rather than blanked, so a typo shows up as a visibly wrong request
    instead of a silently empty one."""
    if isinstance(value, str):
        def repl(match):
            name = match.group(1)
            return str(context[name]) if name in context else match.group(0)
        return _PLACEHOLDER_RE.sub(repl, value)
    if isinstance(value, dict):
        return {key: substitute(val, context) for key, val in value.items()}
    if isinstance(value, list):
        return [substitute(item, context) for item in value]
    return value


def case_from_step(step):
    """Builds an execute_test_case()-shaped dict from a ChainStep, without
    resolving any {{var}} placeholders yet."""
    if step.is_json_body and step.body is not None:
        body_mode = 'json'
    elif step.body_raw:
        body_mode = 'raw'
    else:
        body_mode = 'none'
    return {
        'category': 'setup',
        'request_method': step.method,
        'request_url': step.url,
        'request_headers': dict(step.headers or {}),
        'request_body': step.body,
        'request_body_raw': step.body_raw,
        'body_mode': body_mode,
    }


def substitute_case(case_data, context):
    return {
        **case_data,
        'request_url': substitute(case_data['request_url'], context),
        'request_headers': substitute(case_data.get('request_headers') or {}, context),
        'request_body': substitute(case_data.get('request_body'), context),
        'request_body_raw': substitute(case_data.get('request_body_raw'), context),
    }


def extract_values(rules, status_code, response_body):
    """Runs each {var_name: path} rule against a step's result. 'status_code'
    is a special-cased path; anything else navigates the parsed JSON
    response body (a leading 'body' path segment is stripped for
    readability, e.g. 'body.id' and 'id' are equivalent). Falls back to None
    on a non-JSON body or a path that doesn't resolve -- never raises, since
    a bad extraction rule shouldn't take down the whole run."""
    if not rules:
        return {}

    parsed_body = None
    if response_body:
        try:
            parsed_body = json.loads(response_body)
        except (json.JSONDecodeError, TypeError):
            parsed_body = None

    result = {}
    for var_name, path in rules.items():
        if path == 'status_code':
            result[var_name] = status_code
            continue
        tokens = _parse_path(path)
        if tokens and tokens[0] == 'body':
            tokens = tokens[1:]
        value = parsed_body
        for token in tokens:
            if isinstance(value, dict) and isinstance(token, str):
                value = value.get(token)
            elif isinstance(value, list) and isinstance(token, int) and 0 <= token < len(value):
                value = value[token]
            else:
                value = None
                break
        result[var_name] = value
    return result


def _run_setup_step(chain_run, step, context):
    """Runs one setup step (substituting from `context`), creates/overwrites
    its ChainStepResult, merges any extracted values into `context` in
    place. Returns the raw execution result dict so the caller can check
    for a hard failure."""
    case_data = substitute_case(case_from_step(step), context)
    result = execute_test_case(case_data, verify_ssl=chain_run.verify_ssl)

    extracted = {}
    if not result['error']:
        extracted = extract_values(step.extract_rules, result['status_code'], result['response_body'])
        context.update(extracted)

    ChainStepResult.objects.update_or_create(
        chain_run=chain_run,
        step=step,
        defaults={
            'status_code': result['status_code'],
            'response_body': result['response_body'],
            'error': result['error'],
            'executed_at': result['executed_at'],
            'extracted': extracted,
        },
    )
    return result


def run_chain(chain_run_id, pairs):
    """Orchestrates a chain run: runs setup steps once to build a base
    context, then for each pre-created (pending) ChainTestCase + its raw
    case dict, refreshes any 'per_test' setup steps, substitutes the
    context into the case, and executes it. `pairs` mirrors apitester's
    (test_case, case_data) handoff pattern. Safe to call from a background
    thread; the caller is responsible for closing the DB connection after."""
    chain_run = ChainRun.objects.select_related('chain').get(pk=chain_run_id)
    steps = list(chain_run.chain.steps.order_by('order'))
    setup_steps = steps[:-1]
    once_steps = [s for s in setup_steps if s.refresh_mode == ChainStep.REFRESH_ONCE]
    per_test_steps = [s for s in setup_steps if s.refresh_mode == ChainStep.REFRESH_PER_TEST]

    # Only 'once' steps run in this initial pass. A 'per_test' step is
    # skipped here on purpose: whatever value it produced would be
    # immediately overwritten by its own per-case refresh below before the
    # very first case runs, so running it here too would just be a wasted
    # HTTP call. (This means a 'once' step can't depend on a value a later
    # 'per_test' step produces -- order foundational/reusable setup before
    # anything that needs refreshing.)
    base_context = {}
    for step in once_steps:
        result = _run_setup_step(chain_run, step, base_context)
        if result['error']:
            chain_run.status = ChainRun.STATUS_FAILED
            chain_run.error = (
                f"Setup step {step.order} ('{step.method} {step.url}') failed: {result['error']}"
            )
            chain_run.completed_at = timezone.now()
            chain_run.save()
            return

    for chain_test_case, case_data in pairs:
        context = dict(base_context)
        refresh_failure = None
        for step in per_test_steps:
            result = _run_setup_step(chain_run, step, context)
            if result['error']:
                refresh_failure = (step, result)
                break

        if refresh_failure:
            step, result = refresh_failure
            chain_test_case.error = (
                f"Setup step {step.order} ('{step.method} {step.url}') failed while "
                f"refreshing context: {result['error']}"
            )
            chain_test_case.outcome = ChainTestCase.OUTCOME_ERROR
            chain_test_case.executed_at = timezone.now()
            chain_test_case.context_snapshot = context
            chain_test_case.save()
            continue

        substituted = substitute_case(case_data, context)
        chain_test_case.request_url = substituted['request_url']
        chain_test_case.request_headers = substituted['request_headers']
        chain_test_case.request_body = substituted['request_body']
        chain_test_case.request_body_raw = substituted['request_body_raw']
        chain_test_case.context_snapshot = context
        chain_test_case.save()

        run_and_save(chain_test_case, substituted, verify_ssl=chain_run.verify_ssl)

    chain_run.status = ChainRun.STATUS_COMPLETED
    chain_run.completed_at = timezone.now()
    chain_run.save()
