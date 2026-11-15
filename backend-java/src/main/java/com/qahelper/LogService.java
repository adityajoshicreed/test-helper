package com.qahelper;

import static com.qahelper.Json.*;

import java.nio.file.*;
import java.time.*;
import java.time.format.*;
import java.util.*;
import java.util.regex.*;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import org.springframework.stereotype.Service;
import org.w3c.dom.*;

@Service
class LogService {
  private final DocumentStore store;
  private final Jobs jobs;
  private static final Pattern DEFAULT =
      Pattern.compile(
          "^(?<timestamp>\\d{4}-\\d{2}-\\d{2}["
              + " T]\\d{2}:\\d{2}:\\d{2}[.,]\\d{3}(?:Z|[+-]\\d{2}:?\\d{2})?)\\s+(?<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\\s+.*?---\\s+\\[(?<thread>[^]]*)]\\s+(?<logger>.*?)\\s*:\\s?(?<message>.*)$");

  LogService(DocumentStore store, Jobs jobs) {
    this.store = store;
    this.jobs = jobs;
  }

  Map<String, Object> create(Map<String, Object> b) {
    Path dir = KarateService.directory(b, "logs_dir");
    String xml = str(b, "log4j_xml_path").strip();
    if (!xml.isEmpty() && (!Path.of(xml).isAbsolute() || !Files.isRegularFile(Path.of(xml))))
      throw ApiError.bad("log4j_xml_path must be an existing absolute file path.");
    var job =
        store.create(
            "logs",
            null,
            obj(
                "logs_dir",
                dir.toString(),
                "log4j_xml_path",
                xml,
                "pattern_source",
                "",
                "conversion_pattern",
                "",
                "status",
                "running",
                "file_count",
                0,
                "entry_count",
                0,
                "warnings",
                List.of(),
                "error",
                "",
                "completed_at",
                null));
    jobs.submit("logs", id(job), () -> parse(id(job)));
    return store.get("logs", id(job));
  }

  private void parse(long id) {
    var job = store.get("logs", id);
    var warnings = new ArrayList<String>();
    Pattern pattern = DEFAULT;
    String source = "default", conversion = "";
    if (!str(job, "log4j_xml_path").isEmpty()) {
      try {
        conversion = xmlPattern(Path.of(str(job, "log4j_xml_path")));
        if (!conversion.isEmpty()) {
          pattern = compile(conversion);
          source = "log4j_xml";
        } else warnings.add("No conversion pattern found; using Spring Boot default.");
      } catch (Exception e) {
        warnings.add("Cannot use log4j pattern; using Spring Boot default: " + e.getMessage());
        conversion = "";
      }
    }
    List<Path> files;
    try (var paths = Files.walk(Path.of(str(job, "logs_dir")))) {
      files =
          paths
              .filter(Files::isRegularFile)
              .filter(
                  p ->
                      p.getFileName().toString().matches(".*\\.log(?:\\..*)?")
                          && !p.toString().endsWith(".gz"))
              .sorted(
                  Comparator.comparingLong(
                      p -> {
                        try {
                          return Files.getLastModifiedTime(p).toMillis();
                        } catch (Exception e) {
                          return 0L;
                        }
                      }))
              .toList();
    } catch (Exception e) {
      throw ApiError.bad("Could not read logs: " + e.getMessage());
    }
    if (files.isEmpty()) throw ApiError.bad("No .log files found in the folder.");
    var entries = new ArrayList<Map<String, Object>>();
    int seq = 0;
    boolean truncated = false;
    outer:
    for (Path file : files) {
      Map<String, Object> pending = null;
      int lineNumber = 0;
      try (var reader = Files.newBufferedReader(file)) {
        String line;
        while ((line = reader.readLine()) != null) {
          lineNumber++;
          seq++;
          var matcher = pattern.matcher(line);
          if (matcher.matches()) {
            if (pending != null) {
              entries.add(pending);
              pending = null;
            }
            if (entries.size() >= 20000) {
              truncated = true;
              break outer;
            }
            pending =
                obj(
                    "seq",
                    seq,
                    "source_file",
                    file.getFileName().toString(),
                    "line_number",
                    lineNumber,
                    "timestamp",
                    timestamp(group(matcher, "timestamp")),
                    "level",
                    group(matcher, "level").strip().toUpperCase(Locale.ROOT),
                    "thread",
                    group(matcher, "thread").strip(),
                    "logger",
                    group(matcher, "logger").strip(),
                    "message",
                    group(matcher, "message"));
          } else if (pending != null) pending.put("message", str(pending, "message") + "\n" + line);
          else
            pending =
                obj(
                    "seq",
                    seq,
                    "source_file",
                    file.getFileName().toString(),
                    "line_number",
                    lineNumber,
                    "timestamp",
                    null,
                    "level",
                    "",
                    "thread",
                    "",
                    "logger",
                    "",
                    "message",
                    line);
        }
        if (pending != null) entries.add(pending);
      } catch (Exception e) {
        warnings.add("Could not read " + file + ": " + e.getMessage());
      }
    }
    if (truncated) warnings.add("Import capped at 20,000 entries.");
    for (var entry : entries) {
      String msg = str(entry, "message").toLowerCase(Locale.ROOT);
      entry.put(
          "is_request_like",
          Pattern.compile(
                  "\\b(request|incoming|received|GET|POST|PUT|PATCH|DELETE)\\b",
                  Pattern.CASE_INSENSITIVE)
              .matcher(msg)
              .find());
      entry.put(
          "is_response_like",
          Pattern.compile(
                  "\\b(response|outgoing|responded|status)\\b|\\b[1-5]\\d{2}\\b",
                  Pattern.CASE_INSENSITIVE)
              .matcher(msg)
              .find());
      store.create("log_entry", id, entry);
    }
    String finalSource = source, finalConversion = conversion;
    store.update(
        "logs",
        id,
        d -> {
          d.put("pattern_source", finalSource);
          d.put("conversion_pattern", finalConversion);
          d.put("file_count", files.size());
          d.put("entry_count", entries.size());
          d.put("warnings", warnings);
          d.put("status", "completed");
          d.put("completed_at", now());
        });
  }

  static String xmlPattern(Path path) throws Exception {
    var factory = DocumentBuilderFactory.newInstance();
    factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
    factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
    factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
    factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
    factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
    var document = factory.newDocumentBuilder().parse(path.toFile());
    var elements = document.getElementsByTagName("*");
    for (int i = 0; i < elements.getLength(); i++) {
      var e = (Element) elements.item(i);
      if (e.getTagName().endsWith("PatternLayout") && e.hasAttribute("pattern"))
        return e.getAttribute("pattern");
      if (e.getAttribute("name").equalsIgnoreCase("ConversionPattern"))
        return e.getAttribute("value");
      if (e.getTagName().endsWith("ConversionPattern")) return e.getTextContent();
    }
    return "";
  }

  static Pattern compile(String conversion) {
    var token = Pattern.compile("%[-.\\d]*([a-zA-Z]+|%)(?:\\{[^}]*})?").matcher(conversion);
    var out = new StringBuilder("^");
    int last = 0;
    var names = new HashSet<String>();
    while (token.find()) {
      out.append(literal(conversion.substring(last, token.start())));
      String code = token.group(1),
          name =
              switch (code) {
                case "d", "date" -> "timestamp";
                case "p", "level" -> "level";
                case "t", "thread" -> "thread";
                case "c", "logger" -> "logger";
                case "m", "msg", "message" -> "message";
                default -> null;
              };
      if (code.equals("n")) {
      } else if (code.equals("%")) out.append('%');
      else if (name != null && names.add(name))
        out.append("(?<")
            .append(name)
            .append(name.equals("level") ? ">TRACE|DEBUG|INFO|WARN|ERROR|FATAL)" : ">.*?)");
      else out.append(".*?");
      last = token.end();
    }
    out.append(literal(conversion.substring(last))).append("$");
    return Pattern.compile(out.toString());
  }

  private static String literal(String s) {
    var out = new StringBuilder();
    for (String part : s.split("(?<=\\s)|(?=\\s)"))
      if (!part.isEmpty()) out.append(part.isBlank() ? "\\s+" : Pattern.quote(part));
    return out.toString();
  }

  private static String group(Matcher m, String name) {
    try {
      return Optional.ofNullable(m.group(name)).orElse("");
    } catch (IllegalArgumentException e) {
      return "";
    }
  }

  static String timestamp(String s) {
    if (s.isBlank()) return null;
    String value = s.strip().replace(' ', 'T').replace(',', '.');
    try {
      return OffsetDateTime.parse(value).toInstant().toString();
    } catch (Exception ignored) {
    }
    try {
      return LocalDateTime.parse(value).toInstant(ZoneOffset.UTC).toString();
    } catch (Exception ignored) {
      return null;
    }
  }

  Map<String, Object> entries(long id, Map<String, String> query) {
    store.get("logs", id);
    String search = query.getOrDefault("search", "").toLowerCase(Locale.ROOT),
        logger = query.getOrDefault("logger", "").toLowerCase(Locale.ROOT),
        filter = query.getOrDefault("filter", "");
    var levels =
        new HashSet<>(
            Arrays.asList(query.getOrDefault("level", "").toUpperCase(Locale.ROOT).split(",")));
    levels.retainAll(Set.of("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"));
    var entries =
        store.children("log_entry", id).stream()
            .filter(e -> levels.isEmpty() || levels.contains(str(e, "level")))
            .filter(
                e ->
                    (str(e, "message") + " " + str(e, "logger") + " " + str(e, "thread"))
                            .toLowerCase(Locale.ROOT)
                            .contains(search)
                        && str(e, "logger").toLowerCase(Locale.ROOT).contains(logger))
            .filter(e -> !filter.equals("request") || Boolean.TRUE.equals(e.get("is_request_like")))
            .filter(
                e -> !filter.equals("response") || Boolean.TRUE.equals(e.get("is_response_like")))
            .collect(java.util.stream.Collectors.toCollection(ArrayList::new));
    boolean desc = query.getOrDefault("order", "asc").equals("desc");
    Comparator<Map<String, Object>> seq = Comparator.comparingDouble(e -> number(e.get("seq"), 0));
    if (desc) seq = seq.reversed();
    if (query.getOrDefault("sort", "timestamp").equals("seq")) entries.sort(seq);
    else {
      Comparator<String> direction = desc ? Comparator.reverseOrder() : Comparator.naturalOrder();
      entries.sort(
          Comparator.<Map<String, Object>, String>comparing(
                  e -> (String) e.get("timestamp"), Comparator.nullsLast(direction))
              .thenComparing(seq));
    }
    int page = integer(query.get("page"), 1, 1, Integer.MAX_VALUE),
        size = integer(query.get("page_size"), 100, 1, 500);
    int from = (int) Math.min(entries.size(), ((long) page - 1) * size),
        to = Math.min(entries.size(), from + size);
    return obj(
        "count",
        entries.size(),
        "page",
        page,
        "page_size",
        size,
        "total_pages",
        Math.max(1, (entries.size() + size - 1) / size),
        "results",
        entries.subList(from, to));
  }

  private int integer(String value, int fallback, int min, int max) {
    try {
      return Math.max(min, Math.min(max, Integer.parseInt(value)));
    } catch (Exception e) {
      return fallback;
    }
  }
}
