import { useEffect, useRef, useState } from 'react';
import ParsedRequestView from '../components/ParsedRequestView';
import TestRunResults from '../components/TestRunResults';
import {
  createCredentialRun,
  getCredentialRun,
  listCredentialRuns,
  parseCredentialCurl,
  resumeCredentialRun,
} from '../api/client';

const POLL_INTERVAL_MS = 700;
const IN_PROGRESS_STATUSES = new Set(['pending', 'running']);

function ParseCurlForm({ onParsed }) {
  const [curl, setCurl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!curl.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const parsed = await parseCredentialCurl(curl);
      onParsed(curl, parsed);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="curl-import-form" onSubmit={handleSubmit}>
      <label htmlFor="cred-curl-input">
        Paste a curl command for the endpoint whose token/header expires
      </label>
      <textarea
        id="cred-curl-input"
        rows={8}
        value={curl}
        onChange={(e) => setCurl(e.target.value)}
        placeholder="curl -H 'Authorization: Bearer abc123' https://api.example.com/protected"
      />
      <div className="curl-import-actions">
        <button type="submit" disabled={loading}>
          {loading ? 'Parsing…' : 'Parse curl'}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function CredentialFieldsForm({ parsed, credentialSelection, onChange }) {
  const headerNames = Object.keys(parsed.headers || {});
  const bodyPaths = (parsed.body_field_options || []).map((o) => o.field);

  function toggleField(location, key) {
    const id = `${location}:${key}`;
    onChange((prev) => {
      const next = { ...prev };
      if (next[id]) {
        delete next[id];
      } else {
        next[id] = { location, key, value: location === 'header' ? parsed.headers[key] || '' : '' };
      }
      return next;
    });
  }

  function setValue(location, key, value) {
    const id = `${location}:${key}`;
    onChange((prev) => ({ ...prev, [id]: { ...prev[id], value } }));
  }

  function renderRow(location, key) {
    const id = `${location}:${key}`;
    const entry = credentialSelection[id];
    return (
      <div className="extract-rule-row" key={id}>
        <label>
          <input type="checkbox" checked={!!entry} onChange={() => toggleField(location, key)} />
          {' '}{key}
        </label>
        {entry && (
          <input
            type="text"
            placeholder="current value"
            value={entry.value}
            onChange={(e) => setValue(location, key, e.target.value)}
          />
        )}
      </div>
    );
  }

  return (
    <fieldset>
      <legend>Mark expiring credentials</legend>
      <p className="group-hint">
        Check any header or body field whose value expires after some uses or some time, and give
        its current value. You'll be asked for a fresh value whenever the run pauses.
      </p>

      {headerNames.length > 0 && (
        <>
          <p className="group-hint"><strong>Headers</strong></p>
          {headerNames.map((name) => renderRow('header', name))}
        </>
      )}

      {bodyPaths.length > 0 && (
        <>
          <p className="group-hint"><strong>Body fields</strong></p>
          {bodyPaths.map((path) => renderRow('body', path))}
        </>
      )}

      {headerNames.length === 0 && bodyPaths.length === 0 && (
        <p className="group-hint">This request has no headers or body fields to mark.</p>
      )}
    </fieldset>
  );
}

function ExpirationSignalForm({ statusCode, setStatusCode, messageContains, setMessageContains }) {
  return (
    <fieldset>
      <legend>How do you recognize an expired credential?</legend>
      <p className="group-hint">
        Set a status code, a message to look for in the response, or both — either one matching is
        enough to pause the run.
      </p>
      <label htmlFor="expiration-status-code">Status code</label>
      <input
        id="expiration-status-code"
        type="number"
        placeholder="401"
        value={statusCode}
        onChange={(e) => setStatusCode(e.target.value)}
      />
      <label htmlFor="expiration-message">Message contains</label>
      <input
        id="expiration-message"
        type="text"
        placeholder="token expired"
        value={messageContains}
        onChange={(e) => setMessageContains(e.target.value)}
      />
    </fieldset>
  );
}

function ResumeForm({ run, onResumed }) {
  const [values, setValues] = useState(() => {
    const initial = {};
    for (const field of run.credential_fields || []) initial[field.key] = '';
    return initial;
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const updated = await resumeCredentialRun(run.id, values);
      onResumed(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <p className="dynamic-headers-note">⏸ {run.pause_reason}</p>
      {(run.credential_fields || []).map((field) => (
        <div key={field.key}>
          <label htmlFor={`resume-${field.key}`}>
            {field.location === 'header' ? `Header: ${field.key}` : `Body: ${field.key}`}
          </label>
          <input
            id={`resume-${field.key}`}
            type="text"
            placeholder="fresh value"
            value={values[field.key] || ''}
            onChange={(e) => setValues((prev) => ({ ...prev, [field.key]: e.target.value }))}
          />
        </div>
      ))}
      <button type="submit" disabled={submitting}>
        {submitting ? 'Resuming…' : 'Resume testing'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function CredentialHistory({ onOpen }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listCredentialRuns()
      .then(setRuns)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading history…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (runs.length === 0) return <p>No runs yet.</p>;

  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>Run</th>
          <th>Method</th>
          <th>URL</th>
          <th>Status</th>
          <th>Times paused</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id} className="result-row" onClick={() => onOpen(run.id)}>
            <td>#{run.id}</td>
            <td>{run.method}</td>
            <td className="url-cell">{run.url}</td>
            <td>{run.status}</td>
            <td>{run.pause_count}</td>
            <td>{new Date(run.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function CredentialExpiryTester() {
  const [view, setView] = useState('build');
  const [rawCurl, setRawCurl] = useState('');
  const [parsed, setParsed] = useState(null);
  const [credentialSelection, setCredentialSelection] = useState({});
  const [expirationStatusCode, setExpirationStatusCode] = useState('');
  const [expirationMessageContains, setExpirationMessageContains] = useState('');
  const [run, setRun] = useState(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    return () => stopPolling();
  }, []);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function pollRun(runId) {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getCredentialRun(runId);
        setRun(updated);
        if (!IN_PROGRESS_STATUSES.has(updated.status)) {
          stopPolling();
          setRunning(false);
        }
      } catch (err) {
        stopPolling();
        setRunError(err.message);
        setRunning(false);
      }
    }, POLL_INTERVAL_MS);
  }

  function handleParsed(curl, parsedResult) {
    stopPolling();
    setRawCurl(curl);
    setParsed(parsedResult);
    setCredentialSelection({});
    setExpirationStatusCode('');
    setExpirationMessageContains('');
    setRun(null);
    setRunError(null);
    setRunning(false);
  }

  function handleNew() {
    stopPolling();
    setRawCurl('');
    setParsed(null);
    setCredentialSelection({});
    setExpirationStatusCode('');
    setExpirationMessageContains('');
    setRun(null);
    setRunError(null);
    setRunning(false);
  }

  async function handleRunTests(selection) {
    stopPolling();
    setRunError(null);

    const credentialFields = Object.values(credentialSelection).map((f) => ({
      location: f.location,
      key: f.key,
    }));
    if (credentialFields.length === 0) {
      setRunError('Mark at least one header or body field as an expiring credential.');
      return;
    }
    if (!expirationStatusCode && !expirationMessageContains.trim()) {
      setRunError('Provide an expiration status code, a message to look for, or both.');
      return;
    }
    const currentValues = {};
    for (const f of Object.values(credentialSelection)) currentValues[f.key] = f.value;

    setRunning(true);
    setRun(null);
    try {
      const created = await createCredentialRun({
        raw_curl: rawCurl,
        credential_fields: credentialFields,
        current_values: currentValues,
        expiration_status_code: expirationStatusCode ? Number(expirationStatusCode) : null,
        expiration_message_contains: expirationMessageContains.trim(),
        ...selection,
      });
      setRun(created);
      if (IN_PROGRESS_STATUSES.has(created.status)) {
        pollRun(created.id);
      } else {
        setRunning(false);
      }
    } catch (err) {
      setRunError(err.message);
      setRunning(false);
    }
  }

  function handleResumed(updatedRun) {
    setRun(updatedRun);
    if (IN_PROGRESS_STATUSES.has(updatedRun.status)) {
      setRunning(true);
      pollRun(updatedRun.id);
    } else {
      setRunning(false);
    }
  }

  async function handleOpenFromHistory(runId) {
    stopPolling();
    const fullRun = await getCredentialRun(runId);
    setParsed(null);
    setRun(fullRun);
    setRunError(null);
    setView('build');
    if (IN_PROGRESS_STATUSES.has(fullRun.status)) {
      setRunning(true);
      pollRun(fullRun.id);
    } else {
      setRunning(false);
    }
  }

  return (
    <div className="credential-tester-tool">
      <nav className="tool-subnav">
        <button className={view === 'build' ? 'active' : ''} onClick={() => setView('build')}>
          Build &amp; Test
        </button>
        <button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}>
          History
        </button>
      </nav>

      {view === 'build' && (
        <>
          {!parsed && !run && <ParseCurlForm onParsed={handleParsed} />}

          {parsed && (
            <>
              <div className="chain-header">
                <h2>Configure the expiring credential</h2>
                <button type="button" className="secondary" onClick={handleNew}>
                  + Start over
                </button>
              </div>
              <CredentialFieldsForm
                parsed={parsed}
                credentialSelection={credentialSelection}
                onChange={setCredentialSelection}
              />
              <ExpirationSignalForm
                statusCode={expirationStatusCode}
                setStatusCode={setExpirationStatusCode}
                messageContains={expirationMessageContains}
                setMessageContains={setExpirationMessageContains}
              />
              <ParsedRequestView importedRequest={parsed} onRunTests={handleRunTests} running={running} />
            </>
          )}

          {runError && <p className="error-text">{runError}</p>}

          {run && (
            <>
              {!parsed && (
                <div className="chain-header">
                  <h2>Run #{run.id}</h2>
                  <button type="button" className="secondary" onClick={handleNew}>
                    + New run
                  </button>
                </div>
              )}
              {run.status === 'paused_awaiting_credentials' && (
                <ResumeForm run={run} onResumed={handleResumed} />
              )}
              <TestRunResults testRun={run} />
            </>
          )}
        </>
      )}

      {view === 'history' && <CredentialHistory onOpen={handleOpenFromHistory} />}
    </div>
  );
}
