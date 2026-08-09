import { useEffect, useRef, useState } from 'react';
import LogViewerDashboard from '../components/LogViewerDashboard';
import { createLogViewJob, getLogViewJob, listLogViewJobs } from '../api/client';

const POLL_INTERVAL_MS = 1000;
const IN_PROGRESS_STATUSES = new Set(['pending', 'running']);

function NewJobForm({ onCreated }) {
  const [logsDir, setLogsDir] = useState('');
  const [log4jXmlPath, setLog4jXmlPath] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!logsDir.trim()) {
      setError('Provide the folder containing your .log files.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const job = await createLogViewJob({
        logs_dir: logsDir.trim(),
        log4j_xml_path: log4jXmlPath.trim(),
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
      <label htmlFor="logs-dir">Logs folder (absolute path — scanned recursively for .log / .log.* files)</label>
      <input
        id="logs-dir"
        type="text"
        placeholder="/Users/you/myapp/logs"
        value={logsDir}
        onChange={(e) => setLogsDir(e.target.value)}
      />

      <label htmlFor="log4j-xml-path">
        log4j XML config (optional — absolute path. Leave blank to use Spring Boot's default log format)
      </label>
      <input
        id="log4j-xml-path"
        type="text"
        placeholder="/Users/you/myapp/src/main/resources/log4j2.xml (optional)"
        value={log4jXmlPath}
        onChange={(e) => setLog4jXmlPath(e.target.value)}
      />

      <button type="submit" disabled={submitting}>
        {submitting ? 'Parsing…' : 'View logs'}
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
      {inProgress && <p>Scanning the logs folder and parsing entries…</p>}
      {job.status === 'failed' && job.error && <p className="error-text">{job.error}</p>}
      {job.status === 'completed' && <LogViewerDashboard job={job} />}
    </div>
  );
}

function LogViewerHistory({ onOpen }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listLogViewJobs()
      .then(setJobs)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading history…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (jobs.length === 0) return <p>No logs viewed yet.</p>;

  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>Job</th>
          <th>Logs folder</th>
          <th>Files</th>
          <th>Entries</th>
          <th>Status</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.id} className="result-row" onClick={() => onOpen(job.id)}>
            <td>#{job.id}</td>
            <td className="url-cell">{job.logs_dir}</td>
            <td>{job.file_count}</td>
            <td>{job.entry_count}</td>
            <td>{job.status}</td>
            <td>{new Date(job.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function LogViewerTool() {
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
        const updated = await getLogViewJob(id);
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
    const opened = await getLogViewJob(id);
    setJob(opened);
    setView('new');
    if (IN_PROGRESS_STATUSES.has(opened.status)) {
      pollJob(opened.id);
    }
  }

  return (
    <div className="log-viewer-tool">
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
      {view === 'history' && <LogViewerHistory onOpen={handleOpenFromHistory} />}
    </div>
  );
}
