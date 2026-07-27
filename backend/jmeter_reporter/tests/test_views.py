import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from jmeter_reporter.models import JmeterReportJob


def make_csv():
    return SimpleUploadedFile('results.csv', b'timeStamp,elapsed,label\n1,100,test\n', content_type='text/csv')


class CreateJmeterReportJobViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_missing_csv_file_returns_400(self):
        response = self.client.post('/api/jmeter/jobs/', {'output_dir': '/tmp/whatever'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('csv_file', response.json()['error'])

    def test_missing_output_dir_returns_400(self):
        response = self.client.post('/api/jmeter/jobs/', {'csv_file': make_csv()})
        self.assertEqual(response.status_code, 400)

    def test_relative_output_dir_returns_400(self):
        response = self.client.post(
            '/api/jmeter/jobs/', {'csv_file': make_csv(), 'output_dir': 'relative/path'}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(JmeterReportJob.objects.count(), 0)

    def test_nonexistent_jmeter_bin_path_returns_400_and_creates_no_job(self):
        with tempfile.TemporaryDirectory() as out_dir:
            # TemporaryDirectory creates the dir itself, but validate_output_dir
            # only rejects it if non-empty, so pass a not-yet-existing subdir.
            output_dir = out_dir + '/report'
            response = self.client.post('/api/jmeter/jobs/', {
                'csv_file': make_csv(),
                'output_dir': output_dir,
                'jmeter_bin': '/no/such/jmeter/binary',
            })
            self.assertEqual(response.status_code, 400)
            self.assertEqual(JmeterReportJob.objects.count(), 0)

    def test_non_empty_output_dir_returns_400(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with open(f'{out_dir}/existing.txt', 'w') as f:
                f.write('x')
            response = self.client.post('/api/jmeter/jobs/', {
                'csv_file': make_csv(),
                'output_dir': out_dir,
                'jmeter_bin': '/no/such/jmeter/binary',
            })
            self.assertEqual(response.status_code, 400)
            self.assertIn('not empty', response.json()['error'])


class JmeterReportJobDetailViewTests(TestCase):
    def test_detail_returns_job_fields(self):
        job = JmeterReportJob.objects.create(
            csv_filename='results.csv',
            output_dir='/tmp/out',
            jmeter_bin='jmeter',
            status=JmeterReportJob.STATUS_RUNNING,
        )
        response = APIClient().get(f'/api/jmeter/jobs/{job.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'running')


class JmeterReportFileViewTests(TestCase):
    def test_report_not_available_for_running_job_returns_404(self):
        job = JmeterReportJob.objects.create(
            csv_filename='results.csv',
            output_dir='/tmp/out',
            jmeter_bin='jmeter',
            status=JmeterReportJob.STATUS_RUNNING,
        )
        response = APIClient().get(f'/api/jmeter/jobs/{job.id}/report/')
        self.assertEqual(response.status_code, 404)

    def test_report_serves_index_html_for_completed_job(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with open(f'{out_dir}/index.html', 'w') as f:
                f.write('<html>report</html>')
            job = JmeterReportJob.objects.create(
                csv_filename='results.csv',
                output_dir=out_dir,
                jmeter_bin='jmeter',
                status=JmeterReportJob.STATUS_COMPLETED,
                report_index_path=f'{out_dir}/index.html',
            )
            response = APIClient().get(f'/api/jmeter/jobs/{job.id}/report/')
            self.assertEqual(response.status_code, 200)
            content = b''.join(response.streaming_content) if response.streaming else response.content
            self.assertIn(b'report', content)
