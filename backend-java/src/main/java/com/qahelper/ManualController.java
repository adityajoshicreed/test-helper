package com.qahelper;

import static com.qahelper.Json.*;

import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/manual-tests")
class ManualController {
  private final DocumentStore store;
  private final ExcelService excel;

  ManualController(DocumentStore store, ExcelService excel) {
    this.store = store;
    this.excel = excel;
  }

  @GetMapping("/suites/")
  List<Map<String, Object>> suites() {
    return store.list("suite").stream()
        .map(
            s -> {
              var cases = store.children("manual_case", id(s));
              s.put("test_case_count", cases.size());
              s.put(
                  "step_count",
                  cases.stream().mapToInt(c -> store.children("manual_step", id(c)).size()).sum());
              return s;
            })
        .toList();
  }

  @PostMapping("/suites/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> create(@RequestBody Map<String, Object> b) {
    var s = store.create("suite", null, obj("name", str(b, "name").strip()));
    s.put("test_cases", List.of());
    return s;
  }

  @GetMapping("/suites/{id}/")
  Map<String, Object> suite(@PathVariable long id) {
    var s = store.get("suite", id);
    s.put(
        "test_cases",
        store.children("manual_case", id).stream()
            .map(
                c -> {
                  c.put("steps", store.children("manual_step", id(c)));
                  return c;
                })
            .toList());
    return s;
  }

  @PostMapping("/suites/{id}/cases/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> addCase(@PathVariable long id, @RequestBody Map<String, Object> b) {
    synchronized (store) {
      store.get("suite", id);
      var c =
          obj(
              "name",
              required(b, "name"),
              "description",
              str(b, "description").strip(),
              "order",
              store.children("manual_case", id).size() + 1);
      for (String key : ExcelService.META) c.put(key, str(b, key).strip());
      var saved = store.create("manual_case", id, c);
      saved.put("steps", List.of());
      return saved;
    }
  }

  @PostMapping("/cases/{id}/steps/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> addStep(@PathVariable long id, @RequestBody Map<String, Object> b) {
    synchronized (store) {
      store.get("manual_case", id);
      var step = obj();
      for (String key : List.of("description", "test_data", "expected_result", "actual_result"))
        step.put(key, str(b, key).strip());
      if (step.values().stream().allMatch(v -> text(v).isBlank()))
        throw ApiError.bad("Provide at least one step field.");
      step.put("order", store.children("manual_step", id).size() + 1);
      return store.create("manual_step", id, step);
    }
  }

  @PostMapping("/suites/{id}/export/")
  Map<String, Object> export(@PathVariable long id, @RequestBody Map<String, Object> b) {
    var cases = rows(suite(id).get("test_cases"));
    if (cases.isEmpty()) throw ApiError.bad("Add at least one test case before exporting.");
    String path = excel.path(b);
    return obj(
        "excel_path",
        path,
        "exported_case_count",
        cases.size(),
        "exported_step_count",
        excel.write(cases, path));
  }
}
