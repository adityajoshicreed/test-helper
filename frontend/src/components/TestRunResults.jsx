import { Fragment, useState } from 'react';
import TestRunProgress from './TestRunProgress';

const OUTCOME_LABELS = {
  handled: '✓ Handled',
  review: '⚠ Review',
  error: '✕ Error',
  info: 'ℹ Info',
  rate_limited: '⏳ Rate limited',
};

function OutcomeBadge({ outcome }) {
  if (!outcome) return <span className="outcome-badge outcome-pending">… Pending</span>;
  return <span className={`outcome-badge outcome-${outcome}`}>{OUTCOME_LABELS[outcome] || outcome}</span>;
}

export default function TestRunResults({ testRun, onStop, stopping }) {
  const [expandedId, setExpandedId] = useState(null);
  // A paused run (Expiring Credential Tester) still has pending cases with
  // no outcome yet -- show progress, not a final summary that would group
  // them all under a confusing "null" outcome.
  const isRunning =
    testRun.status === 'running' ||
    testRun.status === 'pending' ||
    testRun.status === 'paused_awaiting_credentials';
  const cases = testRun.test_cases || [];
  const currentId = cases.find((tc) => !tc.executed_at)?.id;

  const summary = cases.reduce((acc, tc) => {
    acc[tc.outcome] = (acc[tc.outcome] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="test-run-results">
      <h2>Results — Test Run #{testRun.id}</h2>

      {isRunning ? (
        <TestRunProgress testRun={testRun} onStop={onStop} stopping={stopping} />
      ) : (
        <div className="results-summary">
          {Object.entries(summary).map(([outcome, count]) => (
            <span key={outcome} className="summary-item">
              <OutcomeBadge outcome={outcome} /> <strong>{count}</strong>
            </span>
          ))}
        </div>
      )}

      <table className="results-table">
        <thead>
          <tr>
            <th>Category</th>
            <th>Description</th>
            <th>Method</th>
            <th>Status</th>
            <th>Latency</th>
            <th>Outcome</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((tc) => {
            const pending = !tc.executed_at;
            return (
              <Fragment key={tc.id}>
                <tr
                  className={`result-row${tc.id === currentId ? ' current-row' : ''}`}
                  onClick={() => !pending && setExpandedId(expandedId === tc.id ? null : tc.id)}
                >
                  <td>{tc.category}</td>
                  <td>{tc.description}</td>
                  <td>{tc.request_method}</td>
                  <td>{pending ? '…' : tc.error ? '—' : tc.status_code}</td>
                  <td>
                    {pending ? '—' : tc.latency_ms != null ? `${tc.latency_ms} ms` : '—'}
                    {tc.rate_limit_retries > 0 && (
                      <span className="retry-note">
                        {' '}(retried {tc.rate_limit_retries}x, waited {tc.rate_limit_wait_seconds}s)
                      </span>
                    )}
                  </td>
                  <td><OutcomeBadge outcome={pending ? null : tc.outcome} /></td>
                </tr>
                {expandedId === tc.id && !pending && (
                  <tr className="result-detail-row">
                    <td colSpan={6}>
                      <div className="result-detail">
                        <div>
                          <h4>Request</h4>
                          <p><strong>{tc.request_method}</strong> {tc.request_url}</p>
                          <pre>{JSON.stringify(tc.request_headers, null, 2)}</pre>
                          <pre>
                            {tc.body_mode === 'json'
                              ? JSON.stringify(tc.request_body, null, 2)
                              : tc.body_mode === 'raw'
                                ? tc.request_body_raw
                                : '(no body sent)'}
                          </pre>
                        </div>
                        <div>
                          <h4>Response</h4>
                          {tc.error ? (
                            <p className="error-text">{tc.error}</p>
                          ) : (
                            <>
                              <pre>{JSON.stringify(tc.response_headers, null, 2)}</pre>
                              <pre>{tc.response_body}</pre>
                            </>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
