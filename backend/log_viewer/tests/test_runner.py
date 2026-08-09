import os
import tempfile
from datetime import datetime
from unittest.mock import patch

from django.test import SimpleTestCase

from log_viewer import runner

LOG4J2_XML = """<?xml version="1.0"?>
<Configuration>
  <Appenders>
    <Console name="Console">
      <PatternLayout pattern="%d{yyyy-MM-dd HH:mm:ss.SSS} %-5level [%t] %c{1.} - %msg%n"/>
    </Console>
  </Appenders>
</Configuration>"""

LOG4J1_XML = """<?xml version="1.0"?>
<log4j:configuration xmlns:log4j="http://jakarta.apache.org/log4j/">
  <appender name="console" class="org.apache.log4j.ConsoleAppender">
    <layout class="org.apache.log4j.PatternLayout">
      <param name="ConversionPattern" value="%d{ISO8601} %-5p [%t] %c{1}:%L - %m%n"/>
    </layout>
  </appender>
</log4j:configuration>"""

NO_PATTERN_XML = """<?xml version="1.0"?>
<Configuration>
  <Appenders>
    <Console name="Console"/>
  </Appenders>
</Configuration>"""

MALFORMED_XML = "<Configuration><unclosed>"


def _write_temp(content, suffix='.xml'):
    with tempfile.NamedTemporaryFile(suffix=suffix, mode='w', delete=False) as f:
        f.write(content)
        return f.name


class ValidateLogsDirTests(SimpleTestCase):
    def test_rejects_empty(self):
        with self.assertRaises(runner.PreflightError):
            runner.validate_logs_dir('')

    def test_rejects_relative_path(self):
        with self.assertRaises(runner.PreflightError):
            runner.validate_logs_dir('relative/path')

    def test_rejects_nonexistent_directory(self):
        with self.assertRaises(runner.PreflightError):
            runner.validate_logs_dir('/tmp/qa-helper-tool-does-not-exist-xyz')

    def test_accepts_existing_directory(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(runner.validate_logs_dir(d), d)


class ValidateLog4jXmlPathTests(SimpleTestCase):
    def test_empty_is_valid_and_returns_empty(self):
        self.assertEqual(runner.validate_log4j_xml_path(''), '')
        self.assertEqual(runner.validate_log4j_xml_path('   '), '')

    def test_rejects_relative_path(self):
        with self.assertRaises(runner.PreflightError):
            runner.validate_log4j_xml_path('relative/log4j2.xml')

    def test_rejects_nonexistent_file(self):
        with self.assertRaises(runner.PreflightError):
            runner.validate_log4j_xml_path('/tmp/qa-helper-tool-does-not-exist-xyz.xml')

    def test_accepts_existing_file(self):
        path = _write_temp(LOG4J2_XML)
        self.assertEqual(runner.validate_log4j_xml_path(path), path)


class FindLogFilesTests(SimpleTestCase):
    def test_finds_plain_and_rotated_log_files_sorted_by_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            older = os.path.join(d, 'app.log.1')
            newer = os.path.join(d, 'app.log')
            with open(older, 'w') as f:
                f.write('old\n')
            with open(newer, 'w') as f:
                f.write('new\n')
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))
            found = runner.find_log_files(d)
            self.assertEqual(found, [older, newer])

    def test_ignores_non_log_files(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'notes.txt'), 'w') as f:
                f.write('irrelevant\n')
            self.assertEqual(runner.find_log_files(d), [])


class ParseLog4jConversionPatternTests(SimpleTestCase):
    def test_extracts_log4j2_pattern_layout(self):
        path = _write_temp(LOG4J2_XML)
        self.assertEqual(
            runner.parse_log4j_conversion_pattern(path),
            '%d{yyyy-MM-dd HH:mm:ss.SSS} %-5level [%t] %c{1.} - %msg%n',
        )

    def test_extracts_log4j1_conversion_pattern(self):
        path = _write_temp(LOG4J1_XML)
        self.assertEqual(
            runner.parse_log4j_conversion_pattern(path),
            '%d{ISO8601} %-5p [%t] %c{1}:%L - %m%n',
        )

    def test_returns_none_when_no_pattern_found(self):
        path = _write_temp(NO_PATTERN_XML)
        self.assertIsNone(runner.parse_log4j_conversion_pattern(path))

    def test_malformed_xml_raises_preflight_error(self):
        path = _write_temp(MALFORMED_XML)
        with self.assertRaises(runner.PreflightError):
            runner.parse_log4j_conversion_pattern(path)


class CompilePatternTests(SimpleTestCase):
    def test_extracts_all_fields_and_parses_timestamp(self):
        compiled = runner.compile_pattern('%d{yyyy-MM-dd HH:mm:ss.SSS} %-5level [%t] %c{1.} - %msg%n')
        line = (
            '2024-01-15 10:23:45.123 INFO [http-nio-8080-exec-1] '
            'c.e.OrderController - Received request GET /orders/5'
        )
        match = compiled.regex.match(line)
        self.assertIsNotNone(match)
        groups = match.groupdict()
        self.assertEqual(groups['level'], 'INFO')
        self.assertEqual(groups['thread'], 'http-nio-8080-exec-1')
        self.assertEqual(groups['logger'], 'c.e.OrderController')
        self.assertEqual(groups['message'], 'Received request GET /orders/5')
        parsed = datetime.strptime(groups['timestamp'], compiled.strptime_format)
        self.assertEqual(parsed, datetime(2024, 1, 15, 10, 23, 45, 123000))

    def test_iso8601_named_date_format_and_unsupported_specifier_tolerated(self):
        compiled = runner.compile_pattern('%d{ISO8601} %-5p [%t] %c{1}:%L - %m%n')
        line = '2024-01-15 10:23:45,123 INFO  [main] com.example.Foo:42 - hello world'
        match = compiled.regex.match(line)
        self.assertIsNotNone(match)
        groups = match.groupdict()
        self.assertEqual(groups['level'].strip(), 'INFO')
        self.assertEqual(groups['thread'], 'main')
        self.assertEqual(groups['logger'], 'com.example.Foo')
        self.assertEqual(groups['message'], 'hello world')

    def test_pattern_without_message_specifier_still_compiles(self):
        compiled = runner.compile_pattern('%d{yyyy-MM-dd} %p')
        self.assertIsNotNone(compiled.regex.match('2024-01-15 INFO trailing text'))


class DefaultCompiledPatternTests(SimpleTestCase):
    def test_matches_spring_boot_default_line_with_pid(self):
        compiled = runner.default_compiled_pattern()
        line = (
            '2024-01-15 10:23:45.123  INFO 12345 --- [nio-8080-exec-1] '
            'c.e.d.controller.OrderController        : Received request'
        )
        match = compiled.regex.match(line)
        self.assertIsNotNone(match)
        groups = match.groupdict()
        self.assertEqual(groups['level'], 'INFO')
        self.assertEqual(groups['thread'], 'nio-8080-exec-1')
        self.assertEqual(groups['logger'], 'c.e.d.controller.OrderController')
        self.assertEqual(groups['message'], 'Received request')
        parsed = datetime.strptime(groups['timestamp'], compiled.strptime_format)
        self.assertEqual(parsed, datetime(2024, 1, 15, 10, 23, 45, 123000))

    def test_matches_line_without_pid(self):
        compiled = runner.default_compiled_pattern()
        line = '2024-01-15 10:23:45.999 ERROR  --- [           main] c.e.d.Application : Boom'
        self.assertIsNotNone(compiled.regex.match(line))


class ClassifyRequestResponseTests(SimpleTestCase):
    def test_http_method_and_path_is_request_like(self):
        is_req, is_resp = runner._classify_request_response('GET /api/orders/5')
        self.assertTrue(is_req)
        self.assertFalse(is_resp)

    def test_status_code_mention_is_response_like(self):
        is_req, is_resp = runner._classify_request_response('Completed with status=200 in 12ms')
        self.assertFalse(is_req)
        self.assertTrue(is_resp)

    def test_ordinary_message_is_neither(self):
        is_req, is_resp = runner._classify_request_response('Starting application on host xyz')
        self.assertFalse(is_req)
        self.assertFalse(is_resp)


class ParseLogFilesTests(SimpleTestCase):
    def _pattern(self):
        return runner.default_compiled_pattern()

    def test_multiline_stack_trace_is_folded_into_previous_entry(self):
        content = (
            '2024-01-15 10:23:45.123  INFO 1 --- [main] c.e.Foo : starting up\n'
            '2024-01-15 10:23:46.000 ERROR 1 --- [main] c.e.Foo : boom\n'
            'java.lang.RuntimeException: boom\n'
            '\tat com.example.Foo.bar(Foo.java:10)\n'
            '2024-01-15 10:23:47.000  INFO 1 --- [main] c.e.Foo : recovered\n'
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'app.log')
            with open(path, 'w') as f:
                f.write(content)
            entries, warnings = runner.parse_log_files([path], self._pattern())

        self.assertEqual(warnings, [])
        self.assertEqual(len(entries), 3)
        boom = entries[1]
        self.assertEqual(boom['level'], 'ERROR')
        self.assertIn('boom', boom['message'])
        self.assertIn('java.lang.RuntimeException: boom', boom['message'])
        self.assertIn('at com.example.Foo.bar(Foo.java:10)', boom['message'])

    def test_lines_before_any_match_are_kept_as_a_raw_entry(self):
        content = (
            '  ____  _          _\n'
            ' / ___|| |_ __ _ _(_)_ __   __ _\n'
            '2024-01-15 10:23:45.123  INFO 1 --- [main] c.e.Foo : started\n'
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'app.log')
            with open(path, 'w') as f:
                f.write(content)
            entries, _ = runner.parse_log_files([path], self._pattern())

        self.assertEqual(len(entries), 2)
        banner = entries[0]
        self.assertEqual(banner['level'], '')
        self.assertIn('____', banner['message'])

    def test_multiple_files_are_merged_in_mtime_order_with_increasing_seq(self):
        with tempfile.TemporaryDirectory() as d:
            first = os.path.join(d, 'app.log.1')
            second = os.path.join(d, 'app.log')
            with open(first, 'w') as f:
                f.write('2024-01-15 10:00:00.000  INFO 1 --- [main] c.e.Foo : first file\n')
            with open(second, 'w') as f:
                f.write('2024-01-15 11:00:00.000  INFO 1 --- [main] c.e.Foo : second file\n')
            os.utime(first, (1000, 1000))
            os.utime(second, (2000, 2000))
            paths = runner.find_log_files(d)
            entries, _ = runner.parse_log_files(paths, self._pattern())

        self.assertEqual([e['message'] for e in entries], ['first file', 'second file'])
        self.assertLess(entries[0]['seq'], entries[1]['seq'])

    def test_max_entries_cap_truncates_and_warns(self):
        lines = ''.join(
            f'2024-01-15 10:00:{i:02d}.000  INFO 1 --- [main] c.e.Foo : line {i}\n' for i in range(60)
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'app.log')
            with open(path, 'w') as f:
                f.write(lines)
            with patch.object(runner, 'MAX_LOG_ENTRIES', 5):
                entries, warnings = runner.parse_log_files([path], self._pattern())

        self.assertEqual(len(entries), 5)
        self.assertTrue(any('cap' in w for w in warnings))

    def test_request_response_flags_are_set_on_entries(self):
        content = (
            '2024-01-15 10:00:00.000  INFO 1 --- [main] c.e.Foo : GET /orders/5\n'
            '2024-01-15 10:00:01.000  INFO 1 --- [main] c.e.Foo : completed with status=200\n'
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'app.log')
            with open(path, 'w') as f:
                f.write(content)
            entries, _ = runner.parse_log_files([path], self._pattern())

        self.assertTrue(entries[0]['is_request_like'])
        self.assertTrue(entries[1]['is_response_like'])
