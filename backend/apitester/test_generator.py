"""Generates mutated test-case request dicts from a parsed/imported request.

Each generated case is a plain dict shaped like the request_* fields on the
TestCase model, ready to be persisted and then executed by test_executor.

Body-field and header tests are selected per-field/per-header (e.g. "run the
null and missing tests on 'email', but only the empty test on 'name'"), via
the body_field_tests / header_tests dicts passed to generate_test_cases.
Body fields are addressed by a flat path -- 'user.address.city',
'items[0].id' -- discovered by recursively walking the body (see
_iter_paths), so nested objects/arrays get their own selectable rows, not
just top-level keys. body_whole and http_method are blanket, request-level
tests (they don't target a specific field), so they're selected via the
plain categories list.
"""
import copy
import re
import uuid

_SKIP = object()

ALL_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']

# Bounds on recursive body-field discovery so a huge/deeply-nested payload
# can't blow up the number of generated test cases. A dict can have any
# number of keys at a given level; only depth and per-array breadth are capped.
MAX_PATH_DEPTH = 6
MAX_ARRAY_ITEMS_PER_LEVEL = 5

# Path segments are matched as either [<index>] or a bare/.-prefixed key.
# This assumes JSON object keys don't themselves contain '.', '[', or ']' --
# true for the vast majority of real-world APIs; a key that does would be
# misparsed, but supporting that would require path-quoting syntax for a
# vanishingly rare case.
_PATH_TOKEN_RE = re.compile(r'\[(\d+)\]|\.?([^.\[\]]+)')

BLANKET_CATEGORY_LABELS = {
    'baseline': 'Baseline (unmodified request)',
    'body_whole': 'Whole-body mutations',
    'http_method': 'Alternate HTTP methods',
}
BLANKET_CATEGORIES = {'body_whole', 'http_method'}

BODY_FIELD_TEST_LABELS = {
    'body_field_null': 'Null',
    'body_field_empty': 'Empty',
    'body_field_wrong_type': 'Wrong type',
    'body_field_missing': 'Missing',
}
BODY_FIELD_TEST_CODES = list(BODY_FIELD_TEST_LABELS.keys())

HEADER_TEST_LABELS = {
    'header_missing': 'Missing',
    'header_empty': 'Empty',
}
HEADER_TEST_CODES = list(HEADER_TEST_LABELS.keys())

# Headers commonly used as per-request nonces/idempotency keys/trace ids.
# Reusing the literal value from the imported curl on every generated case
# would either get later requests rejected as duplicates or make the API
# treat them as a retry of the same call, which defeats the point of testing
# each mutation independently. So these get a fresh value per case instead.
_DYNAMIC_HEADER_PATTERN = re.compile(
    r'(req(?:uest)?[-_]?id|correlation[-_]?id|trace[-_]?id|idempotency)',
    re.IGNORECASE,
)


def _is_dynamic_header(name):
    return bool(_DYNAMIC_HEADER_PATTERN.search(name))


def detect_dynamic_headers(headers):
    """Header names (from the imported request) that look like per-request
    nonces -- exposed to the UI so the user knows they'll be regenerated."""
    return [key for key in (headers or {}) if _is_dynamic_header(key)]


def _fresh_headers(headers):
    result = dict(headers or {})
    for key in result:
        if _is_dynamic_header(key):
            result[key] = str(uuid.uuid4())
    return result


def available_categories(imported_request):
    """Blanket (non-field-scoped) test categories, flagged by applicability."""
    has_any_body = imported_request.body is not None or bool(imported_request.body_raw)
    return [
        {'code': 'baseline', 'label': BLANKET_CATEGORY_LABELS['baseline'], 'applicable': True},
        {'code': 'body_whole', 'label': BLANKET_CATEGORY_LABELS['body_whole'], 'applicable': has_any_body},
        {'code': 'http_method', 'label': BLANKET_CATEGORY_LABELS['http_method'], 'applicable': True},
    ]


def _empty_value(value):
    if isinstance(value, bool):
        return _SKIP
    if isinstance(value, str):
        return ''
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    return _SKIP  # numbers, None -- "empty" isn't meaningful


def _wrong_type_value(value):
    if isinstance(value, bool):
        return 'true'
    if isinstance(value, str):
        return 12345
    if isinstance(value, (int, float)):
        return 'not-a-number'
    if isinstance(value, list):
        return 'not-an-array'
    if isinstance(value, dict):
        return 'not-an-object'
    return _SKIP  # value was already None


def _iter_paths(value, prefix='', depth=0):
    """Recursively walks a JSON body, yielding (path, value) for every
    dict-key/array-index node (not the root itself). A nested object or
    array gets its own path (so you can test "remove this whole object")
    in addition to each of its descendants."""
    if depth >= MAX_PATH_DEPTH:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            path = f'{prefix}.{key}' if prefix else key
            yield path, child
            yield from _iter_paths(child, path, depth + 1)
    elif isinstance(value, list):
        for idx, child in enumerate(value[:MAX_ARRAY_ITEMS_PER_LEVEL]):
            path = f'{prefix}[{idx}]'
            yield path, child
            yield from _iter_paths(child, path, depth + 1)


def _parse_path(path):
    tokens = []
    for m in _PATH_TOKEN_RE.finditer(path):
        if m.group(1) is not None:
            tokens.append(int(m.group(1)))
        else:
            tokens.append(m.group(2))
    return tokens


def _navigate(container, tokens):
    for token in tokens:
        container = container[token]
    return container


def _get_at_path(body, path):
    return _navigate(body, _parse_path(path))


def _get_at_path_safe(body, path):
    try:
        return _get_at_path(body, path)
    except (KeyError, IndexError, TypeError):
        return _SKIP


def _set_at_path(body, path, value):
    tokens = _parse_path(path)
    parent = _navigate(body, tokens[:-1])
    parent[tokens[-1]] = value


def _delete_at_path(body, path):
    tokens = _parse_path(path)
    parent = _navigate(body, tokens[:-1])
    del parent[tokens[-1]]


def body_field_options(imported_request):
    """Per-field (including nested) test applicability, for the UI to
    render a field x test matrix."""
    if not (isinstance(imported_request.body, dict) and imported_request.body):
        return []
    options = []
    for path, value in _iter_paths(imported_request.body):
        tests = [
            {'code': 'body_field_null', 'label': BODY_FIELD_TEST_LABELS['body_field_null']},
            {'code': 'body_field_missing', 'label': BODY_FIELD_TEST_LABELS['body_field_missing']},
        ]
        if _empty_value(value) is not _SKIP:
            tests.append({'code': 'body_field_empty', 'label': BODY_FIELD_TEST_LABELS['body_field_empty']})
        if _wrong_type_value(value) is not _SKIP:
            tests.append({'code': 'body_field_wrong_type', 'label': BODY_FIELD_TEST_LABELS['body_field_wrong_type']})
        options.append({'field': path, 'value_type': type(value).__name__, 'tests': tests})
    return options


def header_field_options(imported_request):
    """Per-header test applicability, for the UI to render a header x test matrix."""
    if not imported_request.headers:
        return []
    tests = [{'code': code, 'label': HEADER_TEST_LABELS[code]} for code in HEADER_TEST_CODES]
    return [{'header': key, 'tests': tests} for key in imported_request.headers]


def _base_case(imported_request):
    if imported_request.is_json_body and imported_request.body is not None:
        body_mode = 'json'
    elif imported_request.body_raw:
        body_mode = 'raw'
    else:
        body_mode = 'none'
    return {
        'request_method': imported_request.method,
        'request_url': imported_request.url,
        'request_headers': _fresh_headers(imported_request.headers),
        'request_body': copy.deepcopy(imported_request.body),
        'request_body_raw': imported_request.body_raw,
        'body_mode': body_mode,
    }


def _make_body_field_case(imported_request, path, category, value):
    mutated = copy.deepcopy(imported_request.body)

    if category == 'body_field_null':
        _set_at_path(mutated, path, None)
        description = f"Set field '{path}' to null"
    elif category == 'body_field_missing':
        _delete_at_path(mutated, path)
        description = f"Remove field '{path}' from body"
    elif category == 'body_field_empty':
        empty = _empty_value(value)
        if empty is _SKIP:
            return None
        _set_at_path(mutated, path, empty)
        description = f"Set field '{path}' to an empty value"
    elif category == 'body_field_wrong_type':
        wrong = _wrong_type_value(value)
        if wrong is _SKIP:
            return None
        _set_at_path(mutated, path, wrong)
        description = f"Set field '{path}' to an incorrect data type"
    else:
        return None

    case = _base_case(imported_request)
    case['request_body'] = mutated
    case['category'] = category
    case['description'] = description
    return case


def _make_header_case(imported_request, key, category):
    mutated_headers = _fresh_headers(imported_request.headers)

    if category == 'header_missing':
        mutated_headers.pop(key, None)
        description = f"Remove header '{key}'"
    elif category == 'header_empty':
        mutated_headers[key] = ''
        description = f"Set header '{key}' to an empty string"
    else:
        return None

    case = _base_case(imported_request)
    case['request_headers'] = mutated_headers
    case['category'] = category
    case['description'] = description
    return case


def _body_whole_cases(imported_request):
    has_json_body = isinstance(imported_request.body, (dict, list))
    has_any_body = imported_request.body is not None or bool(imported_request.body_raw)
    if not has_any_body:
        return []

    cases = []

    def add(description, *, body_mode, body=None, body_raw=None):
        case = _base_case(imported_request)
        case['request_body'] = body
        case['request_body_raw'] = body_raw
        case['body_mode'] = body_mode
        case['category'] = 'body_whole'
        case['description'] = description
        cases.append(case)

    add('Request sent with no body at all', body_mode='none')

    if has_json_body:
        add('Body replaced with empty object {}', body_mode='json', body={})
        add('Body replaced with null', body_mode='json', body=None)
        add('Body replaced with malformed / invalid JSON', body_mode='raw', body_raw='{invalid json,,,')
        if isinstance(imported_request.body, dict):
            add('Body replaced with an array instead of an object',
                body_mode='json', body=['unexpected', 'array', 'body'])
    else:
        add('Body replaced with an empty string', body_mode='raw', body_raw='')
        add('Body replaced with malformed JSON', body_mode='raw', body_raw='{invalid json,,,')

    return cases


def _http_method_cases(imported_request):
    cases = []
    for method in ALL_METHODS:
        if method == imported_request.method:
            continue
        case = _base_case(imported_request)
        case['request_method'] = method
        case['category'] = 'http_method'
        case['description'] = f'Send request using {method} instead of {imported_request.method}'
        cases.append(case)
    return cases


def generate_test_cases(imported_request, categories=None, body_field_tests=None, header_tests=None):
    """Returns a list of test-case dicts.

    'baseline' is always included first, as a control to compare against.
    `categories` selects blanket tests (body_whole / http_method).
    `body_field_tests` / `header_tests` are {name: [test codes]} maps
    selecting which specific tests run on which specific field/header --
    body field names may be nested paths like 'user.address.city' or
    'items[0].id'.
    """
    categories = set(categories or [])
    body_field_tests = body_field_tests or {}
    header_tests = header_tests or {}
    cases = []

    baseline = _base_case(imported_request)
    baseline['category'] = 'baseline'
    baseline['description'] = 'Baseline (unmodified request)'
    cases.append(baseline)

    if isinstance(imported_request.body, dict):
        for path, test_codes in body_field_tests.items():
            value = _get_at_path_safe(imported_request.body, path)
            if value is _SKIP:
                continue
            for code in test_codes:
                if code not in BODY_FIELD_TEST_CODES:
                    continue
                case = _make_body_field_case(imported_request, path, code, value)
                if case:
                    cases.append(case)

    if 'body_whole' in categories:
        cases.extend(_body_whole_cases(imported_request))

    if imported_request.headers:
        for header, test_codes in header_tests.items():
            if header not in imported_request.headers:
                continue
            for code in test_codes:
                if code not in HEADER_TEST_CODES:
                    continue
                case = _make_header_case(imported_request, header, code)
                if case:
                    cases.append(case)

    if 'http_method' in categories:
        cases.extend(_http_method_cases(imported_request))

    return cases
