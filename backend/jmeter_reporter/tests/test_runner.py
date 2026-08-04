import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from jmeter_reporter import runner
from jmeter_reporter.models import JmeterReportJob


class ResolveJmeterBinTests(SimpleTestCase):
    def test_raises_when_not_found_on_path(self):
        with patch('jmeter_reporter.runner.shutil.which', return_value=None):
            with self.assertRaises(runner.PreflightError):
                runner.resolve_jmeter_bin('')

    def test_returns_default_name_when_found_on_path(self):
        with patch('jmeter_reporter.runner.shutil.which', return_value='/usr/local/bin/jmeter'):
            self.assertEqual(runner.resolve_jmeter_bin(''), 'jmeter')
            self.assertEqual(runner.resolve_jmeter_bin('   '), 'jmeter')

    def test_explicit_path_must_exist(self):
        with self.assertRaises(runner.PreflightError):
            runner.resolve_jmeter_bin('/nonexistent/path/to/jmeter')

    def test_explicit_path_must_be_executable(self):
        with tempfile.NamedTemporaryFile() as f:
            os.chmod(f.name, 0o644)
            with self.assertRaises(runner.PreflightError):
                runner.resolve_jmeter_bin(f.name)

    def test_explicit_executable_path_is_accepted(self):
        with tempfile.NamedTemporaryFile() as f:
            os.chmod(f.name, 0o755)
            self.assertEqual(runner.resolve_jmeter_bin(f.name), f.name)


class DefaultOutputDirTests(SimpleTestCase):
    def test_strips_extension_and_uses_csv_path_dir(self):
        self.assertEqual(
            runner.default_output_dir('/tmp/uploads/uuid_results.csv', 'results.csv'),
            '/tmp/uploads/results',
        )

    def test_uses_original_filename_not_saved_filename(self):
        # The saved CSV on disk has a uuid prefix (see _save_uploaded_csv) --
        # the default folder name should come from the original upload name.
        self.assertEqual(
            runner.default_output_dir('/tmp/uploads/ab12cd34_run-1.csv', 'run-1.csv'),
            '/tmp/uploads/run-1',
        )

    def test_handles_multi_dot_filenames(self):
        self.assertEqual(
            runner.default_output_dir('/tmp/uploads/uuid_results.v2.csv', 'results.v2.csv'),
            '/tmp/uploads/results.v2',
        )


class ValidateOutputDirTests(SimpleTestCase):
    def test_rejects_empty(self):
        with self.assertRaises(runner.PreflightError):
            runner.validate_output_dir('')
        with self.assertRaises(runner.PreflightError):
            runner.validate_output_dir('   ')

    def test_rejects_relative_path(self):
        with self.assertRaises(runner.PreflightError):
            runner.validate_output_dir('relative/path')

    def test_accepts_nonexistent_absolute_path(self):
        path = '/tmp/qa-helper-tool-does-not-exist-xyz-12345'
        self.assertEqual(runner.validate_output_dir(path), path)

    def test_accepts_existing_empty_directory(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(runner.validate_output_dir(d), d)

    def test_rejects_existing_non_empty_directory(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, 'file.txt'), 'w').close()
            with self.assertRaises(runner.PreflightError):
                runner.validate_output_dir(d)

    def test_rejects_path_that_is_a_file(self):
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises(runner.PreflightError):
                runner.validate_output_dir(f.name)


class BuildCommandTests(SimpleTestCase):
    def test_builds_expected_argument_list(self):
        cmd = runner.build_command('jmeter', '/tmp/results.csv', '/tmp/out')
        self.assertEqual(cmd, ['jmeter', '-g', '/tmp/results.csv', '-o', '/tmp/out'])


class RunReportTests(TestCase):
    def _make_job(self, **overrides):
        defaults = dict(
            csv_filename='results.csv',
            output_dir='/tmp/qa-helper-tool-out',
            jmeter_bin='jmeter',
            status=JmeterReportJob.STATUS_RUNNING,
        )
        defaults.update(overrides)
        return JmeterReportJob.objects.create(**defaults)

    @patch('jmeter_reporter.runner.os.path.isfile')
    @patch('jmeter_reporter.runner.subprocess.run')
    def test_success_marks_completed_and_sets_report_path(self, mock_run, mock_isfile):
        mock_run.return_value = MagicMock(returncode=0, stdout='ok', stderr='')
        mock_isfile.return_value = True
        job = self._make_job()
        runner.run_report(job, '/tmp/results.csv')
        job.refresh_from_db()
        self.assertEqual(job.status, JmeterReportJob.STATUS_COMPLETED)
        self.assertEqual(job.report_index_path, os.path.join(job.output_dir, 'index.html'))
        self.assertEqual(job.return_code, 0)
        self.assertIn('-g /tmp/results.csv', job.command)

    @patch('jmeter_reporter.runner.subprocess.run')
    def test_nonzero_exit_marks_failed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='boom')
        job = self._make_job()
        runner.run_report(job, '/tmp/results.csv')
        job.refresh_from_db()
        self.assertEqual(job.status, JmeterReportJob.STATUS_FAILED)
        self.assertIn('boom', job.stderr)
        self.assertEqual(job.report_index_path, '')

    @patch('jmeter_reporter.runner.subprocess.run')
    def test_timeout_marks_failed(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='jmeter', timeout=runner.REPORT_TIMEOUT_SECONDS)
        job = self._make_job()
        runner.run_report(job, '/tmp/results.csv')
        job.refresh_from_db()
        self.assertEqual(job.status, JmeterReportJob.STATUS_FAILED)
        self.assertIn('did not finish', job.error)

    @patch('jmeter_reporter.runner.os.path.isfile', return_value=False)
    @patch('jmeter_reporter.runner.subprocess.run')
    def test_success_exit_without_index_html_marks_failed(self, mock_run, mock_isfile):
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        job = self._make_job()
        runner.run_report(job, '/tmp/results.csv')
        job.refresh_from_db()
        self.assertEqual(job.status, JmeterReportJob.STATUS_FAILED)
        self.assertIn('no index.html', job.error)

    @patch('jmeter_reporter.runner.subprocess.run', side_effect=OSError('binary went missing'))
    def test_os_error_marks_failed(self, mock_run):
        job = self._make_job()
        runner.run_report(job, '/tmp/results.csv')
        job.refresh_from_db()
        self.assertEqual(job.status, JmeterReportJob.STATUS_FAILED)
        self.assertIn('binary went missing', job.error)
