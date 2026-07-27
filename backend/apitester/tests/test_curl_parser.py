from base64 import b64encode

from django.test import SimpleTestCase

from apitester.curl_parser import CurlParseError, parse_curl


class CurlParserTests(SimpleTestCase):
    def test_get_no_body(self):
        parsed = parse_curl("curl https://api.example.com/users")
        self.assertEqual(parsed.method, 'GET')
        self.assertEqual(parsed.url, 'https://api.example.com/users')
        self.assertEqual(parsed.headers, {})
        self.assertIsNone(parsed.body)

    def test_post_with_json_body_and_repeated_headers(self):
        curl = (
            "curl -X POST https://api.example.com/users "
            "-H 'Content-Type: application/json' "
            "-H 'Authorization: Bearer abc123' "
            "-d '{\"name\": \"Ada\", \"age\": 30}'"
        )
        parsed = parse_curl(curl)
        self.assertEqual(parsed.method, 'POST')
        self.assertEqual(parsed.headers['Content-Type'], 'application/json')
        self.assertEqual(parsed.headers['Authorization'], 'Bearer abc123')
        self.assertTrue(parsed.is_json_body)
        self.assertEqual(parsed.body, {'name': 'Ada', 'age': 30})

    def test_data_flag_implies_post_without_explicit_x(self):
        curl = "curl https://api.example.com/users -d '{\"name\": \"Ada\"}'"
        parsed = parse_curl(curl)
        self.assertEqual(parsed.method, 'POST')
        self.assertEqual(parsed.body, {'name': 'Ada'})

    def test_basic_auth_flag_sets_authorization_header(self):
        curl = "curl -u alice:secret https://api.example.com/secure"
        parsed = parse_curl(curl)
        expected_token = b64encode(b'alice:secret').decode('ascii')
        self.assertEqual(parsed.headers['Authorization'], f'Basic {expected_token}')

    def test_non_json_body_kept_raw(self):
        curl = "curl https://api.example.com/form -d 'a=1&b=2'"
        parsed = parse_curl(curl)
        self.assertFalse(parsed.is_json_body)
        self.assertIsNone(parsed.body)
        self.assertEqual(parsed.body_raw, 'a=1&b=2')

    def test_missing_url_raises(self):
        with self.assertRaises(CurlParseError):
            parse_curl("curl -X POST -H 'Content-Type: application/json'")

    def test_empty_string_raises(self):
        with self.assertRaises(CurlParseError):
            parse_curl('   ')

    def test_multiline_curl_with_continuations(self):
        curl = (
            "curl https://api.example.com/users \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -d '{\"x\": 1}'"
        )
        parsed = parse_curl(curl)
        self.assertEqual(parsed.url, 'https://api.example.com/users')
        self.assertEqual(parsed.body, {'x': 1})
