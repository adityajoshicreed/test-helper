import { useEffect, useRef, useState } from 'react';
import ParsedRequestView from '../components/ParsedRequestView';
import TestRunResults from '../components/TestRunResults';
import {
  addChainStep,
  createChain,
  createChainRun,
  getChain,
  getChainRun,
  listChainRuns,
} from '../api/client';

const POLL_INTERVAL_MS = 700;
const IN_PROGRESS_STATUSES = new Set(['pending', 'running']);

function NewChainForm({ onCreated }) {
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const chain = await createChain(name.trim());
      onCreated(chain);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor="chain-name">Chain name (optional)</label>
      <input
        id="chain-name"
        type="text"
        placeholder="Create todo, then fetch it"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Start building a chain'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function AddStepForm({ chainId, stepNumber, onAdded }) {
  const [rawCurl, setRawCurl] = useState('');
  const [refreshMode, setRefreshMode] = useState('once');
  const [extractRows, setExtractRows] = useState([{ name: '', path: '' }]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  function updateRow(index, field, value) {
    setExtractRows((rows) => rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }

  function addRow() {
    setExtractRows((rows) => [...rows, { name: '', path: '' }]);
  }

  function removeRow(index) {
    setExtractRows((rows) => rows.filter((_, i) => i !== index));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!rawCurl.trim()) {
      setError('Provide a curl command for this step.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const extract_rules = {};
      for (const row of extractRows) {
        if (row.name.trim() && row.path.trim()) extract_rules[row.name.trim()] = row.path.trim();
      }
      const step = await addChainStep(chainId, {
        raw_curl: rawCurl,
        refresh_mode: refreshMode,
        extract_rules,
      });
      onAdded(step);
      setRawCurl('');
      setRefreshMode('once');
      setExtractRows([{ name: '', path: '' }]);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor={`step-curl-${stepNumber}`}>
        Step {stepNumber} curl — use <code>{'{{varName}}'}</code> to reference a variable extracted from an earlier step
      </label>
      <textarea
        id={`step-curl-${stepNumber}`}
        rows={4}
        value={rawCurl}
        onChange={(e) => setRawCurl(e.target.value)}
        placeholder="curl -H 'Authorization: Bearer {{token}}' https://api.example.com/protected"
      />

      <label htmlFor={`refresh-mode-${stepNumber}`}>Refresh mode</label>
      <select
        id={`refresh-mode-${stepNumber}`}
        value={refreshMode}
        onChange={(e) => setRefreshMode(e.target.value)}
      >
        <option value="once">Once — run one time, reuse the result for every test</option>
        <option value="per_test">Per test — re-run fresh before each generated test (e.g. a one-time token)</option>
      </select>

      <label>Extract variables from this step's response (optional)</label>
      {extractRows.map((row, i) => (
        <div className="extract-rule-row" key={i}>
          <input
            type="text"
            placeholder="variable name, e.g. token"
            value={row.name}
            onChange={(e) => updateRow(i, 'name', e.target.value)}
          />
          <input
            type="text"
            placeholder="path, e.g. body.token or status_code"
            value={row.path}
            onChange={(e) => updateRow(i, 'path', e.target.value)}
          />
          <button type="button" className="secondary" onClick={() => removeRow(i)}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" className="secondary" onClick={addRow}>
        + Add variable
      </button>

      <button type="submit" disabled={submitting}>
        {submitting ? 'Adding…' : 'Add step'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function StepList({ steps }) {
  if (steps.length === 0) return null;
  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Method</th>
          <th>URL</th>
          <th>Refresh</th>
          <th>Role</th>
        </tr>
      </thead>
      <tbody>
        {steps.map((step, i) => (
          <tr key={step.id}>
            <td>{step.order}</td>
            <td>{step.method}</td>
            <td className="url-cell">{step.url}</td>
            <td>{step.refresh_mode === 'per_test' ? 'Per test' : 'Once'}</td>
            <td>{i === steps.length - 1 ? 'API under test' : 'Setup'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ChainHistory({ onOpen }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listChainRuns()
      .then(setRuns)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading history…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (runs.length === 0) return <p>No chain runs yet.</p>;

  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>Run</th>
          <th>Chain</th>
          <th>Steps</th>
          <th>Status</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id} className="result-row" onClick={() => onOpen(run)}>
            <td>#{run.id}</td>
            <td>{run.chain.name || `Chain #${run.chain.id}`}</td>
            <td>{run.chain.step_count}</td>
            <td>{run.status}</td>
            <td>{new Date(run.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ChainTesterTool() {
  const [view, setView] = useState('build'); // 'build' | 'history'
  const [chain, setChain] = useState(null);
  const [chainRun, setChainRun] = useState(null);
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
        const updated = await getChainRun(runId);
        setChainRun(updated);
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

  function handleChainCreated(newChain) {
    stopPolling();
    setChain(newChain);
    setChainRun(null);
    setRunError(null);
    setRunning(false);
  }

  function handleStepAdded(step) {
    setChain((prev) => ({ ...prev, steps: [...prev.steps, step] }));
    setChainRun(null);
    setRunError(null);
  }

  function handleNewChain() {
    stopPolling();
    setChain(null);
    setChainRun(null);
    setRunError(null);
    setRunning(false);
  }

  async function handleRunTests(selection) {
    stopPolling();
    setRunning(true);
    setRunError(null);
    setChainRun(null);
    try {
      const run = await createChainRun(chain.id, selection);
      setChainRun(run);
      if (IN_PROGRESS_STATUSES.has(run.status)) {
        pollRun(run.id);
      } else {
        setRunning(false);
      }
    } catch (err) {
      setRunError(err.message);
      setRunning(false);
    }
  }

  async function handleOpenFromHistory(runSummary) {
    stopPolling();
    const [fullChain, fullRun] = await Promise.all([
      getChain(runSummary.chain.id),
      getChainRun(runSummary.id),
    ]);
    setChain(fullChain);
    setChainRun(fullRun);
    setRunError(null);
    setView('build');
    if (IN_PROGRESS_STATUSES.has(fullRun.status)) {
      setRunning(true);
      pollRun(fullRun.id);
    } else {
      setRunning(false);
    }
  }

  const lastStep = chain?.steps?.length ? chain.steps[chain.steps.length - 1] : null;

  return (
    <div className="chain-tester-tool">
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
          {!chain && <NewChainForm onCreated={handleChainCreated} />}

          {chain && (
            <>
              <div className="chain-header">
                <h2>{chain.name || `Chain #${chain.id}`}</h2>
                <button type="button" className="secondary" onClick={handleNewChain}>
                  + New chain
                </button>
              </div>

              <StepList steps={chain.steps} />
              <AddStepForm chainId={chain.id} stepNumber={chain.steps.length + 1} onAdded={handleStepAdded} />

              {lastStep && (
                <ParsedRequestView
                  key={lastStep.id}
                  importedRequest={lastStep}
                  onRunTests={handleRunTests}
                  running={running}
                />
              )}

              {runError && <p className="error-text">{runError}</p>}
              {chainRun && <TestRunResults testRun={chainRun} />}
            </>
          )}
        </>
      )}

      {view === 'history' && <ChainHistory onOpen={handleOpenFromHistory} />}
    </div>
  );
}
