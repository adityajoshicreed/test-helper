#!/usr/bin/env bash
# Optional helper for managed cloud machines with a proxy or an incomplete system JDK.
set -euo pipefail
BASE=$(cd -- "$(dirname -- "$0")/.." && pwd)
CACHE="$BASE/.mvn/cache"
mkdir -p "$CACHE"
if [[ -z "${JAVA_HOME:-}" || ! -x "$JAVA_HOME/bin/javac" ]]; then
  JDK="$CACHE/jdk-21.0.9+10"
  if [[ ! -x "$JDK/bin/javac" ]]; then
    URL='https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.9%2B10/OpenJDK21U-jdk_x64_linux_hotspot_21.0.9_10.tar.gz'
    curl -fsSL "$URL.sha256.txt" -o "$CACHE/jdk.sha256"
    curl -fsSL "$URL" -o "$CACHE/jdk.tar.gz"
    (cd "$CACHE" && printf '%s  jdk.tar.gz\n' "$(awk '{print $1}' jdk.sha256)" | sha256sum --check --status)
    tar -xzf "$CACHE/jdk.tar.gz" -C "$CACHE"
  fi
  export JAVA_HOME="$JDK"
fi
# Keep TLS verification enabled and use the machine's trusted CA store when available.
if [[ -f /etc/ssl/certs/java/cacerts && "${MAVEN_OPTS:-}" != *javax.net.ssl.trustStore* ]]; then
  export MAVEN_OPTS="${MAVEN_OPTS:-} -Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts"
fi
python3 - "$CACHE/settings.xml" <<'PY'
import os, sys, urllib.parse, xml.etree.ElementTree as ET
root=ET.Element('settings')
proxy=urllib.parse.urlparse(os.environ.get('HTTPS_PROXY',os.environ.get('https_proxy','')))
if proxy.hostname:
    if proxy.username or proxy.password:
        raise SystemExit('Use secure Maven settings for an authenticated proxy; this helper does not write credentials.')
    node=ET.SubElement(ET.SubElement(root,'proxies'),'proxy')
    for k,v in {'id':'environment','active':'true','protocol':'http','host':proxy.hostname,'port':str(proxy.port or 80),'nonProxyHosts':'localhost|127.0.0.1'}.items():
        ET.SubElement(node,k).text=v
ET.ElementTree(root).write(sys.argv[1],encoding='unicode')
PY
exec "$BASE/mvnw" -s "$CACHE/settings.xml" "$@"
