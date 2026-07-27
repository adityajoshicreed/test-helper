"""Hand-written parser for curl commands (e.g. output of browser "Copy as cURL").

Not a full curl clone -- covers the flags that matter for API testing:
method, headers, JSON/raw body, basic auth, cookies, user-agent, referer.
Multipart form data (-F) is not supported.
"""
import json
import shlex
from base64 import b64encode
from dataclasses import dataclass, field


# Flags that take no value (booleans) -- safe to ignore for our purposes.
_NOOP_FLAGS = {
    '-k', '--insecure', '-L', '--location', '--compressed', '-s', '--silent',
    '-v', '--verbose', '-i', '--include', '-#', '--progress-bar', '-f',
    '--fail', '-N', '--no-buffer', '--http1.1', '--http2',
}

# Flags that take a value but that we intentionally ignore.
_IGNORED_VALUE_FLAGS = {
    '--connect-timeout', '--max-time', '-m', '--retry', '--proxy', '-x',
    '--cacert', '--cert', '-E', '--key', '--resolve', '--interface',
}


@dataclass
class ParsedCurl:
    method: str = 'GET'
    url: str = ''
    headers: dict = field(default_factory=dict)
    body: object = None       # parsed JSON (dict/list) if the body is valid JSON
    body_raw: str = None      # raw body text if it isn't valid JSON (or JSON parsing wasn't attempted)
    is_json_body: bool = False

    def to_dict(self):
        return {
            'method': self.method,
            'url': self.url,
            'headers': self.headers,
            'body': self.body,
            'body_raw': self.body_raw,
            'is_json_body': self.is_json_body,
        }


class CurlParseError(ValueError):
    pass


def parse_curl(raw: str) -> ParsedCurl:
    text = raw.strip()
    if not text:
        raise CurlParseError('Empty curl command.')

    # Normalize line continuations from copy-pasted multi-line curl commands.
    text = text.replace('\\\n', ' ').replace('\\\r\n', ' ')

    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise CurlParseError(f'Could not tokenize curl command: {exc}') from exc

    if not tokens:
        raise CurlParseError('Empty curl command.')

    if tokens[0] == 'curl':
        tokens = tokens[1:]

    result = ParsedCurl()
    explicit_method = None
    data_parts = []
    force_get = False
    user_pass = None
    url_from_flag = None
    positional_url = None

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]

        def next_val(flag_name):
            nonlocal i
            if i + 1 >= n:
                raise CurlParseError(f'Flag {flag_name} expects a value.')
            i += 1
            return tokens[i]

        if tok in ('-X', '--request'):
            explicit_method = next_val(tok).upper()
        elif tok in ('-H', '--header'):
            header_str = next_val(tok)
            if ':' in header_str:
                key, _, value = header_str.partition(':')
                result.headers[key.strip()] = value.strip()
        elif tok in ('-d', '--data', '--data-raw', '--data-binary', '--data-ascii'):
            data_parts.append(next_val(tok))
        elif tok == '--data-urlencode':
            data_parts.append(next_val(tok))
        elif tok in ('-u', '--user'):
            user_pass = next_val(tok)
        elif tok in ('-b', '--cookie'):
            result.headers.setdefault('Cookie', next_val(tok))
        elif tok in ('-A', '--user-agent'):
            result.headers.setdefault('User-Agent', next_val(tok))
        elif tok in ('-e', '--referer'):
            result.headers.setdefault('Referer', next_val(tok))
        elif tok in ('-G', '--get'):
            force_get = True
        elif tok == '--url':
            url_from_flag = next_val(tok)
        elif tok in _NOOP_FLAGS:
            pass
        elif tok in _IGNORED_VALUE_FLAGS:
            next_val(tok)
        elif tok.startswith('-') and tok != '-':
            # Unknown flag. If it looks like it should take a value but we
            # don't recognize it, best-effort skip just the flag itself.
            pass
        else:
            if positional_url is None:
                positional_url = tok

        i += 1

    result.url = url_from_flag or positional_url or ''
    if not result.url:
        raise CurlParseError('Could not find a URL in the curl command.')

    if user_pass is not None:
        token = b64encode(user_pass.encode('utf-8')).decode('ascii')
        result.headers['Authorization'] = f'Basic {token}'

    if data_parts:
        raw_body = '&'.join(data_parts) if len(data_parts) > 1 else data_parts[0]
        if force_get:
            separator = '&' if '?' in result.url else '?'
            result.url = f'{result.url}{separator}{raw_body}'
            result.method = explicit_method or 'GET'
        else:
            result.method = explicit_method or 'POST'
            _assign_body(result, raw_body)
    else:
        result.method = explicit_method or 'GET'

    return result


def _assign_body(result: ParsedCurl, raw_body: str):
    content_type = ''
    for key, value in result.headers.items():
        if key.lower() == 'content-type':
            content_type = value.lower()
            break

    looks_json = raw_body.strip().startswith('{') or raw_body.strip().startswith('[')
    if 'json' in content_type or (not content_type and looks_json):
        try:
            result.body = json.loads(raw_body)
            result.is_json_body = True
            return
        except (json.JSONDecodeError, ValueError):
            pass

    result.body_raw = raw_body
    result.is_json_body = False
