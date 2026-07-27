from django.test import SimpleTestCase

from apitester.models import ImportedRequest
from apitester.test_generator import (
    MAX_ARRAY_ITEMS_PER_LEVEL,
    MAX_PATH_DEPTH,
    available_categories,
    body_field_options,
    detect_dynamic_headers,
    generate_test_cases,
    header_field_options,
)


def make_request(**overrides):
    defaults = dict(
        method='POST',
        url='https://api.example.com/users',
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer abc'},
        body={'name': 'Ada', 'age': 30, 'active': True, 'tags': ['a', 'b']},
        body_raw=None,
        is_json_body=True,
    )
    defaults.update(overrides)
    return ImportedRequest(**defaults)


class AvailableCategoriesTests(SimpleTestCase):
    def test_blanket_categories_flag_applicability(self):
        req = make_request()
        cats = {c['code']: c['applicable'] for c in available_categories(req)}
        self.assertTrue(cats['body_whole'])
        self.assertTrue(cats['http_method'])

    def test_body_whole_not_applicable_without_any_body(self):
        req = make_request(body=None, body_raw=None, is_json_body=False)
        cats = {c['code']: c['applicable'] for c in available_categories(req)}
        self.assertFalse(cats['body_whole'])
        self.assertTrue(cats['http_method'])


class BodyFieldOptionsTests(SimpleTestCase):
    def test_lists_one_entry_per_field_including_array_elements(self):
        req = make_request()
        options = {o['field']: {t['code'] for t in o['tests']} for o in body_field_options(req)}
        # 'tags' is a list, so each element gets its own path too (tags[0], tags[1]).
        self.assertEqual(set(options.keys()), {'name', 'age', 'active', 'tags', 'tags[0]', 'tags[1]'})
        # str field: null/missing always, plus empty and wrong_type.
        self.assertEqual(
            options['name'],
            {'body_field_null', 'body_field_missing', 'body_field_empty', 'body_field_wrong_type'},
        )
        # bool field: no meaningful "empty".
        self.assertEqual(options['active'], {'body_field_null', 'body_field_missing', 'body_field_wrong_type'})
        # scalar array element (a string): behaves like any other string field.
        self.assertEqual(
            options['tags[0]'],
            {'body_field_null', 'body_field_missing', 'body_field_empty', 'body_field_wrong_type'},
        )

    def test_empty_for_non_json_object_body(self):
        req = make_request(body=None, body_raw=None, is_json_body=False)
        self.assertEqual(body_field_options(req), [])


class HeaderFieldOptionsTests(SimpleTestCase):
    def test_lists_one_entry_per_header_with_both_tests(self):
        req = make_request()
        options = {o['header']: {t['code'] for t in o['tests']} for o in header_field_options(req)}
        self.assertEqual(set(options.keys()), {'Content-Type', 'Authorization'})
        self.assertEqual(options['Authorization'], {'header_missing', 'header_empty'})

    def test_empty_without_headers(self):
        req = make_request(headers={})
        self.assertEqual(header_field_options(req), [])


class GenerateTestCasesTests(SimpleTestCase):
    def test_baseline_always_included_even_with_no_selection(self):
        req = make_request()
        cases = generate_test_cases(req)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]['category'], 'baseline')

    def test_only_selected_fields_and_test_codes_are_generated(self):
        req = make_request()
        cases = generate_test_cases(req, body_field_tests={'name': ['body_field_null']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(len(non_baseline), 1)
        self.assertEqual(non_baseline[0]['description'], "Set field 'name' to null")
        self.assertIsNone(non_baseline[0]['request_body']['name'])

    def test_multiple_tests_for_the_same_field(self):
        req = make_request()
        cases = generate_test_cases(
            req, body_field_tests={'age': ['body_field_null', 'body_field_missing']}
        )
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(len(non_baseline), 2)
        categories = {c['category'] for c in non_baseline}
        self.assertEqual(categories, {'body_field_null', 'body_field_missing'})

    def test_unselected_fields_are_not_touched(self):
        req = make_request()
        cases = generate_test_cases(req, body_field_tests={'name': ['body_field_null']})
        for c in cases:
            if c['category'] == 'body_field_null':
                self.assertEqual(c['request_body']['age'], 30)

    def test_ignores_test_code_not_applicable_to_field(self):
        # 'active' is a bool -- "empty" isn't a valid mutation for it.
        req = make_request()
        cases = generate_test_cases(req, body_field_tests={'active': ['body_field_empty']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(non_baseline, [])

    def test_ignores_unknown_field_name(self):
        req = make_request()
        cases = generate_test_cases(req, body_field_tests={'nonexistent': ['body_field_null']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(non_baseline, [])

    def test_body_whole_is_blanket_via_categories(self):
        req = make_request()
        cases = generate_test_cases(req, categories=['body_whole'])
        descriptions = {c['description'] for c in cases if c['category'] == 'body_whole'}
        self.assertIn('Request sent with no body at all', descriptions)

    def test_only_selected_headers_and_test_codes_are_generated(self):
        req = make_request()
        cases = generate_test_cases(req, header_tests={'Authorization': ['header_missing']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(len(non_baseline), 1)
        self.assertEqual(non_baseline[0]['description'], "Remove header 'Authorization'")
        self.assertNotIn('Authorization', non_baseline[0]['request_headers'])
        self.assertEqual(non_baseline[0]['request_headers']['Content-Type'], 'application/json')

    def test_http_method_excludes_original_method(self):
        req = make_request(method='POST')
        cases = generate_test_cases(req, categories=['http_method'])
        methods = {c['request_method'] for c in cases if c['category'] == 'http_method'}
        self.assertNotIn('POST', methods)
        self.assertIn('GET', methods)
        self.assertIn('DELETE', methods)


class NestedBodyFieldTests(SimpleTestCase):
    def _nested_request(self):
        return make_request(body={
            'user': {
                'name': 'Ada',
                'address': {'city': 'NY', 'zip': '10001'},
            },
            'items': [{'id': 1}, {'id': 2}],
            'tags': ['x', 'y'],
        })

    def test_body_field_options_includes_nested_paths(self):
        req = self._nested_request()
        paths = {o['field'] for o in body_field_options(req)}
        self.assertEqual(paths, {
            'user', 'user.name', 'user.address', 'user.address.city', 'user.address.zip',
            'items', 'items[0]', 'items[0].id', 'items[1]', 'items[1].id',
            'tags', 'tags[0]', 'tags[1]',
        })

    def test_nested_object_itself_is_selectable(self):
        # You can test "remove the whole address object", not just its fields.
        req = self._nested_request()
        cases = generate_test_cases(req, body_field_tests={'user.address': ['body_field_missing']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(len(non_baseline), 1)
        self.assertNotIn('address', non_baseline[0]['request_body']['user'])
        self.assertEqual(non_baseline[0]['request_body']['user']['name'], 'Ada')

    def test_deeply_nested_leaf_can_be_mutated_in_isolation(self):
        req = self._nested_request()
        cases = generate_test_cases(req, body_field_tests={'user.address.city': ['body_field_null']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(len(non_baseline), 1)
        mutated_body = non_baseline[0]['request_body']
        self.assertIsNone(mutated_body['user']['address']['city'])
        # Sibling untouched.
        self.assertEqual(mutated_body['user']['address']['zip'], '10001')
        self.assertEqual(mutated_body['user']['name'], 'Ada')

    def test_array_element_field_can_be_mutated(self):
        req = self._nested_request()
        cases = generate_test_cases(req, body_field_tests={'items[0].id': ['body_field_wrong_type']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(len(non_baseline), 1)
        mutated_body = non_baseline[0]['request_body']
        self.assertEqual(mutated_body['items'][0]['id'], 'not-a-number')
        self.assertEqual(mutated_body['items'][1]['id'], 2)

    def test_array_element_missing_removes_that_element(self):
        req = self._nested_request()
        cases = generate_test_cases(req, body_field_tests={'items[0]': ['body_field_missing']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        mutated_items = non_baseline[0]['request_body']['items']
        self.assertEqual(mutated_items, [{'id': 2}])

    def test_scalar_array_element_can_be_mutated(self):
        req = self._nested_request()
        cases = generate_test_cases(req, body_field_tests={'tags[0]': ['body_field_null']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertIsNone(non_baseline[0]['request_body']['tags'][0])
        self.assertEqual(non_baseline[0]['request_body']['tags'][1], 'y')

    def test_stale_path_that_no_longer_resolves_is_ignored(self):
        req = self._nested_request()
        cases = generate_test_cases(req, body_field_tests={'user.address.country': ['body_field_null']})
        non_baseline = [c for c in cases if c['category'] != 'baseline']
        self.assertEqual(non_baseline, [])

    def test_recursion_depth_is_capped(self):
        # Build a chain deeper than MAX_PATH_DEPTH and confirm discovery stops.
        body = {}
        cursor = body
        for i in range(MAX_PATH_DEPTH + 3):
            cursor[f'level{i}'] = {}
            cursor = cursor[f'level{i}']
        cursor['too_deep'] = 'value'
        req = make_request(body=body)
        paths = {o['field'] for o in body_field_options(req)}
        self.assertNotIn('too_deep', ' '.join(paths))
        for path in paths:
            depth = path.count('.') + path.count('[')
            self.assertLess(depth, MAX_PATH_DEPTH)

    def test_array_breadth_is_capped(self):
        req = make_request(body={'items': [{'id': i} for i in range(MAX_ARRAY_ITEMS_PER_LEVEL + 5)]})
        paths = {o['field'] for o in body_field_options(req)}
        included_indexes = {p for p in paths if p.startswith('items[') and p.endswith(']')}
        self.assertEqual(len(included_indexes), MAX_ARRAY_ITEMS_PER_LEVEL)


class DynamicHeaderTests(SimpleTestCase):
    def test_detects_common_request_id_style_headers(self):
        for name in ('X-Req-Id', 'X-Request-Id', 'X-Correlation-ID', 'x-trace-id', 'Idempotency-Key'):
            self.assertEqual(detect_dynamic_headers({name: 'abc'}), [name], name)

    def test_does_not_flag_ordinary_headers(self):
        self.assertEqual(detect_dynamic_headers({'Content-Type': 'application/json', 'Authorization': 'x'}), [])

    def test_dynamic_header_gets_a_fresh_value_on_every_generated_case(self):
        req = make_request(headers={'Content-Type': 'application/json', 'X-Req-Id': 'literal-from-curl'})
        cases = generate_test_cases(req, body_field_tests={'name': ['body_field_null'], 'age': ['body_field_null']})
        values = {c['request_headers']['X-Req-Id'] for c in cases}
        self.assertNotIn('literal-from-curl', values)
        self.assertEqual(len(values), len(cases))

    def test_header_missing_case_still_removes_the_dynamic_header_itself(self):
        req = make_request(headers={'Content-Type': 'application/json', 'X-Req-Id': 'literal-from-curl'})
        cases = generate_test_cases(req, header_tests={'X-Req-Id': ['header_missing']})
        target_case = next(c for c in cases if c['description'] == "Remove header 'X-Req-Id'")
        self.assertNotIn('X-Req-Id', target_case['request_headers'])
        self.assertEqual(target_case['request_headers']['Content-Type'], 'application/json')

    def test_header_empty_case_still_empties_the_dynamic_header_itself(self):
        req = make_request(headers={'Content-Type': 'application/json', 'X-Req-Id': 'literal-from-curl'})
        cases = generate_test_cases(req, header_tests={'X-Req-Id': ['header_empty']})
        target_case = next(c for c in cases if c['description'] == "Set header 'X-Req-Id' to an empty string")
        self.assertEqual(target_case['request_headers']['X-Req-Id'], '')

    def test_header_missing_case_for_other_header_still_gets_fresh_dynamic_value(self):
        req = make_request(headers={'Content-Type': 'application/json', 'X-Req-Id': 'literal-from-curl'})
        cases = generate_test_cases(req, header_tests={'Content-Type': ['header_missing']})
        content_type_case = next(c for c in cases if c['description'] == "Remove header 'Content-Type'")
        self.assertNotIn('literal-from-curl', content_type_case['request_headers']['X-Req-Id'])
