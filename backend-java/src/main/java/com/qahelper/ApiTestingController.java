package com.qahelper;

import static com.qahelper.Json.*;

import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
class ApiTestingController {
  private final ApiTestingService service;
  private final ExcelService excel;

  ApiTestingController(ApiTestingService service, ExcelService excel) {
    this.service = service;
    this.excel = excel;
  }

  @GetMapping({"/health", "/health/"})
  Map<String, Object> health() {
    return obj("status", "ok", "backend", "spring-boot");
  }

  @PostMapping("/import-curl/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> importCurl(@RequestBody Map<String, Object> body) {
    return service.importCurl(body);
  }

  @GetMapping("/imported-requests/")
  List<Map<String, Object>> requests() {
    return service.requests();
  }

  @GetMapping("/imported-requests/{id}/")
  Map<String, Object> request(@PathVariable long id) {
    return service.request(id);
  }

  @PostMapping("/imported-requests/{id}/test-runs/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> run(@PathVariable long id, @RequestBody Map<String, Object> body) {
    return service.createRun("api_run", id, body);
  }

  @GetMapping("/test-runs/")
  List<Map<String, Object>> runs() {
    return service.list("api_run");
  }

  @GetMapping("/test-runs/{id}/")
  Map<String, Object> run(@PathVariable long id) {
    return service.detail("api_run", id);
  }

  @PostMapping("/test-runs/{id}/stop/")
  Map<String, Object> stop(@PathVariable long id) {
    return service.stop(id);
  }

  @PostMapping("/test-runs/{id}/export-excel/")
  Map<String, Object> export(@PathVariable long id, @RequestBody Map<String, Object> body) {
    var run = service.detail("api_run", id);
    if (Set.of("pending", "running").contains(str(run, "status")))
      throw ApiError.bad("Wait for the run to finish or stop before exporting.");
    var cases =
        rows(run.get("test_cases")).stream().filter(c -> c.get("executed_at") != null).toList();
    if (cases.isEmpty()) throw ApiError.bad("No executed test cases to export.");
    var prepared = new ArrayList<Map<String, Object>>();
    for (var c : cases) {
      var entry = copy(body);
      entry.put("name", c.getOrDefault("human_description", c.get("description")));
      entry.put("description", entry.get("name"));
      String result =
          ExcelService.result(
              c.get("status_code"),
              c.get("error") != null ? c.get("error") : c.get("response_body"));
      entry.put(
          "steps",
          List.of(
              obj(
                  "description",
                  "Execute the CURL",
                  "test_data",
                  CurlEngine.curl(c),
                  "expected_result",
                  result,
                  "actual_result",
                  result)));
      prepared.add(entry);
    }
    String path = excel.path(body);
    excel.write(prepared, path);
    return obj("excel_path", path, "exported_case_count", prepared.size());
  }

  @GetMapping("/chains/chains/")
  List<Map<String, Object>> chains() {
    return service.chains();
  }

  @PostMapping("/chains/chains/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> createChain(@RequestBody Map<String, Object> b) {
    return service.createChain(b);
  }

  @GetMapping("/chains/chains/{id}/")
  Map<String, Object> chain(@PathVariable long id) {
    return service.chain(id);
  }

  @PostMapping("/chains/chains/{id}/steps/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> step(@PathVariable long id, @RequestBody Map<String, Object> b) {
    return service.addStep(id, b);
  }

  @PostMapping("/chains/chains/{id}/runs/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> chainRun(@PathVariable long id, @RequestBody Map<String, Object> b) {
    return service.createRun("chain_run", id, b);
  }

  @GetMapping("/chains/runs/")
  List<Map<String, Object>> chainRuns() {
    return service.list("chain_run");
  }

  @GetMapping("/chains/runs/{id}/")
  Map<String, Object> chainRun(@PathVariable long id) {
    return service.detail("chain_run", id);
  }

  @PostMapping("/credential-tests/parse-curl/")
  Map<String, Object> preview(@RequestBody Map<String, Object> b) {
    return service.preview(b);
  }

  @PostMapping("/credential-tests/runs/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> credential(@RequestBody Map<String, Object> b) {
    return service.createRun("credential_run", null, b);
  }

  @GetMapping("/credential-tests/runs/")
  List<Map<String, Object>> credentials() {
    return service.list("credential_run");
  }

  @GetMapping("/credential-tests/runs/{id}/")
  Map<String, Object> credential(@PathVariable long id) {
    return service.detail("credential_run", id);
  }

  @PostMapping("/credential-tests/runs/{id}/resume/")
  Map<String, Object> resume(@PathVariable long id, @RequestBody Map<String, Object> b) {
    return service.resume(id, b);
  }
}
