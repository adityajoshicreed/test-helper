package com.qahelper;

import static com.qahelper.Json.*;

import jakarta.annotation.PreDestroy;
import java.util.concurrent.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

@Component
class Jobs {
  private final DocumentStore store;
  private final ThreadPoolExecutor executor;

  Jobs(
      DocumentStore store,
      @Value("${qa.job-workers}") int workers,
      @Value("${qa.job-queue}") int queue) {
    this.store = store;
    executor =
        new ThreadPoolExecutor(
            workers, workers, 0, TimeUnit.SECONDS, new ArrayBlockingQueue<>(queue));
  }

  void submit(String kind, long id, Runnable action) {
    try {
      executor.execute(
          () -> {
            try {
              action.run();
            } catch (Exception e) {
              fail(
                  kind, id, e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
            }
          });
    } catch (RejectedExecutionException e) {
      fail(kind, id, "Job queue is full.");
      throw new ApiError(503, "Job queue is full; retry later.");
    }
  }

  void fail(String kind, long id, String reason) {
    store.update(
        kind,
        id,
        d -> {
          d.put("status", "failed");
          d.put("error", reason);
          d.put("completed_at", now());
        });
  }

  @EventListener(ApplicationReadyEvent.class)
  void recover() {
    for (String kind :
        new String[] {
          "api_run", "chain_run", "credential_run", "karate", "karate-ai", "jmeter", "logs"
        })
      for (var d : store.list(kind))
        if ("running".equals(d.get("status")) || "pending".equals(d.get("status")))
          fail(kind, id(d), "Server restarted before this job completed; start a new run.");
  }

  @PreDestroy
  void shutdown() {
    executor.shutdownNow();
  }

  static void pause(double seconds) {
    try {
      if (seconds > 0) Thread.sleep(Math.round(seconds * 1000));
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("Job interrupted.");
    }
  }
}
