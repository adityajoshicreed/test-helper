export default function TestRunProgress({ testRun }) {
  const cases = testRun.test_cases || [];
  const total = cases.length;
  const completed = cases.filter((tc) => tc.executed_at).length;
  const pct = total ? Math.round((completed / total) * 100) : 0;
  const current = cases.find((tc) => !tc.executed_at);

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
      </p>
    </div>
  );
}
