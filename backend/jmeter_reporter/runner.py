"""Runs `jmeter -g <results-file> -o <output-dir>` to build an HTML
dashboard report from an existing JMeter results file (JMeter's built-in
non-GUI report generator), in a background thread so the API can return
immediately and the frontend can poll for completion -- report generation
on a large results file can take a while.
"""
import os
import shutil
import subprocess

from django.utils import timezone

DEFAULT_JMETER_BIN = 'jmeter'
REPORT_TIMEOUT_SECONDS = 600


class PreflightError(ValueError):
    """Raised for validation problems caught before we spawn the subprocess."""


def resolve_jmeter_bin(jmeter_bin):
    """Validates the user-supplied JMeter binary path (or falls back to
    'jmeter' on PATH). Raises PreflightError with a message the UI can show
    directly if it can't be found/isn't executable."""
    jmeter_bin = (jmeter_bin or '').strip() or DEFAULT_JMETER_BIN
    looks_like_a_path = os.sep in jmeter_bin or (os.altsep and os.altsep in jmeter_bin)
    if looks_like_a_path:
        if not os.path.isfile(jmeter_bin):
            raise PreflightError(f"JMeter binary not found at '{jmeter_bin}'.")
        if not os.access(jmeter_bin, os.X_OK):
            raise PreflightError(f"JMeter binary at '{jmeter_bin}' is not executable.")
    elif shutil.which(jmeter_bin) is None:
        raise PreflightError(
            f"Could not find '{jmeter_bin}' on PATH. Provide the full path to the JMeter binary."
        )
    return jmeter_bin


def default_output_dir(csv_path, original_filename):
    """When the user leaves the output directory blank, defaults to a new
    folder named after the CSV file (extension stripped), next to wherever
    the uploaded CSV itself was saved -- browsers don't expose the client's
    original filesystem path, so the server-side upload location is the
    closest available notion of "the same location as the CSV file"."""
    base_name = os.path.splitext(os.path.basename(original_filename))[0]
    return os.path.join(os.path.dirname(csv_path), base_name)


def validate_output_dir(output_dir):
    """JMeter creates the output directory if it doesn't exist, but refuses
    to write into one that already exists and isn't empty (to avoid
    silently clobbering a previous report)."""
    output_dir = (output_dir or '').strip()
    if not output_dir:
        raise PreflightError('Provide an output directory for the report.')
    if not os.path.isabs(output_dir):
        raise PreflightError('Output directory must be an absolute path.')
    if os.path.exists(output_dir):
        if not os.path.isdir(output_dir):
            raise PreflightError(f"'{output_dir}' exists and is not a directory.")
        if os.listdir(output_dir):
            raise PreflightError(
                f"'{output_dir}' already exists and is not empty. JMeter refuses to write a "
                'report into a non-empty directory -- choose a new or empty directory.'
            )
    return output_dir


def build_command(jmeter_bin, csv_path, output_dir):
    return [jmeter_bin, '-g', csv_path, '-o', output_dir]


def run_report(job, csv_path):
    """Runs the report-generation subprocess and writes the outcome onto
    `job` (a JmeterReportJob), saving it. Safe to call from a background
    thread -- the caller is responsible for closing the DB connection
    afterwards."""
    command = build_command(job.jmeter_bin, csv_path, job.output_dir)
    job.command = ' '.join(command)
    job.save(update_fields=['command'])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=REPORT_TIMEOUT_SECONDS,
        )
        job.return_code = result.returncode
        job.stdout = (result.stdout or '')[-20000:]
        job.stderr = (result.stderr or '')[-20000:]
        if result.returncode == 0:
            index_path = os.path.join(job.output_dir, 'index.html')
            if os.path.isfile(index_path):
                job.report_index_path = index_path
                job.status = job.STATUS_COMPLETED
            else:
                job.status = job.STATUS_FAILED
                job.error = 'JMeter exited successfully but no index.html was found in the output directory.'
        else:
            job.status = job.STATUS_FAILED
    except subprocess.TimeoutExpired:
        job.status = job.STATUS_FAILED
        job.error = f'JMeter did not finish within {REPORT_TIMEOUT_SECONDS}s.'
    except OSError as exc:
        job.status = job.STATUS_FAILED
        job.error = str(exc)

    job.completed_at = timezone.now()
    job.save()
