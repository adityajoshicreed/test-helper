package com.qahelper;

import static com.qahelper.Json.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(
    properties = {
      "spring.datasource.url=jdbc:h2:mem:integration;DB_CLOSE_DELAY=-1",
      "qa.job-workers=4"
    })
@AutoConfigureMockMvc
class BackendIntegrationTest {
  @Autowired MockMvc mvc;
  @Autowired DocumentStore store;
  @Autowired JdbcTemplate jdbc;
  @Autowired Jobs jobs;
  @TempDir Path temp;
  HttpServer target;
  String base;
  List<Long> times;
  List<String> received;
  AtomicInteger limited;

  @BeforeEach
  void start() throws Exception {
    times = new CopyOnWriteArrayList<>();
    received = new CopyOnWriteArrayList<>();
    limited = new AtomicInteger();
    target = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    target.createContext(
        "/",
        exchange -> {
          times.add(System.nanoTime());
          String path = exchange.getRequestURI().getPath();
          String auth = exchange.getRequestHeaders().getFirst("Authorization");
          received.add(
              path
                  + " "
                  + auth
                  + " "
                  + new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
          int code = 200;
          String response = "{\"ok\":true}";
          if (path.equals("/login")) response = "{\"token\":\"fresh-token\"}";
          if (path.equals("/credential") && !"fresh-token".equals(auth)) {
            code = 401;
            response = "token expired";
          }
          if (path.equals("/limited") && limited.getAndIncrement() < 2) {
            code = 429;
            exchange.getResponseHeaders().set("Retry-After", "0");
          }
          if (path.equals("/api/generate"))
            response =
                write(
                    obj(
                        "response",
                        write(
                            obj(
                                "steps",
                                List.of(
                                    obj(
                                        "description",
                                        "Check service health",
                                        "expected_result",
                                        "Service is healthy"))))));
          byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
          exchange.sendResponseHeaders(code, bytes.length);
          exchange.getResponseBody().write(bytes);
          exchange.close();
        });
    target.start();
    base = "http://127.0.0.1:" + target.getAddress().getPort();
  }

  @AfterEach
  void stop() {
    target.stop(0);
  }

  Map<String, Object> postJson(String path, Map<String, Object> b, int code) throws Exception {
    return map(
        read(
            mvc.perform(post(path).contentType("application/json").content(write(b)))
                .andExpect(status().is(code))
                .andReturn()
                .getResponse()
                .getContentAsString()));
  }

  Map<String, Object> getJson(String path) throws Exception {
    return map(
        read(
            mvc.perform(get(path))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString()));
  }

  Map<String, Object> await(String path, String state) throws Exception {
    long end = System.nanoTime() + 10_000_000_000L;
    Map<String, Object> value;
    do {
      value = getJson(path);
      if (state.equals(value.get("status"))) return value;
      if ("failed".equals(value.get("status"))) fail(write(value));
      Thread.sleep(10);
    } while (System.nanoTime() < end);
    fail("Timed out waiting for " + state + ": " + write(value));
    return value;
  }

  long imported(String command) throws Exception {
    return id(postJson("/api/import-curl/", obj("curl", command), 201));
  }

  Map<String, Object> apiRun(long request, Map<String, Object> selection) throws Exception {
    return postJson("/api/imported-requests/" + request + "/test-runs/", selection, 201);
  }

  Map<String, Object> selection(double delay) {
    return obj(
        "delay_seconds",
        delay,
        "header_tests",
        obj("X-Test", List.of("header_empty", "header_missing")));
  }

  Map<String, Object> credentialPayload(String token) {
    return obj(
        "raw_curl",
        "curl " + base + "/credential -H 'Authorization: " + token + "' -H 'X-Test: value'",
        "credential_fields",
        List.of(obj("location", "header", "key", "Authorization")),
        "current_values",
        obj("Authorization", token),
        "expiration_status_code",
        401,
        "delay_seconds",
        .04,
        "header_tests",
        obj("X-Test", List.of("header_empty", "header_missing")));
  }

  @Test
  void healthCorsAndMissingRecords() throws Exception {
    assertEquals("spring-boot", getJson("/api/health/").get("backend"));
    mvc.perform(
            options("/api/import-curl/")
                .header("Origin", "http://localhost:5173")
                .header("Access-Control-Request-Method", "POST"))
        .andExpect(status().isOk())
        .andExpect(header().string("Access-Control-Allow-Origin", "http://localhost:5173"));
    mvc.perform(get("/api/imported-requests/999999/"))
        .andExpect(status().isNotFound())
        .andExpect(jsonPath("$.error").exists());
    postJson("/api/import-curl/", obj("curl", "curl 'unterminated"), 400);
  }

  @Test
  void apiMutationPacingAndExcelExport() throws Exception {
    long request =
        imported(
            "curl "
                + base
                + "/echo -H 'X-Test: value' -H 'Content-Type: application/json' -d"
                + " '{\"user\":{\"name\":\"Ada\"}}'");
    var details = getJson("/api/imported-requests/" + request + "/");
    assertFalse(rows(details.get("body_field_options")).isEmpty());
    var select = selection(.06);
    select.put("body_field_tests", obj("user.name", List.of("body_field_null")));
    var created = apiRun(request, select);
    var run = await("/api/test-runs/" + id(created) + "/", "completed");
    var cases = rows(run.get("test_cases"));
    assertEquals(4, cases.size());
    assertEquals(.06, number(run.get("delay_seconds"), 0));
    assertEquals(4, received.size());
    for (int i = 1; i < times.size(); i++)
      assertTrue(
          (times.get(i) - times.get(i - 1)) / 1e6 >= 50, "Configured delay was not respected.");
    assertTrue(received.get(1).contains("\"name\":null"));
    Path file = temp.resolve("api.xlsx");
    var exported =
        postJson(
            "/api/test-runs/" + id(created) + "/export-excel/",
            obj("excel_path", file.toString()),
            200);
    assertEquals(4, number(exported.get("exported_case_count"), 0));
    try (var wb = new XSSFWorkbook(Files.newInputStream(file))) {
      assertEquals(5, wb.getSheetAt(0).getPhysicalNumberOfRows());
      assertTrue(
          wb.getSheetAt(0).getRow(1).getCell(9).getStringCellValue().contains("\"ok\":true"));
    }
  }

  @Test
  void delayValidationAndZeroDefault() throws Exception {
    long request = imported("curl " + base + "/echo");
    for (Object invalid : List.of(-1, 61, "1", true, List.of(), obj()))
      postJson(
          "/api/imported-requests/" + request + "/test-runs/", obj("delay_seconds", invalid), 400);
    var run = apiRun(request, obj());
    assertEquals(0, number(run.get("delay_seconds"), -1));
    await("/api/test-runs/" + id(run) + "/", "completed");
  }

  @Test
  void stoppingDuringDelayDoesNotSendRemainingCases() throws Exception {
    long request = imported("curl " + base + "/echo -H 'X-Test: value'");
    var created = apiRun(request, selection(2));
    String path = "/api/test-runs/" + id(created) + "/";
    long deadline = System.nanoTime() + 3_000_000_000L;
    while (times.isEmpty() && System.nanoTime() < deadline) Thread.sleep(5);
    postJson(path + "stop/", obj(), 200);
    await(path, "stopped");
    assertEquals(1, times.size());
  }

  @Test
  void rateLimitRetryIsIndependentOfPacing() throws Exception {
    long request = imported("curl " + base + "/limited");
    var run = apiRun(request, obj());
    var result = await("/api/test-runs/" + id(run) + "/", "completed");
    var c = rows(result.get("test_cases")).getFirst();
    assertEquals(2, number(c.get("rate_limit_retries"), 0));
    assertEquals(200, number(c.get("status_code"), 0));
    assertEquals(3, times.size());
  }

  @Test
  void chainSubstitutionAndPerCaseRefresh() throws Exception {
    var chain = postJson("/api/chains/chains/", obj("name", "Login chain"), 201);
    String path = "/api/chains/chains/" + id(chain) + "/";
    postJson(
        path + "steps/",
        obj(
            "raw_curl",
            "curl " + base + "/login",
            "refresh_mode",
            "per_test",
            "extract_rules",
            obj("token", "body.token")),
        201);
    postJson(
        path + "steps/",
        obj("raw_curl", "curl " + base + "/echo -H 'Authorization: {{token}}' -H 'X-Test: value'"),
        201);
    var created = postJson(path + "runs/", selection(.04), 201);
    var run = await("/api/chains/runs/" + id(created) + "/", "completed");
    assertEquals(3, rows(run.get("test_cases")).size());
    assertEquals(6, received.size());
    assertTrue(received.get(1).contains("fresh-token"));
    assertTrue(received.get(3).contains("fresh-token"));
    assertTrue(received.get(5).contains("fresh-token"));
    assertEquals(1, rows(run.get("step_results")).size());
    assertEquals(
        "fresh-token",
        map(rows(run.get("test_cases")).getFirst().get("context_snapshot")).get("token"));
    assertTrue(
        (times.get(2) - times.get(1)) / 1e6 >= 30, "Delay must happen before per-test setup.");
  }

  @Test
  void expiringCredentialsPauseResumeAndRetainDelay() throws Exception {
    var run = postJson("/api/credential-tests/runs/", credentialPayload("stale"), 201);
    String path = "/api/credential-tests/runs/" + id(run) + "/";
    var paused = await(path, "paused_awaiting_credentials");
    assertEquals(
        0,
        rows(paused.get("test_cases")).stream().filter(c -> c.get("executed_at") != null).count());
    postJson(path + "resume/", obj("current_values", obj("wrong", "value")), 400);
    postJson(path + "resume/", obj("current_values", obj("Authorization", "fresh-token")), 200);
    var complete = await(path, "completed");
    assertEquals(.04, number(complete.get("delay_seconds"), 0));
    assertEquals(1, number(complete.get("pause_count"), 0));
    assertEquals(
        3,
        rows(complete.get("test_cases")).stream()
            .filter(c -> c.get("executed_at") != null)
            .count());
  }

  @Test
  void manualCasesAndMergedExcel() throws Exception {
    var suite = postJson("/api/manual-tests/suites/", obj("name", "Regression"), 201);
    String path = "/api/manual-tests/suites/" + id(suite) + "/";
    postJson(path + "cases/", obj(), 400);
    var c = postJson(path + "cases/", obj("name", "Health", "environment", "test"), 201);
    for (int i = 0; i < 2; i++)
      postJson(
          "/api/manual-tests/cases/" + id(c) + "/steps/",
          obj(
              "description",
              "Step " + i,
              "test_data",
              "input",
              "expected_result",
              "healthy",
              "actual_result",
              "healthy"),
          201);
    var details = getJson(path);
    assertEquals(2, rows(rows(details.get("test_cases")).getFirst().get("steps")).size());
    Path file = temp.resolve("manual.xlsx");
    var response = postJson(path + "export/", obj("excel_path", file.toString()), 200);
    assertEquals(2, number(response.get("exported_step_count"), 0));
    try (var wb = new XSSFWorkbook(Files.newInputStream(file))) {
      assertEquals("healthy", wb.getSheetAt(0).getRow(1).getCell(8).getStringCellValue());
      assertTrue(wb.getSheetAt(0).getNumMergedRegions() > 0);
    }
  }

  @Test
  void loadCsvAggregatesIndependentMetricsAndDuplicateRejection() throws Exception {
    var plan = postJson("/api/load-tests/plans/", obj("name", "Load", "api_name", "Health"), 201);
    var test =
        postJson(
            "/api/load-tests/plans/" + id(plan) + "/tests/",
            obj("name", "Steady", "planned_duration_minutes", 1, "planned_tps", 10),
            201);
    var csv =
        new MockMultipartFile(
            "jmeter_csv",
            "results.csv",
            "text/csv",
            "timeStamp,elapsed,success\n1000,10,true\n2000,30,false\n3000,20,true\n"
                .getBytes(StandardCharsets.UTF_8));
    var metrics =
        new MockMultipartFile(
            "server_metrics_csv",
            "metrics.csv",
            "text/csv",
            "Timestamp,CPU_Usage_Percent,RAM_USAGE_PERCENT\n800000,20,40\n800001,30,50\n"
                .getBytes(StandardCharsets.UTF_8));
    String path = "/api/load-tests/tests/" + id(test) + "/record/";
    var result =
        map(
            read(
                mvc.perform(multipart(path).file(csv).file(metrics))
                    .andExpect(status().isCreated())
                    .andReturn()
                    .getResponse()
                    .getContentAsString()));
    var data = map(result.get("result"));
    assertEquals(3, number(data.get("sample_count"), 0));
    assertEquals(20, number(data.get("avg_response_time_ms"), 0));
    assertEquals(29, number(data.get("p95_response_time_ms"), 0));
    assertFalse(rows(data.get("cpu_ram_series")).isEmpty());
    mvc.perform(multipart(path).file(csv)).andExpect(status().isBadRequest());
    assertEquals(
        "recorded",
        rows(getJson("/api/load-tests/plans/" + id(plan) + "/").get("tests"))
            .getFirst()
            .get("status"));
  }

  @Test
  void malformedCsvRejected() throws Exception {
    var plan = postJson("/api/load-tests/plans/", obj("name", "Bad CSV"), 201);
    var test =
        postJson(
            "/api/load-tests/plans/" + id(plan) + "/tests/",
            obj("name", "t", "planned_duration_minutes", 1, "planned_tps", 1),
            201);
    mvc.perform(
            multipart("/api/load-tests/tests/" + id(test) + "/record/")
                .file(
                    new MockMultipartFile(
                        "jmeter_csv",
                        "bad.csv",
                        "text/csv",
                        "wrong,columns\n1,2".getBytes(StandardCharsets.UTF_8))))
        .andExpect(status().isBadRequest());
  }

  Path plainReport() throws Exception {
    Path dir = temp.resolve("reports");
    Files.createDirectories(dir);
    var scenario =
        obj(
            "name",
            "Health",
            "steps",
            List.of(
                obj(
                    "keyword",
                    "method",
                    "text",
                    "get",
                    "logSegments",
                    List.of(
                        obj(
                            "text",
                            "request:\n"
                                + "1 > GET http://example.com/health\n\n"
                                + "response time in milliseconds: 1\n"
                                + "1 < 200 GET http://example.com/health\n"
                                + "1 < Content-Type: text/plain\n\n"
                                + "healthy\n"
                                + "second line\n")))));
    Files.writeString(
        dir.resolve("health.html"),
        "<script id=\"karate-data\" type=\"application/json\">"
            + write(obj("name", "Feature", "scenarios", List.of(scenario)))
            + "</script>");
    return dir;
  }

  @Test
  void karatePlainTextPreservedInBothResultColumns() throws Exception {
    Path dir = plainReport(), file = temp.resolve("karate.xlsx");
    var job =
        postJson(
            "/api/karate/jobs/",
            obj("reports_dir", dir.toString(), "excel_path", file.toString()),
            201);
    await("/api/karate/jobs/" + id(job) + "/", "completed");
    try (var wb = new XSSFWorkbook(Files.newInputStream(file))) {
      for (int col : new int[] {8, 9})
        assertEquals(
            "Response Code: 200\nResponse Body:\nhealthy\nsecond line",
            wb.getSheetAt(0).getRow(1).getCell(col).getStringCellValue());
    }
  }

  @Test
  void existingKarateFixtureAndNestedCallReports() throws Exception {
    Path fixtures = Path.of("../backend/karate_tests/tests/fixtures").toAbsolutePath();
    Path output = temp.resolve("fixture.xlsx");
    var job =
        postJson(
            "/api/karate/jobs/",
            obj("reports_dir", fixtures.toString(), "excel_path", output.toString()),
            201);
    var complete = await("/api/karate/jobs/" + id(job) + "/", "completed");
    assertTrue(number(complete.get("step_count"), 0) >= 5);
    assertTrue(number(complete.get("feature_count"), 0) >= 2);
    assertFalse(((List<?>) complete.get("warnings")).isEmpty());
  }

  @Test
  void aiEnhancementThroughLocalOllamaContract() throws Exception {
    Path dir = plainReport(), file = temp.resolve("ai.xlsx");
    var job =
        postJson(
            "/api/karate-ai/jobs/",
            obj(
                "reports_dir",
                dir.toString(),
                "excel_path",
                file.toString(),
                "ollama_base_url",
                base,
                "ollama_model",
                "test"),
            201);
    var complete = await("/api/karate-ai/jobs/" + id(job) + "/", "completed");
    assertEquals(1, number(complete.get("ai_enhanced_scenario_count"), 0));
    try (var wb = new XSSFWorkbook(Files.newInputStream(file))) {
      assertEquals(
          "Check service health", wb.getSheetAt(0).getRow(1).getCell(6).getStringCellValue());
      assertEquals(
          "Service is healthy", wb.getSheetAt(0).getRow(1).getCell(8).getStringCellValue());
    }
  }

  @Test
  void unavailableOllamaFallsBackWithWarning() throws Exception {
    Path dir = plainReport(), file = temp.resolve("fallback.xlsx");
    var job =
        postJson(
            "/api/karate-ai/jobs/",
            obj(
                "reports_dir",
                dir.toString(),
                "excel_path",
                file.toString(),
                "ollama_base_url",
                base + "/not-ollama",
                "ollama_model",
                "test"),
            201);
    var complete = await("/api/karate-ai/jobs/" + id(job) + "/", "completed");
    assertEquals(0, number(complete.get("ai_enhanced_scenario_count"), 0));
    assertFalse(((List<?>) complete.get("warnings")).isEmpty());
  }

  @Test
  void logsMultilineFiltersAndPagination() throws Exception {
    Files.writeString(
        temp.resolve("application.log"),
        "2026-11-15 10:00:00.000 INFO 12 --- [main] example.App : incoming request\n"
            + "continued\n"
            + "2026-11-15 10:00:01.000 ERROR 12 --- [worker] example.Api : response status 500\n"
            + "stack trace\n");
    var job = postJson("/api/logs/jobs/", obj("logs_dir", temp.toString()), 201);
    var complete = await("/api/logs/jobs/" + id(job) + "/", "completed");
    assertEquals(2, number(complete.get("entry_count"), 0));
    var entries =
        getJson("/api/logs/jobs/" + id(job) + "/entries/?level=ERROR&page_size=1&search=stack");
    assertEquals(1, number(entries.get("count"), 0));
    assertTrue(str(rows(entries.get("results")).getFirst(), "message").contains("stack trace"));
    assertEquals(
        1,
        number(getJson("/api/logs/jobs/" + id(job) + "/entries/?filter=request").get("count"), 0));
  }

  @Test
  void customLog4jPattern() throws Exception {
    Path xml = temp.resolve("log4j.xml");
    Files.writeString(
        xml,
        "<Configuration><Appenders><Console><PatternLayout pattern=\"%d{yyyy-MM-dd HH:mm:ss.SSS}"
            + " [%t] %-5p %c - %m%n\"/></Console></Appenders></Configuration>");
    Files.writeString(
        temp.resolve("custom.log"),
        "2026-11-15 10:00:00.000 [worker] ERROR example.Api - broken\n");
    var job =
        postJson(
            "/api/logs/jobs/",
            obj("logs_dir", temp.toString(), "log4j_xml_path", xml.toString()),
            201);
    var complete = await("/api/logs/jobs/" + id(job) + "/", "completed");
    assertEquals("log4j_xml", complete.get("pattern_source"));
    var entry = rows(getJson("/api/logs/jobs/" + id(job) + "/entries/").get("results")).getFirst();
    assertEquals("ERROR", entry.get("level"));
    assertEquals("example.Api", entry.get("logger"));
  }

  @Test
  void jmeterProcessAndReportFiles() throws Exception {
    Path script = temp.resolve("jmeter"), output = temp.resolve("dashboard");
    Files.writeString(
        script,
        "#!/bin/sh\n"
            + "mkdir -p \"$4/assets\"\n"
            + "printf '<html>Report</html>' > \"$4/index.html\"\n"
            + "printf 'body{}' > \"$4/assets/style.css\"\n");
    assertTrue(script.toFile().setExecutable(true));
    var upload =
        new MockMultipartFile(
            "csv_file",
            "results.csv",
            "text/csv",
            "timeStamp,elapsed,success\n1,10,true".getBytes(StandardCharsets.UTF_8));
    var job =
        map(
            read(
                mvc.perform(
                        multipart("/api/jmeter/jobs/")
                            .file(upload)
                            .param("jmeter_bin", script.toString())
                            .param("output_dir", output.toString()))
                    .andExpect(status().isCreated())
                    .andReturn()
                    .getResponse()
                    .getContentAsString()));
    await("/api/jmeter/jobs/" + id(job) + "/", "completed");
    mvc.perform(get("/api/jmeter/jobs/" + id(job) + "/report/"))
        .andExpect(status().isOk())
        .andExpect(content().string("<html>Report</html>"));
    mvc.perform(get("/api/jmeter/jobs/" + id(job) + "/report/assets/style.css"))
        .andExpect(status().isOk())
        .andExpect(content().string("body{}"));
    mvc.perform(get("/api/jmeter/jobs/" + id(job) + "/report/%2e%2e/secret"))
        .andExpect(status().isNotFound());
  }

  @Test
  void persistenceAndRestartRecovery() {
    var doc = store.create("suite", null, obj("name", "Persistent"));
    var reloaded = new DocumentStore(jdbc);
    assertEquals("Persistent", reloaded.get("suite", id(doc)).get("name"));
    var abandoned = store.create("karate", null, obj("status", "running"));
    jobs.recover();
    assertEquals("failed", store.get("karate", id(abandoned)).get("status"));
  }
}
