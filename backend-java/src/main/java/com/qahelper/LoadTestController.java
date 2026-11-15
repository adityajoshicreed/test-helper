package com.qahelper;

import static com.qahelper.Json.*;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import org.apache.commons.csv.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/load-tests")
class LoadTestController {
  private final DocumentStore store;

  LoadTestController(DocumentStore store) {
    this.store = store;
  }

  @GetMapping("/plans/")
  List<Map<String, Object>> plans() {
    return store.list("plan").stream()
        .map(
            p -> {
              var tests = store.children("planned_test", id(p));
              p.put("test_count", tests.size());
              p.put(
                  "recorded_count",
                  tests.stream().filter(t -> "recorded".equals(t.get("status"))).count());
              return p;
            })
        .toList();
  }

  @PostMapping("/plans/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> create(@RequestBody Map<String, Object> b) {
    var p =
        store.create(
            "plan", null, obj("name", required(b, "name"), "api_name", str(b, "api_name").strip()));
    p.put("tests", List.of());
    return p;
  }

  @GetMapping("/plans/{id}/")
  Map<String, Object> plan(@PathVariable long id) {
    var p = store.get("plan", id);
    p.put("tests", store.children("planned_test", id));
    return p;
  }

  @PostMapping("/plans/{id}/tests/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> add(@PathVariable long id, @RequestBody Map<String, Object> b) {
    synchronized (store) {
      store.get("plan", id);
      double duration = positive(b.get("planned_duration_minutes")),
          tps = positive(b.get("planned_tps"));
      return store.create(
          "planned_test",
          id,
          obj(
              "order",
              store.children("planned_test", id).size() + 1,
              "name",
              required(b, "name"),
              "planned_duration_minutes",
              duration,
              "planned_tps",
              tps,
              "jmeter_csv_filename",
              str(b, "jmeter_csv_filename"),
              "server_metrics_csv_filename",
              str(b, "server_metrics_csv_filename"),
              "status",
              "planned",
              "result",
              null));
    }
  }

  private static double positive(Object o) {
    try {
      double v = Double.parseDouble(text(o));
      if (!Double.isFinite(v) || v <= 0) throw new IllegalArgumentException();
      return v;
    } catch (Exception e) {
      throw ApiError.bad("Planned duration and TPS must be positive finite numbers.");
    }
  }

  @PostMapping("/tests/{id}/record/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> record(
      @PathVariable long id,
      @RequestParam("jmeter_csv") MultipartFile jmeter,
      @RequestParam(value = "server_metrics_csv", required = false) MultipartFile metrics) {
    synchronized (store) {
      var test = store.get("planned_test", id);
      if ("recorded".equals(test.get("status")))
        throw ApiError.bad("This test already has a recorded result; add a new planned test.");
      var samples = parse(jmeter, false);
      var server = metrics == null ? new ArrayList<double[]>() : parse(metrics, true);
      var elapsed = samples.stream().mapToDouble(v -> v[1]).sorted().toArray();
      double start = samples.stream().mapToDouble(v -> v[0]).min().orElseThrow(),
          end = samples.stream().mapToDouble(v -> v[0]).max().orElseThrow(),
          duration = (end - start) / 1000;
      long errors = samples.stream().filter(v -> v[2] == 0).count();
      var result =
          obj(
              "id",
              id,
              "created_at",
              now(),
              "jmeter_csv_filename",
              jmeter.getOriginalFilename(),
              "server_metrics_csv_filename",
              metrics == null ? "" : metrics.getOriginalFilename(),
              "sample_count",
              samples.size(),
              "error_count",
              errors,
              "error_rate_percent",
              round(100.0 * errors / samples.size()),
              "actual_duration_seconds",
              round(duration),
              "actual_tps",
              duration > 0 ? round(samples.size() / duration) : null,
              "avg_response_time_ms",
              round(Arrays.stream(elapsed).average().orElse(0)),
              "min_response_time_ms",
              elapsed[0],
              "max_response_time_ms",
              elapsed[elapsed.length - 1],
              "warnings",
              List.of());
      for (int p : new int[] {50, 90, 95, 99})
        result.put("p" + p + "_response_time_ms", percentile(elapsed, p));
      double width = Math.max(1, Math.ceil(duration / 120));
      var buckets = new TreeMap<Long, List<double[]>>();
      for (var row : samples)
        buckets
            .computeIfAbsent((long) ((row[0] - start) / 1000 / width), k -> new ArrayList<>())
            .add(row);
      var response = new ArrayList<Map<String, Object>>();
      var throughput = new ArrayList<Map<String, Object>>();
      buckets.forEach(
          (index, rows) -> {
            var values = rows.stream().mapToDouble(v -> v[1]).sorted().toArray();
            double t = round3(index * width / 60);
            response.add(
                obj(
                    "t",
                    t,
                    "avg",
                    round(Arrays.stream(values).average().orElse(0)),
                    "p95",
                    round(percentile(values, 95))));
            throughput.add(obj("t", t, "tps", round(rows.size() / width)));
          });
      var cpu = new ArrayList<Map<String, Object>>();
      if (!server.isEmpty()) {
        double min = server.stream().mapToDouble(v -> v[0]).min().orElseThrow(),
            max = server.stream().mapToDouble(v -> v[0]).max().orElseThrow(),
            bucket = Math.max(1, Math.ceil((max - min) / 120));
        var grouped = new TreeMap<Long, List<double[]>>();
        for (var row : server)
          grouped
              .computeIfAbsent((long) ((row[0] - min) / bucket), k -> new ArrayList<>())
              .add(row);
        grouped.forEach(
            (index, rows) ->
                cpu.add(
                    obj(
                        "t",
                        round3(index * bucket / 60),
                        "cpu_percent",
                        round(rows.stream().mapToDouble(v -> v[1]).average().orElse(0)),
                        "ram_percent",
                        round(rows.stream().mapToDouble(v -> v[2]).average().orElse(0)))));
      }
      result.put("response_time_series", response);
      result.put("throughput_series", throughput);
      result.put("cpu_ram_series", cpu);
      return store.update(
          "planned_test",
          id,
          d -> {
            d.put("result", result);
            d.put("status", "recorded");
          });
    }
  }

  private List<double[]> parse(MultipartFile file, boolean metrics) {
    try (var reader = new InputStreamReader(file.getInputStream(), StandardCharsets.UTF_8);
        var parser =
            CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true).get().parse(reader)) {
      var names = parser.getHeaderNames();
      String time = column(names, "timestamp", "time"),
          one = column(names, metrics ? "cpu" : "elapsed"),
          two = column(names, metrics ? "ram" : "success", metrics ? "memory" : "success");
      if (time == null || one == null || two == null)
        throw ApiError.bad(
            "Missing required CSV columns: "
                + (metrics
                    ? "Timestamp, CPU_Usage_Percent, RAM_USAGE_PERCENT"
                    : "timeStamp, elapsed, success"));
      var rows = new ArrayList<double[]>();
      for (var record : parser) {
        if (rows.size() >= 1_000_000) throw ApiError.bad("CSV exceeds 1,000,000 rows.");
        double t = metrics ? timestamp(record.get(time)) : Double.parseDouble(record.get(time));
        double a = Double.parseDouble(record.get(one)),
            b =
                metrics
                    ? Double.parseDouble(record.get(two))
                    : record.get(two).strip().equalsIgnoreCase("true") ? 1 : 0;
        if (!Double.isFinite(t) || !Double.isFinite(a) || !Double.isFinite(b) || a < 0)
          throw ApiError.bad("Invalid number in CSV row " + record.getRecordNumber());
        rows.add(new double[] {t, a, b});
      }
      if (rows.isEmpty()) throw ApiError.bad("CSV has no data rows.");
      return rows;
    } catch (ApiError e) {
      throw e;
    } catch (Exception e) {
      throw ApiError.bad("Could not parse CSV: " + e.getMessage());
    }
  }

  private static String column(List<String> headers, String... needles) {
    for (String needle : needles)
      for (String header : headers)
        if (header.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]", "").contains(needle))
          return header;
    return null;
  }

  private static double timestamp(String s) {
    try {
      double v = Double.parseDouble(s);
      return v > 1e12 ? v / 1000 : v;
    } catch (NumberFormatException e) {
      try {
        return OffsetDateTime.parse(s.replace(' ', 'T')).toInstant().toEpochMilli() / 1000.0;
      } catch (Exception ignored) {
        return LocalDateTime.parse(s.replace(' ', 'T')).toInstant(ZoneOffset.UTC).toEpochMilli()
            / 1000.0;
      }
    }
  }

  static double percentile(double[] sorted, int p) {
    double k = (sorted.length - 1) * p / 100.0;
    int low = (int) Math.floor(k), high = (int) Math.ceil(k);
    return sorted[low] + (sorted[high] - sorted[low]) * (k - low);
  }

  private static double round(double v) {
    return Math.round(v * 100) / 100.0;
  }

  private static double round3(double v) {
    return Math.round(v * 1000) / 1000.0;
  }
}
