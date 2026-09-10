"""Same Karate-HTML-report-to-Excel pipeline as karate_tests.runner, plus one
extra pass: for every scenario, a local Ollama model is given the scenario's
full sequence of API calls (method/URL/response) and asked to write a
plain-English "Step Description" and "Expected Result" for each step --
replacing karate_tests' generic "Execute the CURL" / raw status+body text --
so the sheet reads like something a QA analyst wrote, not a request/response
dump.

Report parsing (find_report_files/parse_report_file/build_test_cases/curl
reconstruction) is unchanged from karate_tests.runner and reused directly
rather than duplicated -- only the AI-enhancement step and the Excel writer
(which has two extra-meaningful columns to fill) are new here.

The AI call is one request per scenario, not per API call: sending the
whole scenario at once lets the model use the flow as context (e.g. "step 2
uses the token step 1 returned" rather than describing each call in
isolation), and it's far fewer requests than one per step.

If Ollama is unreachable, times out, or returns something that can't be
parsed as the expected JSON shape, that scenario's steps just fall back to
the same default text karate_tests.runner would have used, and a warning is
recorded -- an unreachable/misconfigured local model degrades the output,
it doesn't fail the job.
"""
import json
import os
import re

import requests
from django.utils import timezone

from karate_tests.runner import (
    COLUMNS as _BASE_COLUMNS,
    PreflightError,
    build_test_cases,
    find_report_files,
    parse_report_file,
    validate_excel_path,
    validate_reports_dir,
)
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

DEFAULT_OLLAMA_BASE_URL = 'http://localhost:11434'

# Local models are often slow (CPU inference, larger models, a cold-loaded
# model needing to page in) -- generous but bounded so one stuck scenario
# can't hang the job forever.
AI_REQUEST_TIMEOUT_SECONDS = 90

# Bounds how much of each request/response body gets embedded in the
# prompt -- matches this codebase's existing pattern of capping otherwise-
# unbounded input (e.g. apitester.test_generator.MAX_PATH_DEPTH).
MAX_BODY_CHARS_IN_PROMPT = 2000

COLUMNS = _BASE_COLUMNS

_CODE_FENCE_RE = re.compile(r'^```[a-zA-Z]*\n?|\n?```$')


class AiEnhancementError(Exception):
    """Raised (and always caught by the caller) when a scenario's AI
    enhancement can't be produced for any reason -- unreachable server,
    timeout, or a response that isn't the expected JSON shape."""


def validate_ollama_base_url(base_url):
    base_url = (base_url or '').strip() or DEFAULT_OLLAMA_BASE_URL
    if not re.match(r'^https?://', base_url):
        raise PreflightError("Ollama base URL must start with 'http://' or 'https://'.")
    return base_url.rstrip('/')


def validate_ollama_model(model):
    model = (model or '').strip()
    if not model:
        raise PreflightError('Provide the name of the local Ollama model to use (e.g. "llama3.1").')
    return model


def _truncate(text, limit=MAX_BODY_CHARS_IN_PROMPT):
    if not text:
        return '(no body)'
    text = str(text)
    if len(text) <= limit:
        return text
    return f'{text[:limit]}... (truncated, {len(text)} chars total)'


def _build_prompt(scenario_name, api_steps):
    lines = [
        f'You are a QA analyst reviewing an automated API test scenario named "{scenario_name}".',
        'It made the following HTTP calls, in order:',
        '',
    ]
    for i, step in enumerate(api_steps, start=1):
        lines.append(f'Step {i}: {step["method"]} {step["url"] or "(unknown URL)"}')
        lines.append(f'  Response status: {step["status_code"] or "N/A"}')
        lines.append(f'  Response body: {_truncate(step["response_body"])}')
        lines.append('')
    lines.append(
        'For each step, write a concise, plain-English "description" of what that call is '
        'doing in the context of the overall scenario flow (not just restating the method/URL '
        '-- explain its purpose, e.g. "Log in and capture the auth token used by later steps"), '
        'and a concise plain-English "expected_result" describing what a successful response '
        'should look like, based on the actual response shown above.'
    )
    lines.append(
        'Respond with ONLY valid JSON, no markdown formatting and no commentary, in exactly '
        'this shape: {"steps": [{"step": 1, "description": "...", "expected_result": "..."}, '
        '...]} with exactly one entry per step above, in the same order.'
    )
    return '\n'.join(lines)


def _strip_code_fence(text):
    return _CODE_FENCE_RE.sub('', text.strip()).strip()


def enhance_scenario_with_ai(base_url, model, scenario_name, api_steps):
    """Returns a list of {'description', 'expected_result'} dicts, one per
    entry in `api_steps`, in order. Raises AiEnhancementError on any
    failure -- caller falls back to default text for the whole scenario."""
    prompt = _build_prompt(scenario_name, api_steps)
    try:
        response = requests.post(
            f'{base_url}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False, 'format': 'json'},
            timeout=AI_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw_text = response.json().get('response', '')
    except requests.RequestException as exc:
        raise AiEnhancementError(f'could not reach Ollama at {base_url} ({exc})') from exc
    except ValueError as exc:
        raise AiEnhancementError(f"Ollama's response wasn't valid JSON ({exc})") from exc

    try:
        parsed = json.loads(_strip_code_fence(raw_text))
        steps = parsed['steps']
        if not isinstance(steps, list) or len(steps) != len(api_steps):
            got = len(steps) if isinstance(steps, list) else type(steps).__name__
            raise ValueError(f'expected {len(api_steps)} step entries back, got {got}')
        return [
            {
                'description': (str(entry.get('description') or '').strip()) or None,
                'expected_result': (str(entry.get('expected_result') or '').strip()) or None,
            }
            for entry in steps
        ]
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError) as exc:
        raise AiEnhancementError(f"model response wasn't in the expected JSON shape ({exc})") from exc


def _format_actual_result(status_code, response_body):
    return 'Response Code: {}\nResponse Body:\n{}'.format(
        status_code or 'N/A', response_body or '(no response body)'
    )


def enhance_test_cases_with_ai(test_cases, base_url, model, warnings=None):
    """Mutates each step in `test_cases` in place, adding 'ai_description'
    and 'ai_expected_result' keys (None where AI enhancement wasn't used).
    Returns the count of scenarios successfully enhanced."""
    enhanced_count = 0
    for case in test_cases:
        try:
            results = enhance_scenario_with_ai(base_url, model, case['name'], case['steps'])
        except AiEnhancementError as exc:
            if warnings is not None:
                warnings.append(f"scenario '{case['name']}': AI enhancement failed ({exc}) -- using default step text.")
            for step in case['steps']:
                step['ai_description'] = None
                step['ai_expected_result'] = None
            continue

        enhanced_count += 1
        for step, result in zip(case['steps'], results):
            step['ai_description'] = result['description']
            step['ai_expected_result'] = result['expected_result']
    return enhanced_count


def write_excel(test_cases, excel_path, *, environment, pre_requisite, created_by, sprint,
                 lob, vertical, feasible_for_automation, test_case_applicability, labels, test_case_status):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Test Cases'
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    wrap = Alignment(wrap_text=True, vertical='top')
    merged_alignment = Alignment(wrap_text=True, vertical='center', horizontal='center')
    merged_columns = (1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 16, 17, 18)

    for case_number, case in enumerate(test_cases, start=1):
        start_row = ws.max_row + 1
        for step_number, step in enumerate(case['steps'], start=1):
            actual_result = _format_actual_result(step['status_code'], step['response_body'])
            step_description = step.get('ai_description') or 'Execute the CURL'
            expected_result = step.get('ai_expected_result') or actual_result
            is_first_step = step_number == 1
            ws.append([
                case_number if is_first_step else None,
                case['name'] if is_first_step else None,
                case['name'] if is_first_step else None,
                environment if is_first_step else None,
                pre_requisite if is_first_step else None,
                step_number, step_description, step['curl'], expected_result, actual_result,
                created_by if is_first_step else None,
                sprint if is_first_step else None,
                lob if is_first_step else None,
                vertical if is_first_step else None,
                feasible_for_automation if is_first_step else None,
                test_case_applicability if is_first_step else None,
                labels if is_first_step else None,
                test_case_status if is_first_step else None,
            ])
            for cell in ws[ws.max_row]:
                cell.alignment = wrap

        end_row = ws.max_row
        if end_row > start_row:
            for col in merged_columns:
                ws.merge_cells(start_row=start_row, start_column=col, end_row=end_row, end_column=col)
                ws.cell(row=start_row, column=col).alignment = merged_alignment

    widths = [8, 30, 30, 14, 20, 8, 30, 60, 45, 45, 14, 12, 12, 14, 18, 20, 16, 12]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width

    parent = os.path.dirname(excel_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    wb.save(excel_path)


def generate(job):
    """Runs the full pipeline for a KarateAiTestCaseJob, writing progress/
    results onto `job` and saving it. Safe to call from a background thread."""
    try:
        files = find_report_files(job.reports_dir)
        warnings = []
        all_cases = []
        feature_count = 0

        for path in files:
            try:
                feature = parse_report_file(path)
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f'{path}: {exc}')
                continue
            if feature is None:
                continue
            feature_count += 1
            step_warnings = []
            all_cases.extend(build_test_cases(feature, warnings=step_warnings))
            warnings.extend(f'{path}: {w}' for w in step_warnings)

        if feature_count == 0:
            job.status = job.STATUS_FAILED
            job.error = f"No Karate feature HTML reports found under '{job.reports_dir}'."
            job.warnings = warnings
        elif not all_cases:
            job.status = job.STATUS_FAILED
            job.error = 'Found Karate reports, but no scenario made any HTTP calls to document.'
            job.warnings = warnings
        else:
            ai_enhanced_count = enhance_test_cases_with_ai(
                all_cases, job.ollama_base_url, job.ollama_model, warnings=warnings
            )
            write_excel(
                all_cases, job.excel_path,
                environment=job.environment, pre_requisite=job.pre_requisite,
                created_by=job.created_by, sprint=job.sprint,
                lob=job.lob, vertical=job.vertical,
                feasible_for_automation=job.feasible_for_automation,
                test_case_applicability=job.test_case_applicability,
                labels=job.labels, test_case_status=job.test_case_status,
            )
            job.feature_count = feature_count
            job.scenario_count = len(all_cases)
            job.step_count = sum(len(c['steps']) for c in all_cases)
            job.ai_enhanced_scenario_count = ai_enhanced_count
            job.warnings = warnings
            job.status = job.STATUS_COMPLETED
    except Exception as exc:  # noqa: BLE001 -- background thread, must not raise
        job.status = job.STATUS_FAILED
        job.error = str(exc)

    job.completed_at = timezone.now()
    job.save()
