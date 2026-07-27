import { useEffect, useState } from 'react';
import { getImportedRequest, getTestRun, listTestRuns } from '../api/client';

export default function HistoryPage({ onReopen }) {
  const [testRuns, setTestRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listTestRuns()
      .then(setTestRuns)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  async function handleReopen(runSummary) {
    const [imported, fullRun] = await Promise.all([
      getImportedRequest(runSummary.imported_request.id),
      getTestRun(runSummary.id),
    ]);
    onReopen(imported, fullRun);
  }

  if (loading) return <p>Loading history…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (testRuns.length === 0) return <p>No test runs yet. Import a curl command to get started.</p>;

  return (
    <div className="history-page">
      <h2>Past test runs</h2>
      <table className="results-table">
        <thead>
          <tr>
            <th>Run</th>
            <th>Method</th>
            <th>URL</th>
            <th>Categories</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {testRuns.map((run) => (
            <tr key={run.id} className="result-row" onClick={() => handleReopen(run)}>
              <td>#{run.id}</td>
              <td>{run.imported_request.method}</td>
              <td className="url-cell">{run.imported_request.url}</td>
              <td>{run.categories.length}</td>
              <td>{run.status}</td>
              <td>{new Date(run.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
