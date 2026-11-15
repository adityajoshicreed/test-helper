package com.qahelper;

import java.io.IOException;
import java.net.*;
import java.util.*;

/** Uses the environment's outbound proxy without sending loopback traffic through it. */
final class Network {
  private Network() {}

  static ProxySelector proxySelector() {
    return new ProxySelector() {
      @Override
      public List<Proxy> select(URI uri) {
        String host = Optional.ofNullable(uri.getHost()).orElse("").toLowerCase(Locale.ROOT);
        String noProxy = env("NO_PROXY");
        if (host.equals("localhost") || host.equals("127.0.0.1") || host.equals("::1"))
          return List.of(Proxy.NO_PROXY);
        for (String raw : noProxy.split(",")) {
          String rule = raw.strip().toLowerCase(Locale.ROOT);
          if (rule.equals("*")) return List.of(Proxy.NO_PROXY);
          if (rule.contains(":")) rule = rule.substring(0, rule.indexOf(':'));
          if (rule.startsWith(".")) rule = rule.substring(1);
          if (!rule.isEmpty() && (host.equals(rule) || host.endsWith("." + rule)))
            return List.of(Proxy.NO_PROXY);
        }
        String proxy = env("https".equals(uri.getScheme()) ? "HTTPS_PROXY" : "HTTP_PROXY");
        if (proxy.isBlank()) return List.of(Proxy.NO_PROXY);
        URI endpoint = URI.create(proxy.contains("://") ? proxy : "http://" + proxy);
        if (endpoint.getUserInfo() != null)
          throw new IllegalStateException(
              "Authenticated outbound proxies require JVM proxy authentication configuration.");
        return List.of(
            new Proxy(
                Proxy.Type.HTTP,
                new InetSocketAddress(
                    endpoint.getHost(), endpoint.getPort() > 0 ? endpoint.getPort() : 80)));
      }

      @Override
      public void connectFailed(URI uri, SocketAddress address, IOException error) {}
    };
  }

  private static String env(String key) {
    return System.getenv()
        .getOrDefault(key, System.getenv().getOrDefault(key.toLowerCase(Locale.ROOT), ""));
  }
}
