package com.qahelper;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.*;

final class Json {
  static final ObjectMapper MAPPER = new ObjectMapper();

  private Json() {}

  static Map<String, Object> obj(Object... pairs) {
    Map<String, Object> result = new LinkedHashMap<>();
    for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
    return result;
  }

  @SuppressWarnings("unchecked")
  static Map<String, Object> map(Object value) {
    return value instanceof Map<?, ?> ? (Map<String, Object>) value : new LinkedHashMap<>();
  }

  @SuppressWarnings("unchecked")
  static List<Map<String, Object>> rows(Object value) {
    if (!(value instanceof List<?> values)) return new ArrayList<>();
    if (values.stream().anyMatch(v -> !(v instanceof Map<?, ?>)))
      throw ApiError.bad("Expected a list of objects.");
    return (List<Map<String, Object>>) value;
  }

  static String str(Map<String, Object> value, String key) {
    return text(value.get(key));
  }

  static String text(Object v) {
    return v == null ? "" : String.valueOf(v);
  }

  static String now() {
    return Instant.now().toString();
  }

  static long id(Map<String, Object> value) {
    return ((Number) value.get("id")).longValue();
  }

  static double number(Object v, double fallback) {
    return v instanceof Number n ? n.doubleValue() : fallback;
  }

  static String write(Object value) {
    try {
      return MAPPER.writeValueAsString(value);
    } catch (Exception ex) {
      throw new IllegalStateException(ex);
    }
  }

  static Object read(String value) {
    try {
      return MAPPER.readValue(value, Object.class);
    } catch (Exception ex) {
      throw ApiError.bad("Invalid JSON: " + ex.getMessage());
    }
  }

  static Map<String, Object> copy(Map<String, Object> value) {
    return map(read(write(value)));
  }

  static Object cloneValue(Object value) {
    return read(write(value));
  }

  static String required(Map<String, Object> body, String key) {
    if (!(body.get(key) instanceof String s) || s.isBlank())
      throw ApiError.bad("Provide a non-empty \"" + key + "\" string.");
    return s.strip();
  }
}
