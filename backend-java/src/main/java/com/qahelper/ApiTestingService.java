package com.qahelper;

import static com.qahelper.Json.*;

import java.util.*;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

@Service
class ApiTestingService {
  private final DocumentStore store;
  private final CurlEngine curl;
  private final HttpExecutor http;
  private final Jobs jobs;

  ApiTestingService(DocumentStore store, CurlEngine curl, HttpExecutor http, Jobs jobs) {
    this.store = store;
    this.curl = curl;
    this.http = http;
    this.jobs = jobs;
  }

  Map<String, Object> importCurl(Map<String, Object> body) {
    return curl.decorate(store.create("request", null, curl.parse(required(body, "curl"))));
  }

  Map<String, Object> request(long id) {
    return curl.decorate(store.get("request", id));
  }

  List<Map<String, Object>> requests() {
    return store.list("request");
  }

  Map<String, Object> preview(Map<String, Object> body) {
    return curl.decorate(curl.parse(required(body, "raw_curl")));
  }

  Map<String, Object> chain(long id) {
    var c = store.get("chain", id);
    c.put("steps", store.children("chain_step", id).stream().map(curl::decorate).toList());
    return c;
  }

  List<Map<String, Object>> chains() {
    return store.list("chain").stream()
        .map(
            c -> {
              c.put("step_count", store.children("chain_step", id(c)).size());
              return c;
            })
        .toList();
  }

  Map<String, Object> createChain(Map<String, Object> b) {
    var c = store.create("chain", null, obj("name", str(b, "name")));
    c.put("steps", List.of());
    return c;
  }

  Map<String, Object> addStep(long id, Map<String, Object> b) {
    synchronized (store) {
      store.get("chain", id);
      var s = curl.parse(required(b, "raw_curl"));
      s.put("order", store.children("chain_step", id).size() + 1);
      s.put(
          "refresh_mode",
          Set.of("once", "per_test").contains(str(b, "refresh_mode"))
              ? b.get("refresh_mode")
              : "once");
      var rules = obj();
      map(b.get("extract_rules"))
          .forEach(
              (k, v) -> {
                if (v instanceof String) rules.put(k, v);
              });
      s.put("extract_rules", rules);
      return curl.decorate(store.create("chain_step", id, s));
    }
  }

  Map<String, Object> selection(Map<String, Object> b) {
    Object delay = b.getOrDefault("delay_seconds", 0);
    if (!(delay instanceof Number n)
        || !Double.isFinite(n.doubleValue())
        || n.doubleValue() < 0
        || n.doubleValue() > 60)
      throw ApiError.bad("\"delay_seconds\" must be a number between 0 and 60.");
    if (b.containsKey("categories") && !(b.get("categories") instanceof List<?>))
      throw ApiError.bad("\"categories\" must be a list.");
    return obj(
        "categories",
        b.getOrDefault("categories", List.of()),
        "header_tests",
        map(b.get("header_tests")),
        "body_field_tests",
        map(b.get("body_field_tests")),
        "verify_ssl",
        !Boolean.FALSE.equals(b.get("verify_ssl")),
        "delay_seconds",
        delay,
        "status",
        "running",
        "stop_requested",
        false,
        "error",
        "",
        "completed_at",
        null);
  }

  Map<String, Object> createRun(String kind, Long parent, Map<String, Object> b) {
    Map<String, Object> source;
    var fields = selection(b);
    if (kind.equals("api_run")) {
      source = store.get("request", parent);
      fields.put("imported_request", source);
    } else if (kind.equals("chain_run")) {
      var chain = chain(parent);
      var steps = rows(chain.get("steps"));
      if (steps.isEmpty()) throw ApiError.bad("Add at least one step before running this chain.");
      source = steps.getLast();
      fields.put(
          "chain",
          obj(
              "id",
              parent,
              "name",
              chain.get("name"),
              "created_at",
              chain.get("created_at"),
              "step_count",
              steps.size()));
      fields.put("setup_steps", steps.subList(0, steps.size() - 1));
      fields.put("step_results", new ArrayList<>());
    } else {
      source = curl.parse(required(b, "raw_curl"));
      fields.putAll(source);
      Object status = b.get("expiration_status_code");
      if (status != null
          && (!(status instanceof Number n)
              || n.doubleValue() != n.intValue()
              || n.intValue() < 100
              || n.intValue() > 599))
        throw ApiError.bad("Expiration status code must be an HTTP status code.");
      String message = str(b, "expiration_message_contains");
      if (status == null && message.isBlank())
        throw ApiError.bad("Provide an expiration status code, a message to look for, or both.");
      var creds = rows(b.get("credential_fields"));
      var values = map(b.get("current_values"));
      if (creds.isEmpty()) throw ApiError.bad("Mark at least one expiring credential field.");
      for (var f : creds) {
        String key = str(f, "key"), location = str(f, "location");
        if (!Set.of("header", "body").contains(location)
            || key.isEmpty()
            || !values.containsKey(key))
          throw ApiError.bad("Provide a current value for each credential field.");
        if (location.equals("header") && !map(source.get("headers")).containsKey(key))
          throw ApiError.bad("Credential header does not exist: " + key);
        if (location.equals("body") && pathMissing(source.get("body"), key))
          throw ApiError.bad("Credential body field does not exist: " + key);
      }
      fields.put("credential_fields", creds);
      fields.put("current_values", values);
      fields.put("expiration_status_code", status);
      fields.put("expiration_message_contains", message);
      fields.put("pause_count", 0);
      fields.put("pause_reason", "");
    }
    var generated = curl.generate(source, fields);
    var run = store.create(kind, parent, fields);
    long id = id(run);
    for (var c : generated) store.create(kind + "_case", id, c);
    jobs.submit(kind, id, () -> execute(kind, id));
    return detail(kind, id);
  }

  private boolean pathMissing(Object body, String path) {
    // Null itself is a valid field value; use mutation of a clone to check existence.
    return !CurlEngine.change(cloneValue(body), path, null, false);
  }

  Map<String, Object> detail(String kind, long id) {
    var r = store.get(kind, id);
    r.remove("setup_steps");
    r.put("test_cases", store.children(kind + "_case", id));
    return r;
  }

  List<Map<String, Object>> list(String kind) {
    return store.list(kind).stream()
        .map(
            r -> {
              r.remove("setup_steps");
              return r;
            })
        .toList();
  }

  Map<String, Object> stop(long id) {
    store.update(
        "api_run",
        id,
        r -> {
          if (!str(r, "status").equals("running")) throw ApiError.bad("Run is not running.");
          r.put("stop_requested", true);
        });
    return detail("api_run", id);
  }

  Map<String, Object> resume(long id, Map<String, Object> body) {
    store.update(
        "credential_run",
        id,
        r -> {
          if (!str(r, "status").equals("paused_awaiting_credentials"))
            throw ApiError.bad("Run is not paused.");
          var values = map(body.get("current_values"));
          for (var f : rows(r.get("credential_fields")))
            if (!values.containsKey(str(f, "key")))
              throw ApiError.bad("Provide a fresh value for each credential field.");
          r.put("current_values", values);
          r.put("status", "running");
          r.put("pause_reason", "");
        });
    jobs.submit("credential_run", id, () -> execute("credential_run", id));
    return detail("credential_run", id);
  }

  private void execute(String kind, long id) {
    var run = store.get(kind, id);
    var context = obj();
    if (kind.equals("chain_run"))
      for (var step : rows(run.get("setup_steps")))
        if ("once".equals(step.get("refresh_mode"))) setup(id, run, step, context);
    boolean first = true;
    for (var c : store.children(kind + "_case", id)) {
      if (c.get("executed_at") != null) continue;
      if (!first && !delay(kind, id, number(run.get("delay_seconds"), 0))) return;
      first = false;
      if (stopped(kind, id)) return;
      var caseContext = copy(context);
      if (kind.equals("chain_run")) {
        try {
          for (var step : rows(run.get("setup_steps")))
            if ("per_test".equals(step.get("refresh_mode"))) setup(id, run, step, caseContext);
        } catch (Exception e) {
          store.update(
              kind + "_case",
              id(c),
              d -> {
                d.put("error", e.getMessage());
                d.put("outcome", "error");
                d.put("executed_at", now());
              });
          continue;
        }
        c = map(substitute(c, caseContext));
        c.put("context_snapshot", caseContext);
      }
      if (kind.equals("credential_run")) {
        var values = map(run.get("current_values"));
        for (var field : rows(run.get("credential_fields"))) {
          String key = str(field, "key");
          if ("header".equals(field.get("location"))
              && map(c.get("request_headers")).containsKey(key))
            map(c.get("request_headers")).put(key, values.get(key));
          else if ("body".equals(field.get("location")) && "json".equals(c.get("body_mode")))
            CurlEngine.change(c.get("request_body"), key, values.get(key), false);
        }
        c.put("credential_values_used", values);
      }
      var result = http.execute(c, !Boolean.FALSE.equals(run.get("verify_ssl")));
      if (kind.equals("credential_run") && expired(run, result)) {
        store.update(
            kind,
            id,
            r -> {
              r.put("status", "paused_awaiting_credentials");
              r.put("pause_count", (int) number(r.get("pause_count"), 0) + 1);
              r.put(
                  "pause_reason",
                  "Response matched your credential expiration signal (status "
                      + result.get("status_code")
                      + ").");
            });
        return;
      }
      c.putAll(result);
      var saved = c;
      store.update(kind + "_case", id(c), d -> d.putAll(saved));
    }
    store.update(
        kind,
        id,
        r -> {
          r.put("status", "completed");
          r.put("completed_at", now());
        });
  }

  private boolean expired(Map<String, Object> run, Map<String, Object> result) {
    return run.get("expiration_status_code") != null
            && number(run.get("expiration_status_code"), -1)
                == number(result.get("status_code"), -2)
        || !str(run, "expiration_message_contains").isEmpty()
            && str(result, "response_body")
                .toLowerCase(Locale.ROOT)
                .contains(str(run, "expiration_message_contains").toLowerCase(Locale.ROOT));
  }

  private boolean stopped(String kind, long id) {
    if (kind.equals("api_run") && Boolean.TRUE.equals(store.get(kind, id).get("stop_requested"))) {
      store.update(
          kind,
          id,
          r -> {
            r.put("status", "stopped");
            r.put("completed_at", now());
          });
      return true;
    }
    return false;
  }

  private boolean delay(String kind, long id, double seconds) {
    long deadline = System.nanoTime() + (long) (seconds * 1_000_000_000L);
    while (System.nanoTime() < deadline) {
      if (stopped(kind, id)) return false;
      Jobs.pause(Math.min(.1, (deadline - System.nanoTime()) / 1e9));
    }
    return true;
  }

  private void setup(
      long id, Map<String, Object> run, Map<String, Object> step, Map<String, Object> context) {
    var c = map(substitute(curl.base(step, "setup", "Setup step"), context));
    var result = http.execute(c, !Boolean.FALSE.equals(run.get("verify_ssl")));
    Object response = null;
    try {
      response = read(str(result, "response_body"));
    } catch (ApiError ignored) {
    }
    var extracted = obj();
    for (var e : map(step.get("extract_rules")).entrySet()) {
      String path = text(e.getValue());
      Object value =
          path.equals("status_code")
              ? result.get("status_code")
              : CurlEngine.valueAt(response, path.startsWith("body.") ? path.substring(5) : path);
      extracted.put(e.getKey(), value);
    }
    context.putAll(extracted);
    var snapshot =
        obj(
            "id",
            id(step),
            "step",
            step,
            "status_code",
            result.get("status_code"),
            "response_body",
            result.get("response_body"),
            "error",
            result.get("error"),
            "executed_at",
            result.get("executed_at"),
            "extracted",
            extracted);
    store.update(
        "chain_run",
        id,
        r -> {
          var results = new ArrayList<>(rows(r.get("step_results")));
          results.removeIf(x -> id(map(x.get("step"))) == id(step));
          results.add(snapshot);
          r.put("step_results", results);
        });
    if (result.get("error") != null)
      throw ApiError.bad("Setup step " + step.get("order") + " failed: " + result.get("error"));
  }

  static Object substitute(Object v, Map<String, Object> context) {
    if (v instanceof String s) {
      var matcher = Pattern.compile("\\{\\{(\\w+)}}", Pattern.UNICODE_CHARACTER_CLASS).matcher(s);
      return matcher.replaceAll(
          m ->
              java.util.regex.Matcher.quoteReplacement(
                  context.containsKey(m.group(1)) ? text(context.get(m.group(1))) : m.group()));
    }
    if (v instanceof Map<?, ?> m) {
      var out = obj();
      m.forEach((k, value) -> out.put(text(k), substitute(value, context)));
      return out;
    }
    if (v instanceof List<?> l) return l.stream().map(x -> substitute(x, context)).toList();
    return v;
  }
}
