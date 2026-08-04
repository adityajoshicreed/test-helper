import { useEffect, useRef, useState } from 'react';
import CurlImportForm from '../components/CurlImportForm';
import HistoryPage from '../components/HistoryPage';
import ParsedRequestView from '../components/ParsedRequestView';
import TestRunResults from '../components/TestRunResults';
import { createTestRun, getTestRun, stopTestRun } from '../api/client';

const POLL_INTERVAL_MS = 700;
const IN_PROGRESS_STATUSES = new Set(['pending', 'running']);

export default function ApiTesterTool() {
  const [view, setView] = useState('import'); // 'import' | 'history'
  const [importedRequest, setImportedRequest] = useState(null);
  const [testRun, setTestRun] = useState(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [stopping, setStopping] = useState(false);
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

  function pollTestRun(runId) {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getTestRun(runId);
        setTestRun(updated);
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

  function handleImported(imported) {
    stopPolling();
    setImportedRequest(imported);
    setTestRun(null);
    setRunError(null);
    setRunning(false);
    setStopping(false);
  }

  async function handleStopTestRun() {
    if (!testRun || stopping) return;
    setStopping(true);
    try {
      const updated = await stopTestRun(testRun.id);
      setTestRun(updated);
    } catch (err) {
      setRunError(err.message);
    } finally {
      setStopping(false);
    }
  }

  async function handleRunTests(selection) {
    stopPolling();
    setRunning(true);
    setRunError(null);
    setTestRun(null);
    setStopping(false);
    try {
      const run = await createTestRun(importedRequest.id, selection);
      setTestRun(run);
      if (IN_PROGRESS_STATUSES.has(run.status)) {
        pollTestRun(run.id);
      } else {
        setRunning(false);
      }
    } catch (err) {
      setRunError(err.message);
      setRunning(false);
    }
  }

  function handleReopenFromHistory(imported, run) {
    stopPolling();
    setImportedRequest(imported);
    setTestRun(run);
    setRunError(null);
    setStopping(false);
    setView('import');
    if (IN_PROGRESS_STATUSES.has(run.status)) {
      setRunning(true);
      pollTestRun(run.id);
    } else {
      setRunning(false);
    }
  }

  return (
    <div className="api-tester-tool">
      <nav className="tool-subnav">
        <button
          className={view === 'import' ? 'active' : ''}
          onClick={() => setView('import')}
        >
          Import &amp; Test
        </button>
        <button
          className={view === 'history' ? 'active' : ''}
          onClick={() => setView('history')}
        >
          History
        </button>
      </nav>

      {view === 'import' && (
        <>
          <CurlImportForm onImported={handleImported} />
          {importedRequest && (
            <ParsedRequestView
              key={importedRequest.id}
              importedRequest={importedRequest}
              onRunTests={handleRunTests}
              running={running}
            />
          )}
          {runError && <p className="error-text">{runError}</p>}
          {testRun && (
            <TestRunResults testRun={testRun} onStop={handleStopTestRun} stopping={stopping} />
          )}
        </>
      )}

      {view === 'history' && <HistoryPage onReopen={handleReopenFromHistory} />}
    </div>
  );
}
