import { useEffect, useRef, useState } from 'react';
import { createKarateJob, getKarateJob, listKarateJobs } from '../api/client';

const POLL_INTERVAL_MS = 1000;
const IN_PROGRESS_STATUSES = new Set(['pending', 'running']);

function NewJobForm({ onCreated }) {
  const [reportsDir, setReportsDir] = useState('');
  const [excelPath, setExcelPath] = useState('');
  const [environment, setEnvironment] = useState('');
  const [preRequisite, setPreRequisite] = useState('');
  const [createdBy, setCreatedBy] = useState('');
  const [sprint, setSprint] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!reportsDir.trim() || !excelPath.trim()) {
      setError('Provide both the Karate reports location and the Excel file location.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const job = await createKarateJob({
        reports_dir: reportsDir.trim(),
        excel_path: excelPath.trim(),
        environment: environment.trim(),
        pre_requisite: preRequisite.trim(),
        created_by: createdBy.trim(),
        sprint: sprint.trim(),
      });
      onCreated(job);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor="reports-dir">Karate HTML reports location (absolute folder path)</label>
      <input
        id="reports-dir"
        type="text"
        placeholder="/Users/you/project/target/karate-reports"
        value={reportsDir}
        onChange={(e) => setReportsDir(e.target.value)}
      />

      <label htmlFor="excel-path">Test cases Excel file location (absolute path, ending in .xlsx)</label>
      <input
        id="excel-path"
        type="text"
        placeholder="/Users/you/testcases/api-test-cases.xlsx"
        value={excelPath}
        onChange={(e) => setExcelPath(e.target.value)}
      />

      <label htmlFor="environment">Environment</label>
      <input id="environment" type="text" placeholder="QA" value={environment} onChange={(e) => setEnvironment(e.target.value)} />

      <label htmlFor="pre-requisite">Pre-Requisite</label>
      <input
        id="pre-requisite"
        type="text"
        placeholder="User must be logged in"
        value={preRequisite}
        onChange={(e) => setPreRequisite(e.target.value)}
      />

      <label htmlFor="created-by">Created By</label>
      <input id="created-by" type="text" placeholder="Your name" value={createdBy} onChange={(e) => setCreatedBy(e.target.value)} />

      <label htmlFor="sprint">Sprint</label>
      <input id="sprint" type="text" placeholder="Sprint 24" value={sprint} onChange={(e) => setSprint(e.target.value)} />

      <button type="submit" disabled={submitting}>
        {submitting ? 'Starting…' : 'Generate test cases'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function JobStatus({ job }) {
  const inProgress = IN_PROGRESS_STATUSES.has(job.status);
  return (
    <div className="jmeter-job-status">
      <h3>
        Job #{job.id} — {job.status}
      </h3>
      {inProgress && <p>Scanning reports and building the spreadsheet…</p>}
      {job.status === 'completed' && (
        <>
          <p>
            Generated <strong>{job.scenario_count}</strong> test case{job.scenario_count === 1 ? '' : 's'} (
            {job.step_count} step{job.step_count === 1 ? '' : 's'}) from <strong>{job.feature_count}</strong> feature
            report{job.feature_count === 1 ? '' : 's'}.
          </p>
          <p>
            Saved to <code>{job.excel_path}</code>
          </p>
        </>
      )}
      {job.status === 'failed' && job.error && <p className="error-text">{job.error}</p>}
      {job.warnings?.length > 0 && (
        <details open>
          <summary>Warnings ({job.warnings.length})</summary>
          <pre>{job.warnings.join('\n')}</pre>
        </details>
      )}
    </div>
  );
}

function KarateHistory({ onOpen }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listKarateJobs()
      .then(setJobs)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading history…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (jobs.length === 0) return <p>No test cases generated yet.</p>;

  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>Job</th>
          <th>Reports location</th>
          <th>Excel file</th>
          <th>Test cases</th>
          <th>Status</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.id} className="result-row" onClick={() => onOpen(job.id)}>
            <td>#{job.id}</td>
            <td className="url-cell">{job.reports_dir}</td>
            <td className="url-cell">{job.excel_path}</td>
            <td>{job.scenario_count}</td>
            <td>{job.status}</td>
            <td>{new Date(job.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function KarateTestCaseTool() {
  const [view, setView] = useState('new'); // 'new' | 'history'
  const [job, setJob] = useState(null);
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

  function pollJob(id) {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getKarateJob(id);
        setJob(updated);
        if (!IN_PROGRESS_STATUSES.has(updated.status)) {
          stopPolling();
        }
      } catch {
        stopPolling();
      }
    }, POLL_INTERVAL_MS);
  }

  function handleCreated(newJob) {
    setJob(newJob);
    if (IN_PROGRESS_STATUSES.has(newJob.status)) {
      pollJob(newJob.id);
    }
  }

  async function handleOpenFromHistory(id) {
    stopPolling();
    const opened = await getKarateJob(id);
    setJob(opened);
    setView('new');
    if (IN_PROGRESS_STATUSES.has(opened.status)) {
      pollJob(opened.id);
    }
  }

  return (
    <div className="karate-test-case-tool">
      <nav className="tool-subnav">
        <button className={view === 'new' ? 'active' : ''} onClick={() => setView('new')}>
          New
        </button>
        <button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}>
          History
        </button>
      </nav>

      {view === 'new' && (
        <>
          <NewJobForm onCreated={handleCreated} />
          {job && <JobStatus job={job} />}
        </>
      )}
      {view === 'history' && <KarateHistory onOpen={handleOpenFromHistory} />}
    </div>
  );
}
