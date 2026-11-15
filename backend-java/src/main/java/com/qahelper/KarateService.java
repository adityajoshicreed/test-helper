package com.qahelper;

import static com.qahelper.Json.*;

import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.regex.*;
import org.springframework.stereotype.Service;

@Service
class KarateService {
  private final DocumentStore store;
  private final Jobs jobs;
  private final ExcelService excel;
  private static final Pattern DATA =
      Pattern.compile(
          "<script\\s+id=\"karate-data\"\\s+type=\"application/json\">(.*?)</script>",
          Pattern.DOTALL);

  KarateService(DocumentStore store, Jobs jobs, ExcelService excel) {
    this.store = store;
    this.jobs = jobs;
    this.excel = excel;
  }

  static Path directory(Map<String, Object> b, String key) {
    Path p = Path.of(required(b, key));
    if (!p.isAbsolute() || !Files.isDirectory(p))
      throw ApiError.bad(key + " must be an existing absolute directory.");
    return p;
  }

  Map<String, Object> create(String kind, Map<String, Object> b) {
    Path dir = directory(b, "reports_dir");
    String path = excel.path(b);
    var fields =
        obj(
            "reports_dir",
            dir.toString(),
            "excel_path",
            path,
            "status",
            "running",
            "error",
            "",
            "warnings",
            List.of(),
            "feature_count",
            0,
            "scenario_count",
            0,
            "step_count",
            0,
            "completed_at",
            null);
    for (String k : ExcelService.META) fields.put(k, str(b, k));
    if (kind.equals("karate-ai")) {
      String base = str(b, "ollama_base_url").strip();
      if (base.isEmpty()) base = "http://localhost:11434";
      try {
        URI uri = URI.create(base);
        if (!Set.of("http", "https").contains(uri.getScheme()) || uri.getHost() == null)
          throw new IllegalArgumentException();
      } catch (Exception e) {
        throw ApiError.bad("Ollama base URL must be an HTTP or HTTPS URL.");
      }
      fields.put("ollama_base_url", base.replaceAll("/+$", ""));
      fields.put("ollama_model", required(b, "ollama_model"));
      fields.put("ai_enhanced_scenario_count", 0);
    }
    var job = store.create(kind, null, fields);
    jobs.submit(kind, id(job), () -> generate(kind, id(job)));
    return store.get(kind, id(job));
  }

  void generate(String kind, long id) {
    var job = store.get(kind, id);
    var warnings = new ArrayList<String>();
    var cases = new ArrayList<Map<String, Object>>();
    int features = 0;
    try (var paths = Files.walk(Path.of(str(job, "reports_dir")))) {
      for (Path path :
          paths
              .filter(p -> Files.isRegularFile(p) && p.toString().endsWith(".html"))
              .sorted()
              .toList()) {
        try {
          var matcher = DATA.matcher(Files.readString(path));
          if (!matcher.find()) continue;
          var feature = map(read(matcher.group(1)));
          features++;
          for (var scenario : rows(feature.get("scenarios"))) {
            var steps = new ArrayList<Map<String, Object>>();
            extract(scenario, steps, warnings);
            if (!steps.isEmpty()) {
              var c = copy(job);
              c.put(
                  "name",
                  str(scenario, "name").isEmpty() ? feature.get("name") : scenario.get("name"));
              c.put("description", c.get("name"));
              c.put("steps", steps);
              cases.add(c);
            }
          }
        } catch (Exception e) {
          warnings.add(path + ": " + e.getMessage());
        }
      }
    } catch (Exception e) {
      throw ApiError.bad("Could not read reports: " + e.getMessage());
    }
    if (features == 0 || cases.isEmpty())
      throw ApiError.bad(
          "No Karate feature reports with HTTP calls found under " + job.get("reports_dir"));
    int enhanced = 0;
    for (var c : cases) {
      var steps = rows(c.get("steps"));
      boolean ai = false;
      if (kind.equals("karate-ai")) {
        try {
          enhance(job, c, steps);
          ai = true;
          enhanced++;
        } catch (Exception e) {
          warnings.add(
              "Scenario '"
                  + c.get("name")
                  + "': AI enhancement failed; using default step text ("
                  + e.getMessage()
                  + ").");
        }
      }
      for (var step : steps) {
        String result = ExcelService.result(step.get("status_code"), step.get("response_body"));
        if (!ai || str(step, "description").isBlank()) step.put("description", "Execute the CURL");
        if (!ai || str(step, "expected_result").isBlank()) step.put("expected_result", result);
        step.put("actual_result", result);
        step.put("test_data", step.get("curl"));
      }
    }
    excel.write(cases, str(job, "excel_path"));
    int featureCount = features, enhancedCount = enhanced;
    store.update(
        kind,
        id,
        d -> {
          d.put("feature_count", featureCount);
          d.put("scenario_count", cases.size());
          d.put("step_count", cases.stream().mapToInt(c -> rows(c.get("steps")).size()).sum());
          d.put("warnings", warnings);
          if (kind.equals("karate-ai")) d.put("ai_enhanced_scenario_count", enhancedCount);
          d.put("status", "completed");
          d.put("completed_at", now());
        });
  }

  private void extract(
      Map<String, Object> scenario, List<Map<String, Object>> out, List<String> warnings) {
    for (var step : rows(scenario.get("steps"))) {
      if ("method".equals(step.get("keyword"))) {
        if ("skipped".equals(step.get("status")))
          warnings.add("Skipped step omitted: " + step.get("text"));
        else out.add(parseSegments(rows(step.get("logSegments")), str(step, "text"), warnings));
      }
      if (Boolean.TRUE.equals(step.get("hasCallResults")))
        for (var call : rows(step.get("callResults")))
          for (var nested : rows(call.get("scenarios"))) extract(nested, out, warnings);
    }
  }

  static Map<String, Object> parseSegments(
      List<Map<String, Object>> segments, String fallback, List<String> warnings) {
    var req = new StringBuilder();
    var res = new StringBuilder();
    Object reqBody = null, resBody = null;
    boolean response = false;
    for (var segment : segments) {
      if (segment.get("text") != null) {
        String text = str(segment, "text");
        int index = text.indexOf("response time in milliseconds");
        if (index < 0) {
          var m = Pattern.compile("(?m)^\\d+ < \\d+ ").matcher(text);
          if (m.find()) index = m.start();
        }
        if (index >= 0) {
          if (!response) req.append(text, 0, index);
          res.append(text.substring(index));
          response = true;
        } else if (response) res.append(text);
        else req.append(text);
      } else if (segment.get("code") != null) {
        if (response) resBody = segment.get("code");
        else reqBody = segment.get("code");
      }
    }
    String method = null, url = null, status = null;
    var headers = obj();
    for (String line : req.toString().split("\\R")) {
      var m = Pattern.compile("^\\d+ > (.+)$").matcher(line);
      if (!m.matches()) continue;
      String rest = m.group(1);
      if (method == null) {
        String[] parts = rest.split(" ", 2);
        if (parts.length == 2) {
          method = parts[0];
          url = parts[1];
        }
      } else {
        int colon = rest.indexOf(':');
        if (colon > 0)
          headers.put(rest.substring(0, colon).strip(), rest.substring(colon + 1).strip());
      }
    }
    boolean seen = false, body = false;
    var plain = new StringBuilder();
    for (String line : res.toString().split("(?<=\\n)")) {
      if (body) {
        plain.append(line);
        continue;
      }
      var m = Pattern.compile("^\\d+ < (.+)$").matcher(line.stripTrailing());
      if (m.matches()) {
        if (!seen) {
          status = m.group(1).split(" ", 2)[0];
          seen = true;
        }
      } else if (seen) {
        body = true;
        plain.append(line);
      }
    }
    if (resBody == null) {
      String text = plain.toString().replaceAll("^[\\r\\n]+|[\\r\\n]+$", "");
      if (!text.isEmpty()) resBody = text;
    }
    String command;
    if (method == null || url == null) {
      command = "# Could not reconstruct the request for step: " + fallback;
      warnings.add(command);
    } else
      command =
          CurlEngine.curl(
              obj(
                  "request_method",
                  method,
                  "request_url",
                  url,
                  "request_headers",
                  headers,
                  "request_body_raw",
                  reqBody,
                  "body_mode",
                  reqBody == null ? "none" : "raw"));
    return obj(
        "method",
        method == null ? fallback.toUpperCase(Locale.ROOT) : method,
        "url",
        url,
        "curl",
        command,
        "status_code",
        status,
        "response_body",
        resBody);
  }

  private void enhance(
      Map<String, Object> job, Map<String, Object> c, List<Map<String, Object>> steps)
      throws Exception {
    String prompt =
        "You are a QA analyst. For each HTTP call in scenario '"
            + c.get("name")
            + "', write description and expected_result. Return ONLY JSON"
            + " {\"steps\":[{\"description\":\"...\",\"expected_result\":\"...\"}]} with one entry"
            + " per step in order. Calls: ";
    var calls = new ArrayList<Map<String, Object>>();
    for (var s : steps) {
      String body = str(s, "response_body");
      calls.add(
          obj(
              "method",
              s.get("method"),
              "url",
              s.get("url"),
              "status_code",
              s.get("status_code"),
              "response_body",
              body.substring(0, Math.min(2000, body.length()))));
    }
    try (var client =
        HttpClient.newBuilder()
            .proxy(Network.proxySelector())
            .connectTimeout(Duration.ofSeconds(10))
            .build()) {
      var request =
          HttpRequest.newBuilder(URI.create(str(job, "ollama_base_url") + "/api/generate"))
              .timeout(Duration.ofSeconds(90))
              .header("Content-Type", "application/json")
              .POST(
                  HttpRequest.BodyPublishers.ofString(
                      write(
                          obj(
                              "model",
                              job.get("ollama_model"),
                              "prompt",
                              prompt + write(calls),
                              "stream",
                              false,
                              "format",
                              "json"))))
              .build();
      var response = client.send(request, HttpResponse.BodyHandlers.ofString());
      if (response.statusCode() != 200)
        throw new IllegalStateException("Ollama HTTP " + response.statusCode());
      String raw =
          str(map(read(response.body())), "response")
              .strip()
              .replaceAll("^```[a-zA-Z]*\\s*|\\s*```$", "");
      var entries = rows(map(read(raw)).get("steps"));
      if (entries.size() != steps.size())
        throw new IllegalStateException("Unexpected step count from model.");
      for (int i = 0; i < steps.size(); i++) {
        steps.get(i).put("description", entries.get(i).get("description"));
        steps.get(i).put("expected_result", entries.get(i).get("expected_result"));
      }
    }
  }
}
