"""Parses a folder of Spring Boot `.log` files into structured, sortable/
filterable rows for the log viewer UI.

If the user gives us their app's log4j (1.x or 2.x) XML config, we pull the
first `PatternLayout`/`ConversionPattern` we find in it and compile that into
a regex; otherwise (or if that XML doesn't yield a usable pattern) we fall
back to Spring Boot's own well-known default console/file pattern, so the
tool always shows *something* readable rather than erroring out.

Only a practical subset of log4j conversion specifiers is supported --
timestamp, level, thread, logger, message. Anything else (%C, %L, %X{...},
%ex, ...) is tolerated as an inert filler in the regex rather than causing a
hard failure. A line that still doesn't match the compiled pattern is folded
into the previous entry's message as a continuation line (this is how
multi-line stack traces and Spring Boot's startup banner get handled).
"""
import glob
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from xml.etree import ElementTree as ET

from django.utils import timezone

from .models import LogEntry, LogViewJob

# Hard cap so a pathologically large log folder can't stall a request or
# blow up memory/DB size -- matches this codebase's existing pattern of
# bounding otherwise-unbounded input (e.g. apitester.test_generator.MAX_PATH_DEPTH).
MAX_LOG_ENTRIES = 20_000

DEFAULT_CONVERSION_PATTERN = '%d{yyyy-MM-dd HH:mm:ss.SSS} %5p ${PID:- } --- [%15.15t] %-40.40logger{39} : %m%n'


class PreflightError(ValueError):
    """Raised for validation problems caught before we scan/parse anything."""


def validate_logs_dir(logs_dir):
    logs_dir = (logs_dir or '').strip()
    if not logs_dir:
        raise PreflightError('Provide the folder containing your .log files.')
    if not os.path.isabs(logs_dir):
        raise PreflightError('Logs folder location must be an absolute path.')
    if not os.path.isdir(logs_dir):
        raise PreflightError(f"'{logs_dir}' is not a directory (or doesn't exist).")
    return logs_dir


def validate_log4j_xml_path(path):
    """The log4j XML path is optional -- an empty value just means "use the
    default format" and is valid."""
    path = (path or '').strip()
    if not path:
        return ''
    if not os.path.isabs(path):
        raise PreflightError('log4j XML file location must be an absolute path.')
    if not os.path.isfile(path):
        raise PreflightError(f"'{path}' is not a file (or doesn't exist).")
    return path


def find_log_files(logs_dir):
    """Recursively finds `*.log` and rotated `*.log.*` files (e.g. app.log.1,
    app.log.2024-01-01), sorted by modification time -- filename order
    doesn't reflect chronological order for rotated files, mtime does.
    Compressed rotations (.gz) aren't read."""
    matches = set(glob.glob(os.path.join(logs_dir, '**', '*.log'), recursive=True))
    matches |= set(glob.glob(os.path.join(logs_dir, '**', '*.log.*'), recursive=True))
    files = [f for f in matches if os.path.isfile(f)]
    return sorted(files, key=os.path.getmtime)


def _strip_ns(tag):
    return tag.split('}', 1)[-1] if '}' in tag else tag


def parse_log4j_conversion_pattern(xml_path):
    """Returns the first conversion pattern string found in a log4j 1.x or
    2.x XML config, or None if the file is valid XML but no recognizable
    pattern element exists. Raises PreflightError if the file isn't valid XML
    at all."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        raise PreflightError(f"'{xml_path}' is not valid XML: {exc}")

    root = tree.getroot()

    # log4j2 style: <PatternLayout pattern="..."/>
    for elem in root.iter():
        if _strip_ns(elem.tag) == 'PatternLayout' and elem.get('pattern'):
            return elem.get('pattern')

    # log4j 1.x style: <layout class="...PatternLayout"><param name="ConversionPattern" value="..."/></layout>
    for elem in root.iter():
        if _strip_ns(elem.tag) == 'layout' and (elem.get('class') or '').endswith('PatternLayout'):
            for child in elem:
                if _strip_ns(child.tag) == 'param' and child.get('name') == 'ConversionPattern':
                    return child.get('value')

    return None


_DATE_NAMED_FORMATS = {
    'iso8601': 'yyyy-MM-dd HH:mm:ss,SSS',
    'absolute': 'HH:mm:ss,SSS',
}

# Longer tokens must be tried before their prefixes (yyyy before yy, SSS
# before ss's neighbors) -- the alternation below is ordered by length.
_DATE_TOKEN_MAP = {
    'yyyy': (r'\d{4}', '%Y'),
    'yy': (r'\d{2}', '%y'),
    'MM': (r'\d{2}', '%m'),
    'dd': (r'\d{2}', '%d'),
    'HH': (r'\d{2}', '%H'),
    'mm': (r'\d{2}', '%M'),
    'ss': (r'\d{2}', '%S'),
    'SSS': (r'\d{3}', '%f'),
}
_DATE_TOKEN_RE = re.compile(
    '|'.join(sorted((re.escape(t) for t in _DATE_TOKEN_MAP), key=len, reverse=True))
)


def _build_date_regex_and_format(date_spec):
    """Translates a Java date pattern (from inside a %d{...}) into a
    (regex_fragment, strptime_format) pair. Any token we don't recognize is
    kept as literal text in both -- if that means the format can no longer
    match real timestamps, the whole line just falls back to raw/continuation
    display rather than crashing."""
    date_spec = _DATE_NAMED_FORMATS.get(date_spec.strip().lower(), date_spec)
    regex_parts, strptime_parts = [], []
    pos = 0
    for m in _DATE_TOKEN_RE.finditer(date_spec):
        if m.start() > pos:
            literal = date_spec[pos:m.start()]
            regex_parts.append(re.escape(literal))
            strptime_parts.append(literal)
        regex_frag, strptime_frag = _DATE_TOKEN_MAP[m.group(0)]
        regex_parts.append(regex_frag)
        strptime_parts.append(strptime_frag)
        pos = m.end()
    if pos < len(date_spec):
        literal = date_spec[pos:]
        regex_parts.append(re.escape(literal))
        strptime_parts.append(literal)

    if not regex_parts:
        return r'\S+', None
    return ''.join(regex_parts), ''.join(strptime_parts)


@dataclass
class CompiledPattern:
    regex: re.Pattern
    strptime_format: str | None


_SPECIFIER_RE = re.compile(r'%(?:-?\d*(?:\.\d+)?)([a-zA-Z]+)(\{[^}]*\})?')

# Conversion specifiers we actually turn into a captured field. Anything not
# in this map (%C, %L, %F, %M, %X{...}, %ex/%throwable/%marker, ...) is
# tolerated as an inert, non-capturing filler -- see compile_pattern.
_FIELD_MAP = {
    'd': 'timestamp', 'date': 'timestamp',
    'p': 'level', 'level': 'level',
    't': 'thread', 'thread': 'thread',
    'c': 'logger', 'logger': 'logger',
    'm': 'message', 'msg': 'message', 'message': 'message',
    'n': 'newline',
}


def compile_pattern(conversion_pattern):
    """Compiles a log4j/log4j2 conversion pattern string into a regex with
    named groups (timestamp/level/thread/logger/message) plus, if a %d{...}
    was found, a matching strptime format for parsing it."""
    regex_parts = ['^']
    strptime_format = None
    used_fields = set()
    pos = 0

    for m in _SPECIFIER_RE.finditer(conversion_pattern):
        if m.start() > pos:
            regex_parts.append(re.escape(conversion_pattern[pos:m.start()]))

        specifier, braces = m.group(1), m.group(2)
        field = _FIELD_MAP.get(specifier)

        if field == 'newline':
            pass  # lines are already split -- nothing to match
        elif field == 'timestamp' and 'timestamp' not in used_fields:
            date_spec = braces[1:-1] if braces else 'yyyy-MM-dd HH:mm:ss,SSS'
            date_regex, strptime_format = _build_date_regex_and_format(date_spec)
            regex_parts.append(f'(?P<timestamp>{date_regex})')
            used_fields.add('timestamp')
        elif field == 'message':
            regex_parts.append('(?P<message>.*)')
            used_fields.add('message')
        elif field in ('level', 'thread', 'logger') and field not in used_fields:
            regex_parts.append(f'(?P<{field}>.*?)')
            used_fields.add(field)
        else:
            regex_parts.append('(?:.*?)')

        pos = m.end()

    if 'message' not in used_fields:
        regex_parts.append('(?P<message>.*)')

    if pos < len(conversion_pattern):
        regex_parts.append(re.escape(conversion_pattern[pos:]))

    return CompiledPattern(regex=re.compile(''.join(regex_parts)), strptime_format=strptime_format)


_DEFAULT_LINE_RE = re.compile(
    r'^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[.,]\d+(?:[+-]\d{2}:?\d{2}|Z)?)\s+'
    r'(?P<level>[A-Z]+)\s+\d*\s*---\s*\[(?P<thread>[^\]]*)\]\s+'
    r'(?P<logger>\S+)\s*:\s*(?P<message>.*)$'
)

# strptime_format sentinel meaning "parse with datetime.fromisoformat instead
# of a fixed strptime format" -- the default pattern's timestamp needs to
# tolerate both Spring Boot's classic 'yyyy-MM-dd HH:mm:ss.SSS' (space, no
# offset) and the increasingly common ISO-8601-with-offset style
# ('yyyy-MM-ddTHH:mm:ss.SSSXXX'), which a single fixed format can't parse.
ISO_TIMESTAMP_FORMAT = 'iso'


def default_compiled_pattern():
    """Spring Boot's actual default Logback console/file pattern -- used
    whenever no log4j XML is given, the XML has no usable pattern, or the
    extracted pattern turns out to be uncompilable."""
    return CompiledPattern(regex=_DEFAULT_LINE_RE, strptime_format=ISO_TIMESTAMP_FORMAT)


def _parse_timestamp(raw_timestamp, strptime_format):
    """Parses a captured timestamp string using either a fixed strptime
    format or (see ISO_TIMESTAMP_FORMAT) datetime.fromisoformat. Normalizes
    to UTC either way: an offset-bearing timestamp is converted, one with no
    offset/timezone info of its own is assumed to already be UTC rather than
    saved as a naive datetime (USE_TZ=True) or guessing the server's local
    zone. Returns None if parsing fails for any reason."""
    if not raw_timestamp or not strptime_format:
        return None
    try:
        if strptime_format == ISO_TIMESTAMP_FORMAT:
            parsed = datetime.fromisoformat(raw_timestamp.replace(',', '.'))
        else:
            parsed = datetime.strptime(raw_timestamp, strptime_format)
    except ValueError:
        return None
    return parsed.astimezone(dt_timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)


_REQUEST_METHOD_RE = re.compile(r'^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\S+', re.IGNORECASE)
_REQUEST_MARKER_RE = re.compile(r'-->|request\s*[:=]', re.IGNORECASE)
_RESPONSE_STATUS_RE = re.compile(r'\bstatus\s*[:=]?\s*\d{3}\b', re.IGNORECASE)
_RESPONSE_MARKER_RE = re.compile(r'<--|response\s*[:=]', re.IGNORECASE)


def _classify_request_response(message):
    """Heuristic quick-filter flags -- a debugging hint (matches this app's
    existing "hint, not verdict" outcome badges in apitester), not a real
    HTTP transaction parser."""
    head = message[:200]
    is_request = bool(_REQUEST_METHOD_RE.match(head) or _REQUEST_MARKER_RE.search(head))
    is_response = bool(_RESPONSE_STATUS_RE.search(head) or _RESPONSE_MARKER_RE.search(head))
    return is_request, is_response


def _finish_entry(pending):
    message = '\n'.join(pending.pop('message_lines'))
    pending['message'] = message
    pending['is_request_like'], pending['is_response_like'] = _classify_request_response(message)
    return pending


def parse_log_files(log_paths, compiled_pattern):
    """Returns (entries, warnings). `entries` is a list of plain dicts ready
    to become LogEntry kwargs."""
    entries = []
    warnings = []
    pending = None
    seq = 0
    truncated = False

    for path in log_paths:
        if truncated:
            break
        basename = os.path.basename(path)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for line_number, raw_line in enumerate(f, start=1):
                    if len(entries) >= MAX_LOG_ENTRIES:
                        truncated = True
                        break
                    seq += 1
                    line = raw_line.rstrip('\r\n')
                    match = compiled_pattern.regex.match(line)

                    if match:
                        if pending is not None:
                            entries.append(_finish_entry(pending))
                            pending = None
                        if len(entries) >= MAX_LOG_ENTRIES:
                            truncated = True
                            break
                        groups = match.groupdict()
                        parsed_timestamp = _parse_timestamp(
                            groups.get('timestamp'), compiled_pattern.strptime_format
                        )
                        pending = {
                            'seq': seq,
                            'source_file': basename,
                            'line_number': line_number,
                            'timestamp': parsed_timestamp,
                            'level': (groups.get('level') or '').strip().upper(),
                            'thread': (groups.get('thread') or '').strip(),
                            'logger': (groups.get('logger') or '').strip(),
                            'message_lines': [(groups.get('message') or '').strip()],
                        }
                    elif pending is not None:
                        pending['message_lines'].append(line)
                    else:
                        # Nothing has matched yet in this file (e.g. Spring
                        # Boot's startup banner) -- keep the line as a bare
                        # unparsed entry rather than silently dropping it.
                        pending = {
                            'seq': seq,
                            'source_file': basename,
                            'line_number': line_number,
                            'timestamp': None,
                            'level': '',
                            'thread': '',
                            'logger': '',
                            'message_lines': [line],
                        }
        except OSError as exc:
            warnings.append(f"Could not read '{basename}': {exc}")

    if pending is not None:
        entries.append(_finish_entry(pending))

    if truncated:
        warnings.append(
            f'Reached the {MAX_LOG_ENTRIES:,}-entry cap for a single import -- some log lines were not read. '
            'Narrow the folder down (fewer/smaller files) to see everything.'
        )

    return entries, warnings


def generate(job):
    """Runs the full pipeline for a LogViewJob, writing progress/results onto
    `job` and saving it. Safe to call from a background thread."""
    try:
        pattern_source = LogViewJob.PATTERN_SOURCE_DEFAULT
        conversion_pattern = DEFAULT_CONVERSION_PATTERN
        compiled = default_compiled_pattern()
        warnings = []

        if job.log4j_xml_path:
            extracted = None
            try:
                extracted = parse_log4j_conversion_pattern(job.log4j_xml_path)
            except PreflightError as exc:
                warnings.append(f'{exc} Falling back to the default Spring Boot log format.')

            if extracted:
                try:
                    compiled = compile_pattern(extracted)
                    pattern_source = LogViewJob.PATTERN_SOURCE_LOG4J_XML
                    conversion_pattern = extracted
                except re.error as exc:
                    warnings.append(
                        f"Could not use the pattern from '{job.log4j_xml_path}' ({exc}). "
                        'Falling back to the default Spring Boot log format.'
                    )
            elif not warnings:
                warnings.append(
                    f"No PatternLayout/ConversionPattern found in '{job.log4j_xml_path}'. "
                    'Falling back to the default Spring Boot log format.'
                )

        log_paths = find_log_files(job.logs_dir)
        if not log_paths:
            job.status = LogViewJob.STATUS_FAILED
            job.error = f"No .log files found under '{job.logs_dir}'."
            job.warnings = warnings
            job.completed_at = timezone.now()
            job.save()
            return

        entries, parse_warnings = parse_log_files(log_paths, compiled)
        warnings.extend(parse_warnings)

        LogEntry.objects.bulk_create([LogEntry(job=job, **entry) for entry in entries])

        job.pattern_source = pattern_source
        job.conversion_pattern = conversion_pattern
        job.file_count = len(log_paths)
        job.entry_count = len(entries)
        job.warnings = warnings
        job.status = LogViewJob.STATUS_COMPLETED
    except Exception as exc:  # noqa: BLE001 -- background thread, must not raise
        job.status = LogViewJob.STATUS_FAILED
        job.error = str(exc)

    job.completed_at = timezone.now()
    job.save()
