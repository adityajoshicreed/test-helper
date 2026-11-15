package com.qahelper;

import static com.qahelper.Json.*;

import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.*;
import org.springframework.stereotype.Component;

/** Parses curl as data, never as a shell command, and generates isolated mutation cases. */
@Component
class CurlEngine {
  private static final Pattern DYNAMIC =
      Pattern.compile(
          "req(?:uest)?[-_]?id|correlation[-_]?id|trace[-_]?id|idempotency",
          Pattern.CASE_INSENSITIVE);
  private static final Pattern PATH = Pattern.compile("\\[(\\d+)\\]|\\.?([^.\\[\\]]+)");
  static final List<String> METHODS =
      List.of("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS");

  static List<String> tokens(String input) {
    var result = new ArrayList<String>();
    var word = new StringBuilder();
    char quote = 0;
    boolean started = false;
    for (int i = 0; i < input.length(); i++) {
      char c = input.charAt(i);
      if (c == '\\' && quote != '\'') {
        if (i + 1 >= input.length()) throw ApiError.bad("Incomplete escape in curl command.");
        char next = input.charAt(++i);
        if (next != '\n' && next != '\r') {
          word.append(next);
          started = true;
        }
      } else if (quote != 0) {
        if (c == quote) quote = 0;
        else word.append(c);
        started = true;
      } else if (c == '\'' || c == '"') {
        quote = c;
        started = true;
      } else if (Character.isWhitespace(c)) {
        if (started) {
          result.add(word.toString());
          word.setLength(0);
          started = false;
        }
      } else {
        word.append(c);
        started = true;
      }
    }
    if (quote != 0) throw ApiError.bad("Unclosed quote in curl command.");
    if (started) result.add(word.toString());
    return result;
  }

  Map<String, Object> parse(String raw) {
    if (raw.isBlank()) throw ApiError.bad("Empty curl command.");
    var args = tokens(raw.replace("\\\r\n", " "));
    int start = !args.isEmpty() && args.getFirst().equals("curl") ? 1 : 0;
    String method = null, url = "", urlFlag = "", user = null;
    boolean get = false;
    var bodies = new ArrayList<String>();
    var headers = obj();
    Set<String> ignored =
        Set.of(
            "--connect-timeout",
            "--max-time",
            "-m",
            "--retry",
            "--proxy",
            "-x",
            "--cacert",
            "--cert",
            "-E",
            "--key",
            "--resolve",
            "--interface");
    for (int i = start; i < args.size(); i++) {
      String flag = args.get(i), val = null;
      boolean takes =
          Set.of(
                      "-X",
                      "--request",
                      "-H",
                      "--header",
                      "-d",
                      "--data",
                      "--data-raw",
                      "--data-binary",
                      "--data-ascii",
                      "--data-urlencode",
                      "-u",
                      "--user",
                      "-b",
                      "--cookie",
                      "-A",
                      "--user-agent",
                      "-e",
                      "--referer",
                      "--url")
                  .contains(flag)
              || ignored.contains(flag);
      if (takes) {
        if (++i >= args.size()) throw ApiError.bad("Flag " + flag + " expects a value.");
        val = args.get(i);
      }
      if (ignored.contains(flag)) continue;
      switch (flag) {
        case "-X", "--request" -> method = val.toUpperCase(Locale.ROOT);
        case "-H", "--header" -> {
          int colon = val.indexOf(':');
          if (colon >= 0)
            headers.put(val.substring(0, colon).strip(), val.substring(colon + 1).strip());
        }
        case "-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode" ->
            bodies.add(val);
        case "-u", "--user" -> user = val;
        case "-b", "--cookie" -> headers.putIfAbsent("Cookie", val);
        case "-A", "--user-agent" -> headers.putIfAbsent("User-Agent", val);
        case "-e", "--referer" -> headers.putIfAbsent("Referer", val);
        case "--url" -> urlFlag = val;
        case "-G", "--get" -> get = true;
        case "-F", "--form" -> throw ApiError.bad("Multipart curl requests are not supported.");
        default -> {
          if (!flag.startsWith("-") && url.isEmpty()) url = flag;
        }
      }
    }
    if (!urlFlag.isEmpty()) url = urlFlag;
    if (url.isBlank()) throw ApiError.bad("Could not find a URL in the curl command.");
    if (user != null)
      headers.put(
          "Authorization",
          "Basic " + Base64.getEncoder().encodeToString(user.getBytes(StandardCharsets.UTF_8)));
    Object body = null;
    String bodyRaw = null;
    boolean isJson = false;
    if (!bodies.isEmpty()) {
      String joined = String.join("&", bodies);
      if (get) url += (url.contains("?") ? "&" : "?") + joined;
      else {
        String content =
            headers.entrySet().stream()
                .filter(e -> e.getKey().equalsIgnoreCase("Content-Type"))
                .map(e -> text(e.getValue()))
                .findFirst()
                .orElse("");
        if (content.toLowerCase(Locale.ROOT).contains("json")
            || (content.isEmpty()
                && (joined.strip().startsWith("{") || joined.strip().startsWith("[")))) {
          try {
            body = read(joined);
            isJson = true;
          } catch (ApiError ignoredError) {
            bodyRaw = joined;
          }
        } else bodyRaw = joined;
      }
    }
    if (method == null) method = bodies.isEmpty() || get ? "GET" : "POST";
    return obj(
        "raw_curl",
        raw,
        "method",
        method,
        "url",
        url,
        "headers",
        headers,
        "body",
        body,
        "body_raw",
        bodyRaw,
        "is_json_body",
        isJson);
  }

  Map<String, Object> decorate(Map<String, Object> request) {
    var result = copy(request);
    var fields = new ArrayList<Map<String, Object>>();
    var paths = new LinkedHashMap<String, Object>();
    if (request.get("body") instanceof Map<?, ?>) walk(request.get("body"), "", 0, paths);
    for (var e : paths.entrySet()) {
      var tests = new ArrayList<Map<String, Object>>();
      tests.add(option("body_field_null", "Null"));
      tests.add(option("body_field_missing", "Missing"));
      if (emptyable(e.getValue())) tests.add(option("body_field_empty", "Empty"));
      if (e.getValue() != null) tests.add(option("body_field_wrong_type", "Wrong type"));
      fields.add(obj("field", e.getKey(), "value_type", type(e.getValue()), "tests", tests));
    }
    result.put("body_field_options", fields);
    var headerOptions = new ArrayList<Map<String, Object>>();
    var dynamic = new ArrayList<String>();
    for (String key : map(request.get("headers")).keySet()) {
      headerOptions.add(
          obj(
              "header",
              key,
              "tests",
              List.of(option("header_missing", "Missing"), option("header_empty", "Empty"))));
      if (DYNAMIC.matcher(key).find()) dynamic.add(key);
    }
    result.put("header_field_options", headerOptions);
    result.put("dynamic_headers", dynamic);
    result.put(
        "available_test_categories",
        List.of(
            obj("code", "baseline", "label", "Baseline (unmodified request)", "applicable", true),
            obj(
                "code",
                "body_whole",
                "label",
                "Whole-body mutations",
                "applicable",
                request.get("body") != null || !str(request, "body_raw").isEmpty()),
            obj("code", "http_method", "label", "Alternate HTTP methods", "applicable", true)));
    return result;
  }

  private static Map<String, Object> option(String code, String label) {
    return obj("code", code, "label", label);
  }

  private static boolean emptyable(Object value) {
    return value instanceof String || value instanceof List<?> || value instanceof Map<?, ?>;
  }

  private static String type(Object v) {
    return v == null
        ? "NoneType"
        : v instanceof Map
            ? "dict"
            : v instanceof List
                ? "list"
                : v instanceof Boolean
                    ? "bool"
                    : v instanceof String
                        ? "str"
                        : v instanceof Float || v instanceof Double ? "float" : "int";
  }

  private static void walk(Object v, String prefix, int depth, Map<String, Object> paths) {
    if (depth >= 6) return;
    if (v instanceof Map<?, ?> m)
      for (var e : m.entrySet()) {
        String p = prefix.isEmpty() ? text(e.getKey()) : prefix + "." + e.getKey();
        paths.put(p, e.getValue());
        walk(e.getValue(), p, depth + 1, paths);
      }
    else if (v instanceof List<?> list)
      for (int i = 0; i < Math.min(5, list.size()); i++) {
        String p = prefix + "[" + i + "]";
        paths.put(p, list.get(i));
        walk(list.get(i), p, depth + 1, paths);
      }
  }

  static List<Object> pathTokens(String path) {
    var list = new ArrayList<Object>();
    var m = PATH.matcher(path);
    while (m.find()) list.add(m.group(1) == null ? m.group(2) : Integer.parseInt(m.group(1)));
    return list;
  }

  static Object valueAt(Object body, String path) {
    Object v = body;
    for (Object t : pathTokens(path)) {
      if (t instanceof Integer i && v instanceof List<?> list && i < list.size()) v = list.get(i);
      else if (t instanceof String s && v instanceof Map<?, ?> m) v = m.get(s);
      else return null;
    }
    return v;
  }

  @SuppressWarnings("unchecked")
  static boolean change(Object body, String path, Object value, boolean remove) {
    var tokens = pathTokens(path);
    if (tokens.isEmpty()) return false;
    Object parent = body;
    for (int i = 0; i < tokens.size() - 1; i++) {
      Object t = tokens.get(i);
      if (t instanceof Integer n && parent instanceof List<?> l && n < l.size()) parent = l.get(n);
      else if (t instanceof String s && parent instanceof Map<?, ?> m && m.containsKey(s))
        parent = m.get(s);
      else return false;
    }
    Object last = tokens.getLast();
    if (parent instanceof Map<?, ?> m && last instanceof String s && m.containsKey(s)) {
      if (remove) ((Map<String, Object>) m).remove(s);
      else ((Map<String, Object>) m).put(s, value);
      return true;
    }
    if (parent instanceof List<?> l && last instanceof Integer i && i < l.size()) {
      if (remove) ((List<Object>) l).remove((int) i);
      else ((List<Object>) l).set(i, value);
      return true;
    }
    return false;
  }

  Map<String, Object> base(Map<String, Object> r, String category, String description) {
    var headers = copy(map(r.get("headers")));
    headers.replaceAll((k, v) -> DYNAMIC.matcher(k).find() ? UUID.randomUUID().toString() : v);
    return obj(
        "category",
        category,
        "description",
        description,
        "human_description",
        "Verify API: " + description,
        "request_method",
        r.get("method"),
        "request_url",
        r.get("url"),
        "request_headers",
        headers,
        "request_body",
        cloneValue(r.get("body")),
        "request_body_raw",
        r.get("body_raw"),
        "body_mode",
        Boolean.TRUE.equals(r.get("is_json_body"))
            ? "json"
            : r.get("body_raw") != null ? "raw" : "none",
        "status_code",
        null,
        "response_headers",
        null,
        "response_body",
        null,
        "latency_ms",
        null,
        "error",
        null,
        "outcome",
        null,
        "executed_at",
        null,
        "rate_limit_retries",
        0,
        "rate_limit_wait_seconds",
        0);
  }

  List<Map<String, Object>> generate(Map<String, Object> r, Map<String, Object> selection) {
    var result = new ArrayList<Map<String, Object>>();
    result.add(base(r, "baseline", "Baseline (unmodified request)"));
    var paths = new LinkedHashMap<String, Object>();
    walk(r.get("body"), "", 0, paths);
    for (var e : map(selection.get("body_field_tests")).entrySet()) {
      if (!paths.containsKey(e.getKey()) || !(e.getValue() instanceof List<?> codes)) continue;
      Object original = paths.get(e.getKey());
      for (Object code : codes) {
        String category = text(code);
        Object value;
        switch (category) {
          case "body_field_null", "body_field_missing" -> value = null;
          case "body_field_empty" -> {
            if (!emptyable(original)) continue;
            value =
                original instanceof Map ? obj() : original instanceof List ? new ArrayList<>() : "";
          }
          case "body_field_wrong_type" -> {
            if (original == null) continue;
            value =
                original instanceof String
                    ? 12345
                    : original instanceof Boolean
                        ? "true"
                        : original instanceof Number
                            ? "not-a-number"
                            : original instanceof List ? "not-an-array" : "not-an-object";
          }
          default -> {
            continue;
          }
        }
        var c = base(r, category, category.replace('_', ' ') + ": " + e.getKey());
        if (change(c.get("request_body"), e.getKey(), value, category.equals("body_field_missing")))
          result.add(c);
      }
    }
    for (var e : map(selection.get("header_tests")).entrySet()) {
      if (!map(r.get("headers")).containsKey(e.getKey())
          || !(e.getValue() instanceof List<?> codes)) continue;
      for (Object code : codes) {
        if (!Set.of("header_missing", "header_empty").contains(code)) continue;
        var c = base(r, text(code), text(code).replace('_', ' ') + ": " + e.getKey());
        if (code.equals("header_missing")) map(c.get("request_headers")).remove(e.getKey());
        else map(c.get("request_headers")).put(e.getKey(), "");
        result.add(c);
      }
    }
    Object raw = selection.getOrDefault("categories", List.of());
    if (!(raw instanceof List<?> categories)) throw ApiError.bad("\"categories\" must be a list.");
    if (categories.contains("body_whole") && (r.get("body") != null || r.get("body_raw") != null)) {
      result.add(whole(r, "No body", "none", null, null));
      if (Boolean.TRUE.equals(r.get("is_json_body"))) {
        result.add(whole(r, "Empty object", "json", obj(), null));
        result.add(whole(r, "Null body", "json", null, null));
        if (r.get("body") instanceof Map)
          result.add(
              whole(
                  r,
                  "Array instead of object",
                  "json",
                  List.of("unexpected", "array", "body"),
                  null));
      } else result.add(whole(r, "Empty body", "raw", null, ""));
      result.add(whole(r, "Malformed JSON", "raw", null, "{invalid json,,,"));
    }
    if (categories.contains("http_method"))
      for (String method : METHODS)
        if (!method.equals(r.get("method"))) {
          var c =
              base(
                  r,
                  "http_method",
                  "Send request using " + method + " instead of " + r.get("method"));
          c.put("request_method", method);
          result.add(c);
        }
    return result;
  }

  private Map<String, Object> whole(
      Map<String, Object> r, String label, String mode, Object body, String raw) {
    var c = base(r, "body_whole", label);
    c.put("body_mode", mode);
    c.put("request_body", body);
    c.put("request_body_raw", raw);
    return c;
  }

  static String curl(Map<String, Object> c) {
    StringBuilder s = new StringBuilder("curl -X " + str(c, "request_method"));
    map(c.get("request_headers"))
        .forEach(
            (k, v) -> {
              if (!Set.of("host", "content-length", "connection", "user-agent")
                  .contains(k.toLowerCase(Locale.ROOT)))
                s.append(" -H ").append(quote(k + ": " + v));
            });
    s.append(' ').append(quote(str(c, "request_url")));
    if (!"none".equals(c.get("body_mode")))
      s.append(" -d ")
          .append(
              quote(
                  "json".equals(c.get("body_mode"))
                      ? write(c.get("request_body"))
                      : str(c, "request_body_raw")));
    return s.toString();
  }

  private static String quote(String s) {
    return "'" + s.replace("'", "'\"'\"'") + "'";
  }
}
