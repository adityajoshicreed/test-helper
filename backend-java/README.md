# QA Helper — Spring Boot backend

An independent Java implementation of the nine tools in the existing Django backend. It serves the existing React frontend's `/api/.../` endpoints and snake_case JSON fields, including trailing slashes, job polling, history, credential pause/resume, Excel exports, and `delay_seconds` pacing.

The Django backend remains in `../backend/`. This service does not launch Django or invoke Python for application features. Java and Django have separate databases: existing SQLite history is **not imported** into H2. You can switch back to Django without modifying its data.

## Run

Requires a Java **21 JDK**, `curl`, `tar`, and `sha512sum` for the Maven launcher. The launcher downloads Maven 3.9.11 with checksum verification into the ignored `.mvn/cache/` directory; an installed Maven also works with `mvn` instead of `./mvnw`.

```bash
cd backend-java
./mvnw test
./mvnw package
java -jar target/qa-helper-backend-1.0.0.jar
```

The default address is `127.0.0.1:8000`, matching `frontend/src/api/client.js`. Stop Django before running Java on that port. Start the unchanged frontend from `frontend/` with `npm ci` and `npm run dev`.

To run both backends at once for comparison, keep Django on 8000 and run Java on another port:

```bash
PORT=8001 java -jar target/qa-helper-backend-1.0.0.jar
curl --fail http://127.0.0.1:8001/api/health/
```

The frontend continues calling whichever backend owns port 8000. No frontend configuration changes are required to use Java there. A health response of `{"status":"ok","backend":"spring-boot"}` identifies this backend.

### Managed cloud build helper

Some cloud machines provide an incomplete system compiler or require an outbound proxy and an additional CA trust store. The optional Linux x86_64 helper supplies a checksum-verified Temurin 21.0.9 JDK when `JAVA_HOME/bin/javac` is unavailable, writes local Maven proxy settings from `HTTPS_PROXY` without credentials, and uses `/etc/ssl/certs/java/cacerts` when present. It requires Python 3 only to generate Maven settings; the Java service does not require Python.

```bash
cd backend-java
./tools/cloud-maven.sh test package
```

The helper installs its JDK into `.mvn/cache/jdk-21.0.9+10` and prints Maven's normal output. If using that JDK to run the jar, use:

```bash
.mvn/cache/jdk-21.0.9+10/bin/java \
  -Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts \
  -jar target/qa-helper-backend-1.0.0.jar
```

If you provide your own `JAVA_HOME`, run `$JAVA_HOME/bin/java` instead. On other platforms, use the normal Java 21/Maven commands above. Authenticated proxies need your own secure Maven/JVM configuration; the helper deliberately does not copy proxy credentials into files. Build downloads retain TLS and checksum verification. Runtime API requests honor `HTTP_PROXY`, `HTTPS_PROXY`, and hostname rules in `NO_PROXY`; loopback targets always remain local. For a custom JVM trust store, set Java's `javax.net.ssl.trustStore` option.

## Configuration and data

| Environment variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | HTTP port |
| `BIND_ADDRESS` | `127.0.0.1` | Bind address |
| `JDBC_URL` | `jdbc:h2:file:./data/qahelper;DB_CLOSE_ON_EXIT=FALSE` | H2 storage URL |
| `DB_USER` | `sa` | Database user |
| `DB_PASSWORD` | empty | Database password |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins |

Run from `backend-java/` to keep the default database and uploads in its ignored `data/` directory. The SQL schema initializes automatically. Documents and their ordered children are persisted through Spring JDBC; JSON payloads preserve each tool's existing API shape. Document creation and mutation are serialized within one server process. This implementation is intended to run as one local backend instance, like the original application; it is not a multi-instance job system.

Background jobs use a bounded executor (four workers, 100 queued jobs, configurable with `qa.job-workers` and `qa.job-queue`). Results are persisted after each API case. Active jobs interrupted by a server restart are marked failed on startup with a reason rather than left permanently running. They are not automatically replayed, because API calls can have side effects. Paused credential runs can be resumed after a restart.

## Endpoints

All paths below are relative to `/api`. Collections support `GET` for history; operations listed with `POST` create or update records.

| Tool | Endpoints |
|---|---|
| Health | `GET /health/` |
| API Tester | `POST /import-curl/`; `GET /imported-requests/`, `/imported-requests/{id}/`; `POST /imported-requests/{id}/test-runs/`; `GET /test-runs/`, `/test-runs/{id}/`; `POST /test-runs/{id}/stop/`, `/test-runs/{id}/export-excel/` |
| Chain Tester | `GET/POST /chains/chains/`; `GET /chains/chains/{id}/`; `POST /chains/chains/{id}/steps/`, `/chains/chains/{id}/runs/`; `GET /chains/runs/`, `/chains/runs/{id}/` |
| Credential Tester | `POST /credential-tests/parse-curl/`; `GET/POST /credential-tests/runs/`; `GET /credential-tests/runs/{id}/`; `POST /credential-tests/runs/{id}/resume/` |
| Karate / Karate AI | `GET/POST /karate/jobs/`, `/karate-ai/jobs/`; `GET /karate/jobs/{id}/`, `/karate-ai/jobs/{id}/` |
| JMeter | Multipart `POST /jmeter/jobs/`; `GET /jmeter/jobs/`, `/jmeter/jobs/{id}/`, `/jmeter/jobs/{id}/report/` and report assets |
| Load Tracker | `GET/POST /load-tests/plans/`; `GET /load-tests/plans/{id}/`; `POST /load-tests/plans/{id}/tests/`; multipart `POST /load-tests/tests/{id}/record/` |
| Log Viewer | `GET/POST /logs/jobs/`; `GET /logs/jobs/{id}/`, `/logs/jobs/{id}/entries/` |
| Manual Cases | `GET/POST /manual-tests/suites/`; `GET /manual-tests/suites/{id}/`; `POST /manual-tests/suites/{id}/cases/`, `/manual-tests/cases/{id}/steps/`, `/manual-tests/suites/{id}/export/` |

Input errors return HTTP 400 with `{"error":"..."}`; missing records return 404; a full job queue returns 503. Job failures are available through their detail endpoints. Detail records include the same fields used by the React screens; list responses may include additional detail fields.

## Workflow behavior

- **API tests:** curl is parsed as data, never executed in a shell. Supports method, headers, JSON/raw bodies, basic auth, cookies, user-agent, referer and GET query data. Multipart curl (`-F`) is rejected; this is not a full curl CLI implementation. Nested JSON field paths are limited to depth six and the first five elements of each array, as in Django. Keys containing `.`, `[` or `]` retain the original path limitation. Dynamic request-ID and idempotency headers receive new UUID values per generated case.
- **Pacing:** `delay_seconds` accepts finite numbers from 0 to 60, including decimals, defaults to zero, and persists with the run. There is no wait before the first or after the last case. Chain pacing happens before each subsequent case's per-test setup requests. Resume retries the pending credential case immediately, then uses the saved delay. Stop is checked while waiting and before another request is sent.
- **HTTP results:** ten-second connection/response timeouts, a 20,000-character stored response limit, and up to three explicit 429 retries. `Retry-After` is honored up to 15 seconds; otherwise waits are 1, 2, and 4 seconds. Outcome badges use the same status-based heuristic as Django. TLS is verified by default; an explicit `verify_ssl: false` applies only to that run.
- **Chains:** earlier setup calls provide `{{variables}}` extracted from JSON paths or `status_code`. `once` setup calls run once; `per_test` setup calls refresh before each mutation. Missing placeholders remain visible in requests. Setup HTTP transport errors stop the run or fail the affected case, consistent with the existing runner.
- **Credentials:** matches expiration status **or** a case-insensitive response substring. The triggering case stays pending until fresh values are submitted to `resume/`.
- **Excel:** Apache POI writes the same 18-column layout and merged case-level cells. Exports use absolute backend filesystem paths. Text cells are capped at Excel's 32,767-character limit.
- **Karate:** reads embedded `karate-data`, includes nested called-feature HTTP steps, omits skipped steps, and preserves JSON/code and plain-text response bodies. Malformed reports produce warnings. AI calls Ollama once per scenario and falls back to ordinary text with warnings when enhancement fails.
- **Load results:** parses raw JMeter CSV samples and optional server metrics with Apache Commons CSV; computes counts, error rate, mean/min/max and interpolated percentiles, and about 120 buckets per chart. Metrics have their own relative timeline. Recording a result twice is rejected. This module does not generate load.
- **Logs:** imports plain `.log` and rotated `.log.*` files, joins continuation lines, supports the Spring Boot default and common log4j/log4j2 pattern tokens, and caps imports at 20,000 entries. XML external entities and DTDs are disabled. Entries support `search`, `logger`, comma-separated `level`, `filter=request|response`, `sort=timestamp|seq`, `order=asc|desc`, `page`, and `page_size` (maximum 500). This is an imported snapshot, not a live tail.
- **JMeter:** requires a separately installed JMeter executable (and Java), or a `jmeter_bin` path. Upload field is `csv_file`; `output_dir` must be absolute and empty/nonexistent. Runs a process argument list with a 600-second timeout and serves generated report files with traversal/symlink checks.
- **Ollama:** optional external service and model; defaults to `http://localhost:11434`. Supply `ollama_model` and optionally `ollama_base_url` for AI jobs. No model is bundled.

Like the original backend, this is a trusted local QA application: submitted requests can contain credentials and API calls can change target systems. There is no new authentication or user-isolation layer. Django admin and SQLite-history migration are not part of this Java backend.

## Validation

`./mvnw test` runs unit/parameterized tests and Spring Boot/MockMvc integration tests against an isolated in-memory H2 database. Tests use a real local HTTP server for request execution, pacing, 429 retries, chains, credential resume, and the Ollama response contract. They also check Excel cells, the existing Karate fixtures, CSV aggregates, logs, persistent document reload, restart recovery, report files, and input errors.

JMeter process tests use a temporary deterministic executable; they do not establish a working external JMeter installation. AI tests exercise a local fake Ollama protocol endpoint and fallback behavior; they do not require or validate an installed model. `package` creates an executable Spring Boot jar. The existing Python suite remains runnable separately from `../backend/`.
