import { useEffect, useState } from 'react';
import LineChart from '../components/charts/LineChart';
import {
  addPlannedLoadTest,
  createLoadTestPlan,
  getLoadTestPlan,
  listLoadTestPlans,
  recordLoadTestResult,
} from '../api/client';

function NewPlanForm({ onCreated }) {
  const [name, setName] = useState('');
  const [apiName, setApiName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!name.trim()) {
      setError('Provide a name for the plan.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const plan = await createLoadTestPlan({ name: name.trim(), api_name: apiName.trim() });
      onCreated(plan);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor="plan-name">Plan name</label>
      <input
        id="plan-name"
        type="text"
        placeholder="Checkout API load test plan"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <label htmlFor="plan-api-name">API under test (optional)</label>
      <input
        id="plan-api-name"
        type="text"
        placeholder="checkout-service"
        value={apiName}
        onChange={(e) => setApiName(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Create plan'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function AddPlannedTestForm({ planId, nextOrder, onAdded }) {
  const [name, setName] = useState('');
  const [durationMinutes, setDurationMinutes] = useState('');
  const [tps, setTps] = useState('');
  const [jmeterFilename, setJmeterFilename] = useState('');
  const [metricsFilename, setMetricsFilename] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const test = await addPlannedLoadTest(planId, {
        name: name.trim(),
        planned_duration_minutes: Number(durationMinutes),
        planned_tps: Number(tps),
        jmeter_csv_filename: jmeterFilename.trim(),
        server_metrics_csv_filename: metricsFilename.trim(),
      });
      onAdded(test);
      setName('');
      setDurationMinutes('');
      setTps('');
      setJmeterFilename('');
      setMetricsFilename('');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor={`test-name-${nextOrder}`}>Test #{nextOrder} name</label>
      <input
        id={`test-name-${nextOrder}`}
        type="text"
        placeholder="50 concurrent users, 10 min soak"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <label htmlFor={`test-duration-${nextOrder}`}>Planned duration (minutes)</label>
      <input
        id={`test-duration-${nextOrder}`}
        type="number"
        placeholder="10"
        value={durationMinutes}
        onChange={(e) => setDurationMinutes(e.target.value)}
      />
      <label htmlFor={`test-tps-${nextOrder}`}>Planned TPS</label>
      <input
        id={`test-tps-${nextOrder}`}
        type="number"
        placeholder="50"
        value={tps}
        onChange={(e) => setTps(e.target.value)}
      />
      <label htmlFor={`test-jmeter-filename-${nextOrder}`}>Planned JMeter output CSV filename (optional, just a reminder)</label>
      <input
        id={`test-jmeter-filename-${nextOrder}`}
        type="text"
        placeholder="results-test1.csv"
        value={jmeterFilename}
        onChange={(e) => setJmeterFilename(e.target.value)}
      />
      <label htmlFor={`test-metrics-filename-${nextOrder}`}>Planned server metrics CSV filename (optional)</label>
      <input
        id={`test-metrics-filename-${nextOrder}`}
        type="text"
        placeholder="metrics-test1.csv"
        value={metricsFilename}
        onChange={(e) => setMetricsFilename(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? 'Adding…' : 'Add planned test'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function RecordResultForm({ testId, onRecorded }) {
  const [jmeterFile, setJmeterFile] = useState(null);
  const [metricsFile, setMetricsFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!jmeterFile || !metricsFile) {
      setError('Provide both the JMeter results CSV and the server metrics CSV.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const updated = await recordLoadTestResult(testId, jmeterFile, metricsFile);
      onRecorded(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor={`jmeter-csv-${testId}`}>JMeter results CSV (raw per-sample output)</label>
      <input
        id={`jmeter-csv-${testId}`}
        type="file"
        accept=".csv,.jtl,.log"
        onChange={(e) => setJmeterFile(e.target.files[0] || null)}
      />
      <label htmlFor={`metrics-csv-${testId}`}>Server metrics CSV (Timestamp, CPU_Usage_Percent, RAM_USAGE_PERCENT)</label>
      <input
        id={`metrics-csv-${testId}`}
        type="file"
        accept=".csv"
        onChange={(e) => setMetricsFile(e.target.files[0] || null)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? 'Processing…' : 'Record results'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function StatTile({ label, value, sub }) {
  return (
    <div className="stat-tile">
      <p className="stat-tile-label">{label}</p>
      <p className="stat-tile-value">{value}</p>
      {sub && <p className="stat-tile-sub">{sub}</p>}
    </div>
  );
}

function msFormat(v) {
  return `${Math.round(v)}`;
}
function tpsFormat(v) {
  return v.toFixed(1);
}
function percentFormat(v) {
  return `${Math.round(v)}%`;
}
function minutesFormat(v) {
  return `${v.toFixed(1)}m`;
}

function LoadTestDashboard({ test }) {
  const result = test.result;
  if (!result) return null;

  return (
    <div>
      {result.warnings?.length > 0 && (
        <p className="dynamic-headers-note">⚠ {result.warnings.join(' ')}</p>
      )}
      <div className="stat-tile-row">
        <StatTile label="Samples" value={result.sample_count} sub={`${result.error_count} errors`} />
        <StatTile
          label="Error rate"
          value={result.error_rate_percent != null ? `${result.error_rate_percent}%` : '—'}
        />
        <StatTile
          label="Actual TPS"
          value={result.actual_tps != null ? result.actual_tps.toFixed(2) : '—'}
          sub={`planned ${test.planned_tps}`}
        />
        <StatTile
          label="Actual duration"
          value={result.actual_duration_seconds != null ? `${(result.actual_duration_seconds / 60).toFixed(1)}m` : '—'}
          sub={`planned ${test.planned_duration_minutes}m`}
        />
        <StatTile label="Avg response" value={result.avg_response_time_ms != null ? `${msFormat(result.avg_response_time_ms)} ms` : '—'} />
        <StatTile label="p95 response" value={result.p95_response_time_ms != null ? `${msFormat(result.p95_response_time_ms)} ms` : '—'} />
        <StatTile label="p99 response" value={result.p99_response_time_ms != null ? `${msFormat(result.p99_response_time_ms)} ms` : '—'} />
      </div>

      <LineChart
        title="Response time (ms)"
        xLabel="Minutes elapsed"
        yLabel="ms"
        xFormat={minutesFormat}
        yFormat={msFormat}
        series={[
          { name: 'Avg', color: 'var(--chart-blue)', points: result.response_time_series.map((p) => ({ x: p.t, y: p.avg })) },
          { name: 'p95', color: 'var(--chart-orange)', points: result.response_time_series.map((p) => ({ x: p.t, y: p.p95 })) },
        ]}
      />

      <LineChart
        title="Throughput (TPS)"
        xLabel="Minutes elapsed"
        yLabel="req/s"
        xFormat={minutesFormat}
        yFormat={tpsFormat}
        series={[
          { name: 'TPS', color: 'var(--chart-blue)', points: result.throughput_series.map((p) => ({ x: p.t, y: p.tps })) },
        ]}
      />

      <LineChart
        title="Server CPU / RAM (%)"
        xLabel="Minutes elapsed"
        yLabel="%"
        xFormat={minutesFormat}
        yFormat={percentFormat}
        series={[
          { name: 'CPU', color: 'var(--chart-blue)', points: result.cpu_ram_series.map((p) => ({ x: p.t, y: p.cpu_percent })) },
          { name: 'RAM', color: 'var(--chart-aqua)', points: result.cpu_ram_series.map((p) => ({ x: p.t, y: p.ram_percent })) },
        ]}
      />
    </div>
  );
}

function PlannedTestRow({ test, onRecorded }) {
  return (
    <div className="curl-import-form">
      <div className="chain-header">
        <h3>
          #{test.order} {test.name}
        </h3>
        <span className="tool-badge">{test.status}</span>
      </div>
      <p className="group-hint">
        Planned: {test.planned_duration_minutes}m at {test.planned_tps} TPS
        {test.jmeter_csv_filename && <> — JMeter file: <code>{test.jmeter_csv_filename}</code></>}
        {test.server_metrics_csv_filename && <> — metrics file: <code>{test.server_metrics_csv_filename}</code></>}
      </p>
      {test.status === 'planned' && (
        <RecordResultForm testId={test.id} onRecorded={onRecorded} />
      )}
      {test.status === 'recorded' && <LoadTestDashboard test={test} />}
    </div>
  );
}

function LoadTestHistory({ onOpen }) {
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listLoadTestPlans()
      .then(setPlans)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading history…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (plans.length === 0) return <p>No plans yet.</p>;

  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>Plan</th>
          <th>API</th>
          <th>Tests</th>
          <th>Recorded</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {plans.map((plan) => (
          <tr key={plan.id} className="result-row" onClick={() => onOpen(plan.id)}>
            <td>{plan.name}</td>
            <td>{plan.api_name || '—'}</td>
            <td>{plan.test_count}</td>
            <td>{plan.recorded_count}</td>
            <td>{new Date(plan.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function LoadTestTrackerTool() {
  const [view, setView] = useState('build');
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState(null);

  function handlePlanCreated(newPlan) {
    setError(null);
    setPlan(newPlan);
  }

  function handleNewPlan() {
    setError(null);
    setPlan(null);
  }

  function handleTestAdded(test) {
    setPlan((prev) => ({ ...prev, tests: [...prev.tests, test] }));
  }

  function handleTestRecorded(updatedTest) {
    setPlan((prev) => ({
      ...prev,
      tests: prev.tests.map((t) => (t.id === updatedTest.id ? updatedTest : t)),
    }));
  }

  async function handleOpenFromHistory(planId) {
    setError(null);
    try {
      const fullPlan = await getLoadTestPlan(planId);
      setPlan(fullPlan);
      setView('build');
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="load-test-tracker-tool">
      <nav className="tool-subnav">
        <button className={view === 'build' ? 'active' : ''} onClick={() => setView('build')}>
          Build &amp; Record
        </button>
        <button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}>
          History
        </button>
      </nav>

      {view === 'build' && (
        <>
          {!plan && <NewPlanForm onCreated={handlePlanCreated} />}

          {plan && (
            <>
              <div className="chain-header">
                <h2>{plan.name}</h2>
                <button type="button" className="secondary" onClick={handleNewPlan}>
                  + New plan
                </button>
              </div>
              {plan.api_name && <p className="group-hint">API: {plan.api_name}</p>}

              {plan.tests.map((test) => (
                <PlannedTestRow key={test.id} test={test} onRecorded={handleTestRecorded} />
              ))}

              <AddPlannedTestForm planId={plan.id} nextOrder={plan.tests.length + 1} onAdded={handleTestAdded} />
            </>
          )}

          {error && <p className="error-text">{error}</p>}
        </>
      )}

      {view === 'history' && <LoadTestHistory onOpen={handleOpenFromHistory} />}
    </div>
  );
}
