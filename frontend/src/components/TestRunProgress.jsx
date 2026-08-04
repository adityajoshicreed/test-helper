export default function TestRunProgress({ testRun, onStop, stopping }) {
  const cases = testRun.test_cases || [];
  const total = cases.length;
  const completed = cases.filter((tc) => tc.executed_at).length;
  const pct = total ? Math.round((completed / total) * 100) : 0;
  const current = cases.find((tc) => !tc.executed_at);
  const canStop = onStop && testRun.status === 'running' && !testRun.stop_requested;

  return (
    <div className="test-run-progress">
      <div className="progress-bar-track">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <p className="progress-label">
        {completed}/{total} tests complete ({pct}%)
        {current && (
          <>
            {' '}— running: <strong>{current.description}</strong>
          </>
        )}
        {testRun.stop_requested && <> — stopping after the in-flight request…</>}
        {canStop && (
          <button
            type="button"
            className="stop-run-button"
            onClick={onStop}
            disabled={stopping}
          >
            {stopping ? 'Stopping…' : 'Stop'}
          </button>
        )}
      </p>
    </div>
  );
}
