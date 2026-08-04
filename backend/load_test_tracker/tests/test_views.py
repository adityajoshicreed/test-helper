from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from load_test_tracker.models import LoadTestPlan, LoadTestResult, PlannedLoadTest

JMETER_CSV = (
    'timeStamp,elapsed,label,responseCode,success\n'
    '0,100,GET /x,200,true\n'
    '1000,200,GET /x,200,true\n'
)
METRICS_CSV = 'Timestamp,CPU_Usage_Percent,RAM_USAGE_PERCENT\n0,10,20\n1,15,25\n'


def csv_file(name, text):
    return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/csv')


class LoadTestPlanViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_plan(self):
        response = self.client.post(
            '/api/load-tests/plans/', {'name': 'Checkout load plan', 'api_name': 'checkout'}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['name'], 'Checkout load plan')
        self.assertEqual(body['api_name'], 'checkout')
        self.assertEqual(body['tests'], [])

    def test_missing_name_returns_400(self):
        response = self.client.post('/api/load-tests/plans/', {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(LoadTestPlan.objects.count(), 0)

    def test_list_returns_test_and_recorded_counts(self):
        plan = LoadTestPlan.objects.create(name='p')
        PlannedLoadTest.objects.create(plan=plan, order=1, name='t1', planned_duration_minutes=1, planned_tps=10)
        recorded = PlannedLoadTest.objects.create(
            plan=plan, order=2, name='t2', planned_duration_minutes=1, planned_tps=10,
            status=PlannedLoadTest.STATUS_RECORDED,
        )
        LoadTestResult.objects.create(
            planned_test=recorded, jmeter_csv_filename='a.csv', server_metrics_csv_filename='b.csv',
        )
        response = self.client.get('/api/load-tests/plans/')
        self.assertEqual(response.status_code, 200)
        body = response.json()[0]
        self.assertEqual(body['test_count'], 2)
        self.assertEqual(body['recorded_count'], 1)

    def test_detail_nests_tests_with_result(self):
        plan = LoadTestPlan.objects.create(name='p')
        test = PlannedLoadTest.objects.create(
            plan=plan, order=1, name='t1', planned_duration_minutes=1, planned_tps=10,
            status=PlannedLoadTest.STATUS_RECORDED,
        )
        LoadTestResult.objects.create(
            planned_test=test, jmeter_csv_filename='a.csv', server_metrics_csv_filename='b.csv',
            sample_count=2,
        )
        response = self.client.get(f'/api/load-tests/plans/{plan.id}/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['tests']), 1)
        self.assertEqual(body['tests'][0]['result']['sample_count'], 2)


class PlannedLoadTestCreateViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.plan = LoadTestPlan.objects.create(name='p')

    def test_creates_test_with_incrementing_order(self):
        first = self.client.post(
            f'/api/load-tests/plans/{self.plan.id}/tests/',
            {'name': 't1', 'planned_duration_minutes': 5, 'planned_tps': 20},
            format='json',
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()['order'], 1)
        self.assertEqual(first.json()['status'], 'planned')

        second = self.client.post(
            f'/api/load-tests/plans/{self.plan.id}/tests/',
            {'name': 't2', 'planned_duration_minutes': 10, 'planned_tps': 30},
            format='json',
        )
        self.assertEqual(second.json()['order'], 2)

    def test_non_numeric_duration_returns_400(self):
        response = self.client.post(
            f'/api/load-tests/plans/{self.plan.id}/tests/',
            {'name': 't1', 'planned_duration_minutes': 'soon', 'planned_tps': 20},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_zero_tps_returns_400(self):
        response = self.client.post(
            f'/api/load-tests/plans/{self.plan.id}/tests/',
            {'name': 't1', 'planned_duration_minutes': 5, 'planned_tps': 0},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_name_returns_400(self):
        response = self.client.post(
            f'/api/load-tests/plans/{self.plan.id}/tests/',
            {'planned_duration_minutes': 5, 'planned_tps': 20},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class RecordLoadTestResultViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        plan = LoadTestPlan.objects.create(name='p')
        self.planned_test = PlannedLoadTest.objects.create(
            plan=plan, order=1, name='t1', planned_duration_minutes=1, planned_tps=10,
        )

    def test_record_happy_path(self):
        response = self.client.post(
            f'/api/load-tests/tests/{self.planned_test.id}/record/',
            {
                'jmeter_csv': csv_file('jmeter.csv', JMETER_CSV),
                'server_metrics_csv': csv_file('metrics.csv', METRICS_CSV),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['status'], 'recorded')
        self.assertEqual(body['result']['sample_count'], 2)
        self.assertEqual(body['result']['jmeter_csv_filename'], 'jmeter.csv')

        self.planned_test.refresh_from_db()
        self.assertEqual(self.planned_test.status, PlannedLoadTest.STATUS_RECORDED)

    def test_missing_files_returns_400(self):
        response = self.client.post(
            f'/api/load-tests/tests/{self.planned_test.id}/record/', {}, format='multipart'
        )
        self.assertEqual(response.status_code, 400)

    def test_malformed_csv_returns_400_and_does_not_record(self):
        response = self.client.post(
            f'/api/load-tests/tests/{self.planned_test.id}/record/',
            {
                'jmeter_csv': csv_file('jmeter.csv', 'not,the,right,columns\n1,2,3,4\n'),
                'server_metrics_csv': csv_file('metrics.csv', METRICS_CSV),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 400)
        self.planned_test.refresh_from_db()
        self.assertEqual(self.planned_test.status, PlannedLoadTest.STATUS_PLANNED)
        self.assertEqual(LoadTestResult.objects.count(), 0)

    def test_recording_twice_is_rejected(self):
        self.client.post(
            f'/api/load-tests/tests/{self.planned_test.id}/record/',
            {'jmeter_csv': csv_file('a.csv', JMETER_CSV), 'server_metrics_csv': csv_file('b.csv', METRICS_CSV)},
            format='multipart',
        )
        second = self.client.post(
            f'/api/load-tests/tests/{self.planned_test.id}/record/',
            {'jmeter_csv': csv_file('a.csv', JMETER_CSV), 'server_metrics_csv': csv_file('b.csv', METRICS_CSV)},
            format='multipart',
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(LoadTestResult.objects.filter(planned_test=self.planned_test).count(), 1)
