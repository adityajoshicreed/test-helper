package com.qahelper;

import static com.qahelper.Json.*;

import jakarta.servlet.http.HttpServletRequest;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api")
class ReportController {
  private final DocumentStore store;
  private final Jobs jobs;
  private final KarateService karate;

  ReportController(DocumentStore store, Jobs jobs, KarateService karate) {
    this.store = store;
    this.jobs = jobs;
    this.karate = karate;
  }

  @GetMapping("/{kind:karate|karate-ai|jmeter}/jobs/")
  List<Map<String, Object>> list(@PathVariable String kind) {
    return store.list(kind);
  }

  @GetMapping("/{kind:karate|karate-ai|jmeter}/jobs/{id}/")
  Map<String, Object> get(@PathVariable String kind, @PathVariable long id) {
    return store.get(kind, id);
  }

  @PostMapping("/{kind:karate|karate-ai}/jobs/")
  @ResponseStatus(HttpStatus.CREATED)
  Map<String, Object> create(@PathVariable String kind, @RequestBody Map<String, Object> body) {
    return karate.create(kind, body);
  }

  @PostMapping("/jmeter/jobs/")
  @ResponseStatus(HttpStatus.CREATED)
  Map<String, Object> jmeter(
      @RequestParam("csv_file") MultipartFile file,
      @RequestParam(defaultValue = "") String output_dir,
      @RequestParam(defaultValue = "") String jmeter_bin) {
    String executable = resolve(jmeter_bin.isBlank() ? "jmeter" : jmeter_bin);
    try {
      Path uploads = Path.of("data", "jmeter_uploads").toAbsolutePath();
      Files.createDirectories(uploads);
      Path csv = Files.createTempFile(uploads, "upload-", ".csv");
      Path output =
          output_dir.isBlank()
              ? uploads.resolve(UUID.randomUUID().toString())
              : Path.of(output_dir);
      if (!output.isAbsolute()) throw ApiError.bad("Output directory must be absolute.");
      if (Files.exists(output)) {
        if (!Files.isDirectory(output)) throw ApiError.bad("Output path must be a directory.");
        try (var paths = Files.list(output)) {
          if (paths.findAny().isPresent()) throw ApiError.bad("Output directory must be empty.");
        }
      }
      file.transferTo(csv);
      var job =
          store.create(
              "jmeter",
              null,
              obj(
                  "csv_filename",
                  file.getOriginalFilename(),
                  "output_dir",
                  output.toString(),
                  "jmeter_bin",
                  executable,
                  "command",
                  "",
                  "status",
                  "running",
                  "return_code",
                  null,
                  "stdout",
                  "",
                  "stderr",
                  "",
                  "report_index_path",
                  "",
                  "error",
                  "",
                  "completed_at",
                  null));
      jobs.submit("jmeter", id(job), () -> runJmeter(id(job), csv, output, executable));
      return store.get("jmeter", id(job));
    } catch (IOException e) {
      throw ApiError.bad("Could not save upload: " + e.getMessage());
    }
  }

  private String resolve(String input) {
    if (input.contains("/")) {
      Path p = Path.of(input);
      if (Files.isRegularFile(p) && Files.isExecutable(p)) return p.toAbsolutePath().toString();
    } else
      for (String dir : System.getenv().getOrDefault("PATH", "").split(File.pathSeparator)) {
        Path p = Path.of(dir, input);
        if (Files.isRegularFile(p) && Files.isExecutable(p)) return p.toString();
      }
    throw ApiError.bad(
        "JMeter binary not found or not executable. Provide jmeter_bin or install jmeter on PATH.");
  }

  private void runJmeter(long id, Path csv, Path output, String binary) {
    Process process = null;
    try {
      var command = List.of(binary, "-g", csv.toString(), "-o", output.toString());
      store.update("jmeter", id, d -> d.put("command", String.join(" ", command)));
      Path stdout = Files.createTempFile(csv.getParent(), "stdout-", ".log"),
          stderr = Files.createTempFile(csv.getParent(), "stderr-", ".log");
      try {
        process =
            new ProcessBuilder(command)
                .redirectOutput(stdout.toFile())
                .redirectError(stderr.toFile())
                .start();
        if (!process.waitFor(600, TimeUnit.SECONDS)) {
          process.destroyForcibly();
          throw ApiError.bad("JMeter report generation timed out after 600 seconds.");
        }
        int code = process.exitValue();
        String out = Files.readString(stdout), err = Files.readString(stderr);
        boolean exists = Files.isRegularFile(output.resolve("index.html"));
        store.update(
            "jmeter",
            id,
            d -> {
              d.put("return_code", code);
              d.put("stdout", out);
              d.put("stderr", err);
              d.put("report_index_path", exists ? output.resolve("index.html").toString() : "");
              d.put("status", code == 0 && exists ? "completed" : "failed");
              d.put(
                  "error",
                  code == 0 && exists
                      ? ""
                      : "JMeter did not generate a report (exit " + code + ").");
              d.put("completed_at", now());
            });
      } finally {
        Files.deleteIfExists(stdout);
        Files.deleteIfExists(stderr);
      }
    } catch (Exception e) {
      jobs.fail("jmeter", id, e.getMessage());
    } finally {
      if (process != null && process.isAlive()) process.destroyForcibly();
    }
  }

  @GetMapping({"/jmeter/jobs/{id}/report/", "/jmeter/jobs/{id}/report/{*subpath}"})
  ResponseEntity<FileSystemResource> report(@PathVariable long id, HttpServletRequest request) {
    var job = store.get("jmeter", id);
    if (!"completed".equals(job.get("status"))) throw ApiError.missing();
    try {
      Path root = Path.of(str(job, "output_dir")).toRealPath();
      String prefix = "/api/jmeter/jobs/" + id + "/report/";
      String sub = request.getRequestURI().substring(prefix.length());
      sub = java.net.URLDecoder.decode(sub, java.nio.charset.StandardCharsets.UTF_8);
      Path file = root.resolve(sub.isEmpty() ? "index.html" : sub).normalize();
      if (!file.startsWith(root)
          || !Files.isRegularFile(file)
          || !file.toRealPath().startsWith(root)) throw ApiError.missing();
      String type = Files.probeContentType(file);
      return ResponseEntity.ok()
          .contentType(
              type == null ? MediaType.APPLICATION_OCTET_STREAM : MediaType.parseMediaType(type))
          .body(new FileSystemResource(file));
    } catch (IOException e) {
      throw ApiError.missing();
    }
  }
}
