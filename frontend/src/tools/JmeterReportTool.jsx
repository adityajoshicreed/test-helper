import { useEffect, useRef, useState } from 'react';
import {
  createJmeterReportJob,
  getJmeterReportJob,
  jmeterReportUrl,
  listJmeterReportJobs,
} from '../api/client';

const POLL_INTERVAL_MS = 1000;
const IN_PROGRESS_STATUSES = new Set(['pending', 'running']);

function NewReportForm({ onCreated }) {
  const [csvFile, setCsvFile] = useState(null);
  const [outputDir, setOutputDir] = useState('');
  const [jmeterBin, setJmeterBin] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!csvFile || !outputDir.trim()) {
      setError('Provide both a results CSV/JTL file and an output directory.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('csv_file', csvFile);
      formData.append('output_dir', outputDir.trim());
      if (jmeterBin.trim()) formData.append('jmeter_bin', jmeterBin.trim());
      const job = await createJmeterReportJob(formData);
      onCreated(job);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor="csv-file">JMeter results file (CSV/JTL)</label>
      <input
        id="csv-file"
        type="file"
        accept=".csv,.jtl,.log,.xml"
        onChange={(e) => setCsvFile(e.target.files[0] || null)}
      />

      <label htmlFor="output-dir">Output directory (absolute path — must not already exist, or must be empty)</label>
      <input
        id="output-dir"
        type="text"
        placeholder="/Users/you/reports/run-1"
        value={outputDir}
        onChange={(e) => setOutputDir(e.target.value)}
      />

      <label htmlFor="jmeter-bin">JMeter binary path (optional — leave blank to use "jmeter" on PATH)</label>
      <input
        id="jmeter-bin"
        type="text"
        placeholder="/opt/apache-jmeter-5.6.3/bin/jmeter"
        value={jmeterBin}
        onChange={(e) => setJmeterBin(e.target.value)}
      />

      <button type="submit" disabled={submitting}>
        {submitting ? 'Starting…' : 'Generate report'}
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
      {inProgress && <p>Running JMeter… this can take a while for large result files.</p>}
      {job.command && (
        <details>
          <summary>Command</summary>
          <pre>{job.command}</pre>
        </details>
      )}
      {job.status === 'completed' && (
        <p>
          <a href={jmeterReportUrl(job.id)} target="_blank" rel="noreferrer">
            Open report
          </a>{' '}
          — also written to <code>{job.output_dir}</code>
        </p>
      )}
      {job.status === 'failed' && (
        <>
          {job.error && <p className="error-text">{job.error}</p>}
          {job.stderr && (
            <details open>
              <summary>stderr</summary>
              <pre>{job.stderr}</pre>
            </details>
          )}
          {job.stdout && (
            <details>
              <summary>stdout</summary>
              <pre>{job.stdout}</pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function JmeterHistory({ onOpen }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listJmeterReportJobs()
      .then(setJobs)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading history…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (jobs.length === 0) return <p>No reports generated yet.</p>;

  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>Job</th>
          <th>CSV</th>
          <th>Output dir</th>
          <th>Status</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.id} className="result-row" onClick={() => onOpen(job.id)}>
            <td>#{job.id}</td>
            <td>{job.csv_filename}</td>
            <td className="url-cell">{job.output_dir}</td>
            <td>{job.status}</td>
            <td>{new Date(job.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function JmeterReportTool() {
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
        const updated = await getJmeterReportJob(id);
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
    const opened = await getJmeterReportJob(id);
    setJob(opened);
    setView('new');
    if (IN_PROGRESS_STATUSES.has(opened.status)) {
      pollJob(opened.id);
    }
  }

  return (
    <div className="jmeter-report-tool">
      <nav className="tool-subnav">
        <button className={view === 'new' ? 'active' : ''} onClick={() => setView('new')}>
          New Report
        </button>
        <button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}>
          History
        </button>
      </nav>

      {view === 'new' && (
        <>
          <NewReportForm onCreated={handleCreated} />
          {job && <JobStatus job={job} />}
        </>
      )}
      {view === 'history' && <JmeterHistory onOpen={handleOpenFromHistory} />}
    </div>
  );
}
