# QA Helper Tool

A growing collection of QA utilities behind a single home page:
- **API Tester** — paste a curl command, pick which negative/boundary tests to run against it, and see the results for every generated variant.
- **JMeter Report Generator** — upload a JMeter results CSV/JTL file and get back an HTML dashboard report.
- **Karate Test Case Generator** — point it at a folder of Karate HTML execution reports and get back an Excel sheet of API test cases, one step per HTTP call.
- **API Chain Tester** — chain multiple curl-derived requests together, passing data extracted from one response into the next, then run the same mutation-test engine against only the last one (the API actually under test).

More tools (Test Case Creator, Test Data Generator, ...) will be added as separate cards on the home page over time.

## Adding a new tool
The frontend is structured so a new tool is just: build a self-contained component under `frontend/src/tools/`, add it to the `TOOLS` registry in `frontend/src/App.jsx`, and flip its `available` flag to `true` in the catalog in `frontend/src/components/HomePage.jsx`. Each tool owns its own internal navigation/state; `App.jsx` only handles top-level routing between the home page and whichever tool is active. On the backend, each tool that needs one is its own Django app (`apitester/`, `jmeter_reporter/`, `karate_tests/`, `chain_tester/`) registered in `INSTALLED_APPS` and mounted under its own `/api/<tool>/` prefix in `config/urls.py`.

## Stack
- **Backend**: Django + Django REST Framework (SQLite), `backend/`
- **Frontend**: React + Vite, `frontend/`

## Running it

### Backend (port 8000)
```bash
cd backend
source venv/bin/activate
python manage.py runserver 8000
```

### Frontend (port 5173)
```bash
cd frontend
npm install   # first time only
npm run dev
```

Then open http://localhost:5173.

## What the API Tester tool does
Open http://localhost:5173, click the "API Tester" card on the home page, then:
1. Paste a curl command (e.g. copied from your browser's devtools "Copy as cURL") and import it.
2. The tool parses method, URL, headers, and body.
3. Pick exactly which tests to run, per field:
   - **Body field tests**: a field × test matrix — every field in the JSON body gets its own row, including nested ones (`user.address.city`, `items[0].id`) and the nested objects/arrays themselves (`user.address`, `items[0]`), discovered by walking the body recursively (capped at depth 6, and the first 5 elements of any array, so a huge payload can't blow up the test count). Check any of Null / Empty / Wrong type / Missing per row — only the mutations meaningful for that field's type are shown (e.g. booleans have no "empty" test). Each mutation is applied to a fresh copy of the body, so testing `items[0].id` leaves `items[0].qty` and `items[1]` untouched.
   - **Header tests**: a header × test matrix — for each header, check Missing and/or Empty.
   - **Whole-request tests**: blanket, non-field-scoped tests — whole-body mutations (empty/null/malformed/no body) and alternate HTTP methods.
   - "Select all" / "Select none" per matrix for convenience. A baseline (unmodified request) is always run for comparison.
   - **Skip SSL certificate verification**: off by default; turn it on when the target is behind a self-signed or internal-CA certificate (common for staging/internal APIs) that would otherwise fail every request with a certificate verification error. Applies to every request in the run, including in the API Chain Tester.
4. Headers that look like per-request nonces (`x-req-id`, `x-request-id`, `x-correlation-id`, `x-trace-id`, `idempotency-key`) get a fresh value generated for every test case instead of reusing the literal value from the curl, so requests aren't rejected as duplicates — except in the specific test that deliberately removes/empties that header.
5. Running a test run shows a live progress bar (e.g. "12/28 tests complete (43%) — running: Set field 'age' to null") that updates in real time; the results table fills in row by row as each request completes, with the currently-running row highlighted.
6. Results show status code, latency, and an outcome badge (Handled / Review / Error / Info / Rate limited) — a heuristic hint, not a verdict. Expand any completed row to see the exact request sent and the full response.
7. If a target API responds with 429, the request is retried automatically before being recorded: it honors a `Retry-After` header (capped at 15s) or falls back to exponential backoff (1s, 2s, 4s — capped at 10s, up to 3 retries). If it still hasn't succeeded after that, the case is marked "Rate limited" rather than lumped in with a normal pass/fail, and the row shows how many retries/how long it waited.
8. Past test runs are saved and browsable under "History" — reopening a run that's still in progress resumes live progress tracking.

## What the JMeter Report Generator tool does
Click the "JMeter Report Generator" card, then:
1. Upload a JMeter results file (CSV or JTL) and provide an absolute output directory. Optionally provide the path to your `jmeter` binary — if left blank, the tool looks for `jmeter` on the server's PATH.
2. On submit, the tool runs JMeter's built-in non-GUI report generator (`jmeter -g <results> -o <output-dir>`) in a background thread and returns immediately; the UI polls for completion.
3. Preflight checks happen before anything runs, with a clear error message and no job created if they fail: the output directory must be an absolute path and either not exist yet or be empty (JMeter itself refuses to write into a non-empty directory), and the JMeter binary must exist and be executable (or be found on PATH).
4. On success, click "Open report" to view the generated HTML dashboard (served directly by the backend from the output directory) — it's also written to disk at the path you gave. On failure, the exact command, stdout, and stderr are shown for debugging.
5. Past jobs are saved and browsable under "History".

## What the Karate Test Case Generator tool does
Click the "Karate Test Case Generator" card, then:
1. Provide the folder containing your Karate HTML reports (modern Karate reports embed each feature's full execution data as JSON in a `<script id="karate-data">` tag; the tool reads that directly rather than scraping rendered markup), the absolute path where the Excel file should be written, and the shared values that apply to every generated test case: Environment, Pre-Requisite, Created By, Sprint, LOB, Vertical, Feasible for Automation?, Test Case Applicability, Labels, Status.
2. The tool scans every `.html` file in that folder (recursively), and for each scenario that made at least one HTTP call, generates one test case with one row per call — including calls made inside another feature it invokes via `call`/`callSingle`, inlined at the point the call actually happened, however many calls deep. Step Description is always "Execute the CURL", Test Data is a reconstructed curl command (method, URL, headers minus the noisy transport ones curl sets itself — `Content-Length`, `Host`, `Connection`, `User-Agent` — and the request body), and Expected/Actual Result both show the response code and response body Karate recorded. Test Case Name and Description are the scenario name (falling back to the feature name if a scenario has none), and S.No is the test case's position in the sheet (1, 2, 3, ...). When a test case has more than one step, every case-level column — S.No, Test Case Name, Test Case Description, Environment, Pre-Requisite, Created By, Sprint, LOB, Vertical, Feasible for Automation?, Test Case Applicability, Labels, and Status — is written as a single merged cell spanning all of that case's rows (they don't vary per API call); only Step #, Step Description, Test Data, Expected Result, and Actual Result are per-row, since those are the ones that do.
3. On success you get a count of features/test cases/steps generated and the output path. Files that aren't per-feature reports (e.g. an overview/summary page) are silently skipped; files that fail to parse are listed as warnings rather than failing the whole run. A `method` step Karate marks as skipped (it never actually ran because an earlier step in the scenario failed first) is omitted rather than turned into a step with nothing to execute — noted as a warning, not a failure. A step that did run but whose logs don't match the expected format closely enough to rebuild a curl command (some Karate configs/versions log less detail than others) is still included with a `# Could not reconstruct the request for step: ...` placeholder in Test Data, also flagged as a warning so it's easy to spot which step needs a manual look — it's kept rather than dropped, since the call did happen.
4. Past jobs are saved and browsable under "History".

## What the API Chain Tester tool does
For APIs where one call depends on another — log in, take the token, use it to call the endpoint you actually want to test. Click the "API Chain Tester" card, then:
1. Start a chain (optional name), then add steps one at a time as curl commands — same parser as API Tester, so anything you'd paste there works here too. Any step after the first can reference a variable from an earlier step's response with `{{varName}}` in its URL, header values, or body.
2. Each step (except the last) also has an **extraction rule** (`{variable_name: "body.path.to.value"}`, or the special path `status_code`) and a **refresh mode**:
   - **Once** — runs a single time per test run; its extracted value is cached and reused for every generated test of the last step. Use this for something reusable, like a login session.
   - **Per test** — re-run fresh right before *each* generated test of the last step. Use this for something that goes stale after one use, like a one-time token — otherwise every test after the first would fail for a reason that has nothing to do with what you're actually testing.
3. The **last step you've added is always "the API under test"** — adding another step afterward makes that new one the last step instead (the API Tester field/header matrix appears for whichever step currently holds that position). Pick mutations for it exactly as in API Tester.
4. Running the chain executes every "once" step a single time, then for each generated test: refreshes any "per test" steps, substitutes the current values into the test's `{{var}}` placeholders, and runs it. Each result's expandable row shows the resolved request that was actually sent.
5. If a setup step fails outright (e.g. login itself fails), the whole run stops with a clear error naming the step — nothing downstream would be meaningful. If a "per test" refresh fails for one specific generated test, only that test is marked an error; the rest of the run continues.
6. Past chains/runs are saved and browsable under "History".

## Tests
```bash
cd backend
source venv/bin/activate
python manage.py test
```

## Known limitations (v1)
- Body field path parsing (API Tester) assumes JSON keys don't themselves contain `.`, `[`, or `]` (true for virtually all real-world APIs).
- Multipart form data (`-F`) in curl commands isn't parsed.
- Test cases execute one at a time in a background thread per run (not across runs), and the frontend polls every 700ms for progress — there's no websocket/SSE push, so progress updates are near-real-time rather than instant.
- JMeter report generation has a 600s subprocess timeout; a job that doesn't finish by then is marked failed.
- Karate Test Case Generator only supports the modern Alpine-based Karate HTML report format (the one with an embedded `<script id="karate-data">` JSON blob).
- API Chain Tester: a step can only be added to the end of a chain (no reordering/editing/deleting an earlier step — start a new chain instead). A header whose *name* matches the API Tester's "dynamic header" auto-regeneration pattern (`req-id`, `correlation-id`, `trace-id`, `idempotency`) has its value overwritten with a random UUID before a `{{var}}` placeholder in it would ever get substituted — fine for typical header names (`Authorization`, custom names), just avoid using a placeholder in a header named like that. A "once" step also can't depend on a value produced by a *later* "per test" step — order foundational/reusable setup before anything that needs refreshing.
