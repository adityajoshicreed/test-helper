package com.qahelper;

import static com.qahelper.Json.*;

import java.net.URI;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import org.apache.hc.client5.http.classic.methods.HttpUriRequestBase;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.client5.http.ssl.NoopHostnameVerifier;
import org.apache.hc.client5.http.ssl.SSLConnectionSocketFactoryBuilder;
import org.apache.hc.core5.http.ContentType;
import org.apache.hc.core5.http.io.entity.EntityUtils;
import org.apache.hc.core5.http.io.entity.StringEntity;
import org.apache.hc.core5.ssl.SSLContexts;
import org.apache.hc.core5.util.Timeout;
import org.springframework.stereotype.Component;

@Component
class HttpExecutor {
  Map<String, Object> execute(Map<String, Object> c, boolean verify) {
    var result =
        obj(
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
            "executed_at",
            null,
            "rate_limit_retries",
            0,
            "rate_limit_wait_seconds",
            0.0);
    int retries = 0;
    double waited = 0;
    try {
      var builder =
          HttpClients.custom()
              .setRoutePlanner(
                  new org.apache.hc.client5.http.impl.routing.SystemDefaultRoutePlanner(
                      Network.proxySelector()))
              .disableAutomaticRetries()
              .setDefaultRequestConfig(
                  RequestConfig.custom()
                      .setConnectionRequestTimeout(Timeout.ofSeconds(10))
                      .setResponseTimeout(Timeout.ofSeconds(10))
                      .build());
      var manager =
          PoolingHttpClientConnectionManagerBuilder.create()
              .setDefaultConnectionConfig(
                  org.apache.hc.client5.http.config.ConnectionConfig.custom()
                      .setConnectTimeout(Timeout.ofSeconds(10))
                      .setSocketTimeout(Timeout.ofSeconds(10))
                      .build());
      if (!verify) {
        // Only an explicit per-run opt-out disables certificate checks; installation and defaults
        // always verify TLS.
        var ssl = SSLContexts.custom().loadTrustMaterial((chain, auth) -> true).build();
        manager.setSSLSocketFactory(
            SSLConnectionSocketFactoryBuilder.create()
                .setSslContext(ssl)
                .setHostnameVerifier(NoopHostnameVerifier.INSTANCE)
                .build());
      }
      builder.setConnectionManager(manager.build());
      try (var client = builder.build()) {
        while (true) {
          long start = System.nanoTime();
          var uri = URI.create(str(c, "request_url"));
          if (!Set.of("http", "https").contains(uri.getScheme()))
            throw ApiError.bad("Only HTTP and HTTPS API targets are supported.");
          var req = new HttpUriRequestBase(str(c, "request_method"), uri);
          map(c.get("request_headers"))
              .forEach(
                  (k, v) -> {
                    if (!Set.of("content-length", "host", "connection")
                        .contains(k.toLowerCase(Locale.ROOT))) req.setHeader(k, text(v));
                  });
          String mode = str(c, "body_mode");
          if (!mode.equals("none"))
            req.setEntity(
                new StringEntity(
                    mode.equals("json") ? write(c.get("request_body")) : str(c, "request_body_raw"),
                    mode.equals("json") ? ContentType.APPLICATION_JSON : ContentType.TEXT_PLAIN));
          String retryAfter =
              client.execute(
                  req,
                  response -> {
                    result.put("status_code", response.getCode());
                    var headers = obj();
                    for (var h : response.getHeaders()) headers.put(h.getName(), h.getValue());
                    result.put("response_headers", headers);
                    String body =
                        response.getEntity() == null
                            ? ""
                            : EntityUtils.toString(response.getEntity());
                    result.put("response_body", body.substring(0, Math.min(20000, body.length())));
                    var header = response.getFirstHeader("Retry-After");
                    return header == null ? null : header.getValue();
                  });
          result.put("latency_ms", Math.round((System.nanoTime() - start) / 10000.0) / 100.0);
          if (!Integer.valueOf(429).equals(result.get("status_code")) || retries >= 3) break;
          double wait = Math.min(10, Math.pow(2, retries));
          if (retryAfter != null) {
            try {
              wait = Math.max(0, Double.parseDouble(retryAfter));
            } catch (NumberFormatException e) {
              try {
                wait =
                    Math.max(
                        0,
                        Duration.between(
                                    Instant.now(),
                                    ZonedDateTime.parse(
                                            retryAfter, DateTimeFormatter.RFC_1123_DATE_TIME)
                                        .toInstant())
                                .toMillis()
                            / 1000.0);
              } catch (Exception ignored) {
              }
            }
          }
          wait = Math.min(15, wait);
          Jobs.pause(wait);
          waited += wait;
          retries++;
        }
      }
    } catch (Exception e) {
      result.put("error", e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
    }
    result.put("rate_limit_retries", retries);
    result.put("rate_limit_wait_seconds", waited);
    result.put("executed_at", now());
    int code = (int) number(result.get("status_code"), 0);
    String category = str(c, "category");
    String outcome =
        result.get("error") != null
            ? "error"
            : code == 429
                ? "rate_limited"
                : category.equals("baseline") || category.equals("setup")
                    ? "info"
                    : category.equals("http_method")
                        ? (code == 404 || code == 405
                            ? "handled"
                            : code >= 200 && code < 300 ? "review" : "info")
                        : code >= 400 && code < 500
                            ? "handled"
                            : code >= 200 && code < 300 ? "review" : "info";
    result.put("outcome", outcome);
    return result;
  }
}
