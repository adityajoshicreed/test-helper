from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from load_test_tracker import runner
from load_test_tracker.models import LoadTestPlan, LoadTestResult, PlannedLoadTest


def csv_file(name, text):
    return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/csv')


JMETER_HEADER = 'timeStamp,elapsed,label,responseCode,success\n'


def jmeter_row(timestamp_ms, elapsed_ms, success='true', label='GET /x', code='200'):
    return f'{timestamp_ms},{elapsed_ms},{label},{code},{success}\n'


class ParseJmeterCsvTests(SimpleTestCase):
    def test_parses_happy_path(self):
        text = JMETER_HEADER + jmeter_row(1000, 100) + jmeter_row(2000, 200, success='false')
        samples = runner.parse_jmeter_csv(csv_file('r.csv', text))
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0], {
            'timestamp_ms': 1000.0, 'elapsed_ms': 100.0, 'success': True,
            'label': 'GET /x', 'response_code': '200',
        })
        self.assertFalse(samples[1]['success'])

    def test_missing_required_column_raises(self):
        text = 'timeStamp,elapsed,label\n1000,100,x\n'  # no 'success'
        with self.assertRaises(runner.PreflightError) as ctx:
            runner.parse_jmeter_csv(csv_file('r.csv', text))
        self.assertIn('success', str(ctx.exception))

    def test_malformed_numeric_value_raises_with_row_number(self):
        text = JMETER_HEADER + 'not-a-number,100,GET /x,200,true\n'
        with self.assertRaises(runner.PreflightError) as ctx:
            runner.parse_jmeter_csv(csv_file('r.csv', text))
        self.assertIn('Row 2', str(ctx.exception))

    def test_no_data_rows_raises(self):
        with self.assertRaises(runner.PreflightError):
            runner.parse_jmeter_csv(csv_file('r.csv', JMETER_HEADER))

    @patch('load_test_tracker.runner.MAX_CSV_ROWS', 5)
    def test_row_count_cap_raises(self):
        text = JMETER_HEADER + ''.join(jmeter_row(i * 1000, 100) for i in range(7))
        with self.assertRaises(runner.PreflightError) as ctx:
            runner.parse_jmeter_csv(csv_file('r.csv', text))
        self.assertIn('more than 5 rows', str(ctx.exception))


class ParseServerMetricsCsvTests(SimpleTestCase):
    def test_parses_happy_path_with_epoch_seconds(self):
        text = 'Timestamp,CPU_Usage_Percent,RAM_USAGE_PERCENT\n1000,45.5,60.1\n1005,50.0,61.0\n'
        rows = runner.parse_server_metrics_csv(csv_file('m.csv', text))
        self.assertEqual(rows, [
            {'timestamp_s': 1000.0, 'cpu_percent': 45.5, 'ram_percent': 60.1},
            {'timestamp_s': 1005.0, 'cpu_percent': 50.0, 'ram_percent': 61.0},
        ])

    def test_tolerates_header_variants(self):
        text = 'time,CPU Usage %,RAM Usage %\n1000,10,20\n'
        rows = runner.parse_server_metrics_csv(csv_file('m.csv', text))
        self.assertEqual(rows[0]['cpu_percent'], 10.0)
        self.assertEqual(rows[0]['ram_percent'], 20.0)

    def test_epoch_milliseconds_are_converted_to_seconds(self):
        text = 'Timestamp,CPU_Usage_Percent,RAM_USAGE_PERCENT\n1700000000000,10,20\n'
        rows = runner.parse_server_metrics_csv(csv_file('m.csv', text))
        self.assertAlmostEqual(rows[0]['timestamp_s'], 1700000000.0)

    def test_iso_timestamp_is_parsed(self):
        text = 'Timestamp,CPU_Usage_Percent,RAM_USAGE_PERCENT\n2026-01-01T00:00:00+00:00,10,20\n'
        rows = runner.parse_server_metrics_csv(csv_file('m.csv', text))
        self.assertGreater(rows[0]['timestamp_s'], 0)

    def test_missing_column_raises(self):
        text = 'Timestamp,CPU_Usage_Percent\n1000,10\n'  # no RAM column
        with self.assertRaises(runner.PreflightError) as ctx:
            runner.parse_server_metrics_csv(csv_file('m.csv', text))
        self.assertIn('RAM_USAGE_PERCENT', str(ctx.exception))

    def test_bad_timestamp_raises(self):
        text = 'Timestamp,CPU_Usage_Percent,RAM_USAGE_PERCENT\nnot-a-timestamp,10,20\n'
        with self.assertRaises(runner.PreflightError):
            runner.parse_server_metrics_csv(csv_file('m.csv', text))


class ComputeAggregatesTests(SimpleTestCase):
    def _samples(self):
        # 5 samples, 1 second apart, elapsed 100..500ms, one failure.
        return [
            {'timestamp_ms': 0, 'elapsed_ms': 100, 'success': True, 'label': '', 'response_code': ''},
            {'timestamp_ms': 1000, 'elapsed_ms': 200, 'success': True, 'label': '', 'response_code': ''},
            {'timestamp_ms': 2000, 'elapsed_ms': 300, 'success': False, 'label': '', 'response_code': ''},
            {'timestamp_ms': 3000, 'elapsed_ms': 400, 'success': True, 'label': '', 'response_code': ''},
            {'timestamp_ms': 4000, 'elapsed_ms': 500, 'success': True, 'label': '', 'response_code': ''},
        ]

    def test_known_sample_set_matches_hand_checked_values(self):
        agg = runner.compute_aggregates(self._samples())
        self.assertEqual(agg['sample_count'], 5)
        self.assertEqual(agg['error_count'], 1)
        self.assertEqual(agg['error_rate_percent'], 20.0)
        self.assertEqual(agg['actual_duration_seconds'], 4.0)
        self.assertEqual(agg['actual_tps'], 1.25)
        self.assertEqual(agg['avg_response_time_ms'], 300.0)
        self.assertEqual(agg['min_response_time_ms'], 100)
        self.assertEqual(agg['max_response_time_ms'], 500)
        self.assertEqual(agg['p50_response_time_ms'], 300)
        self.assertAlmostEqual(agg['p90_response_time_ms'], 460.0)
        self.assertAlmostEqual(agg['p95_response_time_ms'], 480.0)
        self.assertAlmostEqual(agg['p99_response_time_ms'], 496.0)

    def test_single_sample_has_no_tps_but_no_crash(self):
        agg = runner.compute_aggregates([
            {'timestamp_ms': 0, 'elapsed_ms': 100, 'success': True, 'label': '', 'response_code': ''},
        ])
        self.assertEqual(agg['sample_count'], 1)
        self.assertIsNone(agg['actual_tps'])
        self.assertEqual(agg['avg_response_time_ms'], 100)


class BucketSeriesTests(SimpleTestCase):
    def test_buckets_by_target_width_deterministically(self):
        # 10 one-second samples (elapsed=100 each); target 5 buckets over a
        # 10s span -> bucket width = ceil(10/5) = 2s -> 5 populated buckets.
        samples = [
            {'timestamp_ms': i * 1000, 'elapsed_ms': 100, 'success': True, 'label': '', 'response_code': ''}
            for i in range(10)
        ]
        response_time_series, throughput_series, cpu_ram_series, warnings = runner.bucket_series(
            samples, [], bucket_count_target=5
        )
        self.assertEqual(len(response_time_series), 5)
        self.assertEqual([p['t'] for p in response_time_series], [0.0, round(2 / 60, 3), round(4 / 60, 3), round(6 / 60, 3), round(8 / 60, 3)])
        for p in response_time_series:
            self.assertEqual(p['avg'], 100)
            self.assertEqual(p['p95'], 100)
        for p in throughput_series:
            self.assertEqual(p['tps'], 1.0)  # 2 samples / 2s bucket width
        self.assertEqual(cpu_ram_series, [])
        self.assertEqual(warnings, [])

    def test_metrics_outside_jmeter_time_range_are_excluded_with_warning(self):
        samples = [
            {'timestamp_ms': 0, 'elapsed_ms': 100, 'success': True, 'label': '', 'response_code': ''},
            {'timestamp_ms': 9000, 'elapsed_ms': 100, 'success': True, 'label': '', 'response_code': ''},
        ]
        metrics = [
            {'timestamp_s': -100, 'cpu_percent': 1, 'ram_percent': 1},  # before start
            {'timestamp_s': 5, 'cpu_percent': 50, 'ram_percent': 60},  # within range
            {'timestamp_s': 9999, 'cpu_percent': 99, 'ram_percent': 99},  # after end
        ]
        _, _, cpu_ram_series, warnings = runner.bucket_series(samples, metrics, bucket_count_target=5)
        self.assertEqual(len(cpu_ram_series), 1)
        self.assertEqual(cpu_ram_series[0]['cpu_percent'], 50)
        self.assertEqual(len(warnings), 1)
        self.assertIn('2 server-metrics row(s)', warnings[0])

    def test_cpu_ram_bucket_present_even_without_a_matching_jmeter_sample(self):
        # Only one jmeter sample (bucket 0), but a metrics row lands in a
        # later bucket that has no jmeter sample at all -- must still show up.
        samples = [
            {'timestamp_ms': 0, 'elapsed_ms': 100, 'success': True, 'label': '', 'response_code': ''},
            {'timestamp_ms': 9000, 'elapsed_ms': 100, 'success': True, 'label': '', 'response_code': ''},
        ]
        metrics = [{'timestamp_s': 5, 'cpu_percent': 33, 'ram_percent': 44}]
        response_time_series, _, cpu_ram_series, _ = runner.bucket_series(samples, metrics, bucket_count_target=5)
        # bucket width = 2s -> metrics at t=5s falls in bucket index 2 (t=4min... actually 4/60 min)
        self.assertEqual(len(cpu_ram_series), 1)
        self.assertEqual(cpu_ram_series[0]['cpu_percent'], 33)


class RecordResultTests(TestCase):
    def _make_planned_test(self):
        plan = LoadTestPlan.objects.create(name='p', api_name='checkout')
        return PlannedLoadTest.objects.create(
            plan=plan, order=1, name='baseline', planned_duration_minutes=1, planned_tps=10,
        )

    def test_creates_result_and_marks_test_recorded(self):
        planned_test = self._make_planned_test()
        jmeter_csv = csv_file('jmeter.csv', JMETER_HEADER + jmeter_row(0, 100) + jmeter_row(1000, 200))
        metrics_csv = csv_file('metrics.csv', 'Timestamp,CPU_Usage_Percent,RAM_USAGE_PERCENT\n0,10,20\n')

        result = runner.record_result(planned_test, jmeter_csv, metrics_csv)

        self.assertEqual(LoadTestResult.objects.filter(planned_test=planned_test).count(), 1)
        self.assertEqual(result.sample_count, 2)
        planned_test.refresh_from_db()
        self.assertEqual(planned_test.status, PlannedLoadTest.STATUS_RECORDED)
