package com.qahelper;

import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/logs")
class LogController {
  private final DocumentStore store;
  private final LogService logs;

  LogController(DocumentStore store, LogService logs) {
    this.store = store;
    this.logs = logs;
  }

  @GetMapping("/jobs/")
  List<Map<String, Object>> list() {
    return store.list("logs");
  }

  @PostMapping("/jobs/")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  Map<String, Object> create(@RequestBody Map<String, Object> b) {
    return logs.create(b);
  }

  @GetMapping("/jobs/{id}/")
  Map<String, Object> get(@PathVariable long id) {
    return store.get("logs", id);
  }

  @GetMapping("/jobs/{id}/entries/")
  Map<String, Object> entries(@PathVariable long id, @RequestParam Map<String, String> query) {
    return logs.entries(id, query);
  }
}
