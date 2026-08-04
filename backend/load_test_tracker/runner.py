"""Parses the two CSVs a user uploads for one already-executed load test
(JMeter's raw per-sample results CSV, and a server-metrics CSV of
Timestamp/CPU_Usage_Percent/RAM_USAGE_PERCENT) into aggregate stats and
chart-ready time-series data.

Unlike every other tool in this app, this is pure CSV parsing + arithmetic
-- no subprocess, no live HTTP calls -- so it all runs synchronously in the
request that uploads the files. No background thread, no polling.
"""
import csv
import io
import math
import re
from datetime import datetime

from .models import LoadTestResult, PlannedLoadTest

# Hard caps so a pathologically large file can't stall a request or blow up
# memory -- matches this codebase's existing pattern of bounding otherwise-
# unbounded input (e.g. apitester.test_generator.MAX_PATH_DEPTH).
MAX_CSV_ROWS = 300_000

# Target number of points per chart series, regardless of how many raw
# samples/how long the test ran -- keeps chart payloads small and fast to
# render for both a 2-minute smoke test and a 2-hour soak test.
BUCKET_COUNT_TARGET = 120


class PreflightError(ValueError):
    """Raised for validation problems caught before/while parsing, with a
    message meant to be shown directly to the user."""


def _decode(uploaded_file):
    raw = uploaded_file.read()
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise PreflightError(f"'{uploaded_file.name}' is not a valid UTF-8 text/CSV file.") from exc


def _find_column(fieldnames, *needles):
    """Returns the first fieldname whose normalized form (lowercased,
    non-alphanumerics stripped) contains every needle -- tolerant of header
    variants like 'CPU_Usage_Percent', 'CPU Usage %', 'cpu_usage_pct'."""
    for name in fieldnames or []:
        normalized = re.sub(r'[^a-z0-9]', '', name.lower())
        if all(needle in normalized for needle in needles):
            return name
    return None


def parse_jmeter_csv(uploaded_file):
    """Returns a list of {timestamp_ms, elapsed_ms, success, label,
    response_code} dicts, one per HTTP sample, in whatever order the file
    had them (bucket_series sorts by time itself)."""
    reader = csv.DictReader(io.StringIO(_decode(uploaded_file)))
    fieldnames = reader.fieldnames or []

    timestamp_col = _find_column(fieldnames, 'timestamp') or _find_column(fieldnames, 'time')
    elapsed_col = _find_column(fieldnames, 'elapsed')
    success_col = _find_column(fieldnames, 'success')
    missing = [
        label for label, col in
        (('timeStamp', timestamp_col), ('elapsed', elapsed_col), ('success', success_col))
        if col is None
    ]
    if missing:
        raise PreflightError(
            f"JMeter CSV is missing required column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(fieldnames) or '(none -- file may be empty)'}."
        )
    label_col = _find_column(fieldnames, 'label')
    response_code_col = _find_column(fieldnames, 'responsecode')

    samples = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        if len(samples) > MAX_CSV_ROWS:
            raise PreflightError(f"JMeter CSV has more than {MAX_CSV_ROWS} rows -- too large to process.")
        try:
            timestamp_ms = float(row[timestamp_col])
            elapsed_ms = float(row[elapsed_col])
        except (TypeError, ValueError):
            raise PreflightError(f"Row {i}: could not parse '{timestamp_col}'/'{elapsed_col}' as numbers.")
        samples.append({
            'timestamp_ms': timestamp_ms,
            'elapsed_ms': elapsed_ms,
            'success': (row.get(success_col) or '').strip().lower() == 'true',
            'label': (row.get(label_col) or '') if label_col else '',
            'response_code': (row.get(response_code_col) or '') if response_code_col else '',
        })

    if not samples:
        raise PreflightError('JMeter CSV has no data rows.')
    return samples


def _parse_timestamp_seconds(value):
    value = (value or '').strip()
    try:
        num = float(value)
        # Epoch milliseconds are ~13 digits (>1e12); epoch seconds ~10 (<1e12).
        return num / 1000.0 if num > 1e12 else num
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        raise PreflightError(f"Could not parse timestamp '{value}' in the server metrics CSV.")


def parse_server_metrics_csv(uploaded_file):
    """Returns a list of {timestamp_s, cpu_percent, ram_percent} dicts."""
    reader = csv.DictReader(io.StringIO(_decode(uploaded_file)))
    fieldnames = reader.fieldnames or []

    timestamp_col = _find_column(fieldnames, 'timestamp') or _find_column(fieldnames, 'time')
    cpu_col = _find_column(fieldnames, 'cpu')
    ram_col = _find_column(fieldnames, 'ram') or _find_column(fieldnames, 'memory')
    missing = [
        label for label, col in
        (('Timestamp', timestamp_col), ('CPU_Usage_Percent', cpu_col), ('RAM_USAGE_PERCENT', ram_col))
        if col is None
    ]
    if missing:
        raise PreflightError(
            f"Server metrics CSV is missing required column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(fieldnames) or '(none -- file may be empty)'}."
        )

    rows = []
    for i, row in enumerate(reader, start=2):
        if len(rows) > MAX_CSV_ROWS:
            raise PreflightError(f"Server metrics CSV has more than {MAX_CSV_ROWS} rows -- too large to process.")
        timestamp_s = _parse_timestamp_seconds(row[timestamp_col])
        try:
            cpu_percent = float(row[cpu_col])
            ram_percent = float(row[ram_col])
        except (TypeError, ValueError):
            raise PreflightError(f"Row {i}: could not parse '{cpu_col}'/'{ram_col}' as numbers.")
        rows.append({'timestamp_s': timestamp_s, 'cpu_percent': cpu_percent, 'ram_percent': ram_percent})

    if not rows:
        raise PreflightError('Server metrics CSV has no data rows.')
    return rows


def _percentile(sorted_values, pct):
    """Linear-interpolation percentile (same convention as numpy's default),
    on an already-sorted list."""
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * (pct / 100)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def compute_aggregates(samples):
    sample_count = len(samples)
    error_count = sum(1 for s in samples if not s['success'])
    timestamps = [s['timestamp_ms'] for s in samples]
    start_ms, end_ms = min(timestamps), max(timestamps)
    duration_seconds = (end_ms - start_ms) / 1000.0

    elapsed_sorted = sorted(s['elapsed_ms'] for s in samples)

    return {
        'sample_count': sample_count,
        'error_count': error_count,
        'error_rate_percent': round(100 * error_count / sample_count, 2) if sample_count else None,
        'actual_duration_seconds': round(duration_seconds, 2),
        'actual_tps': round(sample_count / duration_seconds, 2) if duration_seconds > 0 else None,
        'avg_response_time_ms': round(sum(elapsed_sorted) / sample_count, 2) if sample_count else None,
        'min_response_time_ms': elapsed_sorted[0] if elapsed_sorted else None,
        'max_response_time_ms': elapsed_sorted[-1] if elapsed_sorted else None,
        'p50_response_time_ms': _percentile(elapsed_sorted, 50),
        'p90_response_time_ms': _percentile(elapsed_sorted, 90),
        'p95_response_time_ms': _percentile(elapsed_sorted, 95),
        'p99_response_time_ms': _percentile(elapsed_sorted, 99),
    }


def _bucket_width_for(duration_seconds, bucket_count_target):
    return max(1, math.ceil(duration_seconds / bucket_count_target)) if duration_seconds > 0 else 1


def bucket_series(samples, metrics, bucket_count_target=BUCKET_COUNT_TARGET):
    """Buckets JMeter samples onto a "minutes since the JMeter test started"
    axis, and server metrics onto their own separate "minutes since the
    metrics capture started" axis -- capping the number of points per
    series to roughly `bucket_count_target` regardless of the raw row count
    or duration of either file.

    The two axes are deliberately *not* aligned to each other. Server
    metrics are often captured on a different machine than the one running
    JMeter (the server under test, a monitoring host, ...), and clocks
    between machines routinely disagree or run in different timezones --
    trying to line them up on one shared axis meant real CPU/RAM data could
    get silently excluded as "outside the test's time range" whenever the
    two clocks didn't closely agree, even though the data was perfectly
    valid on its own terms. Showing the full CPU/RAM capture on its own
    timeline is more useful than a chart that might come up empty.
    """
    start_ms = min(s['timestamp_ms'] for s in samples)
    end_ms = max(s['timestamp_ms'] for s in samples)
    duration_seconds = (end_ms - start_ms) / 1000.0
    bucket_width_seconds = _bucket_width_for(duration_seconds, bucket_count_target)

    request_buckets = {}
    for s in samples:
        idx = int(((s['timestamp_ms'] - start_ms) / 1000.0) // bucket_width_seconds)
        request_buckets.setdefault(idx, []).append(s['elapsed_ms'])

    response_time_series = []
    throughput_series = []
    for idx in sorted(request_buckets):
        elapsed_values = sorted(request_buckets[idx])
        t_minutes = round(idx * bucket_width_seconds / 60.0, 3)
        response_time_series.append({
            't': t_minutes,
            'avg': round(sum(elapsed_values) / len(elapsed_values), 2),
            'p95': round(_percentile(elapsed_values, 95), 2),
        })
        throughput_series.append({
            't': t_minutes,
            'tps': round(len(elapsed_values) / bucket_width_seconds, 2),
        })

    cpu_ram_series = []
    if metrics:
        metrics_start_s = min(m['timestamp_s'] for m in metrics)
        metrics_end_s = max(m['timestamp_s'] for m in metrics)
        metrics_bucket_width = _bucket_width_for(metrics_end_s - metrics_start_s, bucket_count_target)

        metric_buckets = {}
        for m in metrics:
            idx = int((m['timestamp_s'] - metrics_start_s) // metrics_bucket_width)
            metric_buckets.setdefault(idx, []).append(m)

        for idx in sorted(metric_buckets):
            rows = metric_buckets[idx]
            t_minutes = round(idx * metrics_bucket_width / 60.0, 3)
            cpu_ram_series.append({
                't': t_minutes,
                'cpu_percent': round(sum(r['cpu_percent'] for r in rows) / len(rows), 2),
                'ram_percent': round(sum(r['ram_percent'] for r in rows) / len(rows), 2),
            })

    # Reserved for future validation warnings (e.g. sparse coverage) --
    # nothing gets excluded from either series anymore, so always empty.
    warnings = []

    return response_time_series, throughput_series, cpu_ram_series, warnings


def record_result(planned_test, jmeter_file, server_metrics_file):
    """Parses both uploaded files and creates the (one-time) LoadTestResult
    for `planned_test`. Caller is responsible for checking a result doesn't
    already exist -- this always creates a new row."""
    samples = parse_jmeter_csv(jmeter_file)
    metrics = parse_server_metrics_csv(server_metrics_file)
    aggregates = compute_aggregates(samples)
    response_time_series, throughput_series, cpu_ram_series, warnings = bucket_series(samples, metrics)

    result = LoadTestResult.objects.create(
        planned_test=planned_test,
        jmeter_csv_filename=jmeter_file.name,
        server_metrics_csv_filename=server_metrics_file.name,
        response_time_series=response_time_series,
        throughput_series=throughput_series,
        cpu_ram_series=cpu_ram_series,
        warnings=warnings,
        **aggregates,
    )
    planned_test.status = PlannedLoadTest.STATUS_RECORDED
    planned_test.save(update_fields=['status'])
    return result
