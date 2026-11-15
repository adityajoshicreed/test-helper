package com.qahelper;

import static com.qahelper.Json.*;
import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.*;
import java.util.*;
import java.util.regex.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class CurlEngineTest {
  CurlEngine engine = new CurlEngine();
  @TempDir Path temp;

  @Test
  void curlParsingHandlesJsonBasicAuthAndMultiline() {
    var r =
        engine.parse(
            "curl \\\n"
                + " -X POST 'https://example.com/items' -u 'user:password' -H 'Content-Type:"
                + " application/json' -d '{\"name\":\"Ada\"}'");
    assertEquals("POST", r.get("method"));
    assertEquals("https://example.com/items", r.get("url"));
    assertEquals("Ada", map(r.get("body")).get("name"));
    assertEquals("Basic dXNlcjpwYXNzd29yZA==", map(r.get("headers")).get("Authorization"));
  }

  @Test
  void rawBodyAndGetQuery() {
    var raw = engine.parse("curl https://example.com -d 'hello world'");
    assertEquals("POST", raw.get("method"));
    assertEquals("hello world", raw.get("body_raw"));
    assertEquals(false, raw.get("is_json_body"));
    var get = engine.parse("curl https://example.com?q=x -G -d 'page=1'");
    assertEquals("GET", get.get("method"));
    assertEquals("https://example.com?q=x&page=1", get.get("url"));
  }

  @ParameterizedTest
  @ValueSource(
      strings = {"", "curl", "curl -X", "curl 'broken", "curl https://example.com -F 'file=@x'"})
  void malformedCurlRejected(String command) {
    assertThrows(ApiError.class, () -> engine.parse(command));
  }

  @Test
  void nestedMutationsDoNotModifySource() {
    var r =
        engine.parse("curl https://example.com -d '{\"items\":[{\"name\":\"Ada\",\"qty\":2}]}'");
    var cases =
        engine.generate(
            r,
            obj(
                "body_field_tests",
                obj(
                    "items[0].name",
                    List.of(
                        "body_field_null",
                        "body_field_missing",
                        "body_field_wrong_type",
                        "body_field_empty"))));
    assertEquals(5, cases.size());
    assertEquals("Ada", CurlEngine.valueAt(r.get("body"), "items[0].name"));
    assertNull(CurlEngine.valueAt(cases.get(1).get("request_body"), "items[0].name"));
    assertEquals(2, CurlEngine.valueAt(cases.get(1).get("request_body"), "items[0].qty"));
    assertFalse(
        map(((List<?>) map(cases.get(2).get("request_body")).get("items")).getFirst())
            .containsKey("name"));
  }

  @Test
  void dynamicHeadersRegeneratedExceptSelectedMutations() {
    var r = engine.parse("curl https://example.com -H 'X-Request-Id: original'");
    var cases =
        engine.generate(
            r, obj("header_tests", obj("X-Request-Id", List.of("header_missing", "header_empty"))));
    assertNotEquals("original", map(cases.getFirst().get("request_headers")).get("X-Request-Id"));
    assertFalse(map(cases.get(1).get("request_headers")).containsKey("X-Request-Id"));
    assertEquals("", map(cases.get(2).get("request_headers")).get("X-Request-Id"));
  }

  @Test
  void bodyAndMethodBlanketCases() {
    var r = engine.parse("curl https://example.com -d '{\"name\":\"Ada\"}'");
    var cases = engine.generate(r, obj("categories", List.of("body_whole", "http_method")));
    assertEquals(12, cases.size());
    assertEquals(6, cases.stream().filter(c -> "http_method".equals(c.get("category"))).count());
    assertEquals(1, engine.generate(r, obj()).size());
  }

  @Test
  void onlyApplicableFieldOptionsAndStalePathsIgnored() {
    var r =
        engine.parse("curl https://example.com -d '{\"active\":true,\"age\":1,\"other\":null}'");
    var options = rows(engine.decorate(r).get("body_field_options"));
    assertEquals(3, options.size());
    assertFalse(
        rows(options.getFirst().get("tests")).stream()
            .anyMatch(t -> "body_field_empty".equals(t.get("code"))));
    assertEquals(
        1,
        engine
            .generate(r, obj("body_field_tests", obj("missing", List.of("body_field_null"))))
            .size());
  }

  @Test
  void pathDiscoveryBoundsArrayBreadth() {
    var r = engine.parse("curl https://example.com -d '{\"items\":[1,2,3,4,5,6,7]}'");
    var paths = rows(engine.decorate(r).get("body_field_options"));
    assertEquals(6, paths.size());
    assertFalse(paths.stream().anyMatch(p -> "items[5]".equals(p.get("field"))));
  }

  @Test
  void chainSubstitutionIsRecursiveAndUnknownVariablesRemain() {
    var result =
        map(
            ApiTestingService.substitute(
                obj(
                    "url",
                    "http://example.com/{{id}}",
                    "body",
                    List.of(obj("token", "{{token}}")),
                    "missing",
                    "{{unknown}}"),
                obj("id", 42, "token", "abc")));
    assertEquals("http://example.com/42", result.get("url"));
    assertEquals("abc", map(((List<?>) result.get("body")).getFirst()).get("token"));
    assertEquals("{{unknown}}", result.get("missing"));
  }

  @ParameterizedTest
  @ValueSource(
      strings = {"OK", "\nhealthy\nsecond line\n", "<html>healthy</html>", "  spaced text  "})
  void plainTextKarateResponsePreserved(String body) {
    for (boolean separate : List.of(false, true)) {
      String head =
          "request:\n"
              + "1 > GET https://example.com\n\n"
              + "response time in milliseconds: 1\n"
              + "1 < 200 GET https://example.com\n"
              + "1 < Content-Type: text/plain\n";
      var segments =
          separate
              ? List.of(obj("text", head), obj("text", body))
              : List.of(obj("text", head + body));
      var step = KarateService.parseSegments(segments, "get", new ArrayList<>());
      assertEquals(body.replaceAll("^[\\r\\n]+|[\\r\\n]+$", ""), step.get("response_body"));
    }
  }

  @Test
  void structuredKarateCodeAndEmptyResponse() {
    String header =
        "request:\n"
            + "1 > GET https://example.com\n\n"
            + "response time in milliseconds: 1\n"
            + "1 < 200 GET https://example.com\n";
    var step =
        KarateService.parseSegments(
            List.of(obj("text", header), obj("code", "{\"ok\":true}")), "get", new ArrayList<>());
    assertEquals("{\"ok\":true}", step.get("response_body"));
    assertNull(
        KarateService.parseSegments(List.of(obj("text", header)), "get", new ArrayList<>())
            .get("response_body"));
  }

  @Test
  void logTimestampsNormalizeOffsetsAndPreserveInvalidAsNull() {
    assertEquals("2026-11-15T08:00:00Z", LogService.timestamp("2026-11-15T10:00:00.000+02:00"));
    assertEquals("2026-11-15T10:00:00Z", LogService.timestamp("2026-11-15 10:00:00.000"));
    assertNull(LogService.timestamp("invalid"));
  }

  @Test
  void logXmlRejectsExternalEntities() throws Exception {
    Path secret = temp.resolve("secret.txt");
    Files.writeString(secret, "private-value");
    Path xml = temp.resolve("unsafe.xml");
    Files.writeString(
        xml,
        "<!DOCTYPE a [<!ENTITY xxe SYSTEM '"
            + secret.toUri()
            + "'>]><Configuration><ConversionPattern>&xxe;</ConversionPattern></Configuration>");
    assertThrows(Exception.class, () -> LogService.xmlPattern(xml));
  }

  @Test
  void bodyCurlShellQuotingRoundTrip() {
    var r = engine.parse("curl https://example.com -d '{\"name\":\"Ada\"}'");
    var base = engine.base(r, "baseline", "baseline");
    map(base.get("request_headers")).put("X-Test", "it's safe");
    var parsed = engine.parse(CurlEngine.curl(base));
    assertEquals("it's safe", map(parsed.get("headers")).get("X-Test"));
    assertEquals(r.get("body"), parsed.get("body"));
  }
}
