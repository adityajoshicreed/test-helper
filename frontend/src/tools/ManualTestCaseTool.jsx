import { useEffect, useState } from 'react';
import {
  addManualTestCase,
  addManualTestStep,
  createManualTestSuite,
  exportManualTestSuiteExcel,
  getManualTestSuite,
  listManualTestSuites,
} from '../api/client';

const CASE_FIELDS = [
  { key: 'environment', label: 'Environment', placeholder: 'QA' },
  { key: 'pre_requisite', label: 'Pre-Requisite', placeholder: 'User must be logged in' },
  { key: 'created_by', label: 'Created By', placeholder: 'Your name' },
  { key: 'sprint', label: 'Sprint', placeholder: 'Sprint 24' },
  { key: 'lob', label: 'LOB', placeholder: 'Payments' },
  { key: 'vertical', label: 'Vertical', placeholder: 'Retail' },
  { key: 'feasible_for_automation', label: 'Feasible for Automation?', placeholder: 'Yes' },
  { key: 'test_case_applicability', label: 'Test Case Applicability', placeholder: 'Regression' },
  { key: 'labels', label: 'Labels', placeholder: 'smoke, api' },
  { key: 'test_case_status', label: 'Status', placeholder: 'Active' },
];

const EMPTY_CASE_FIELDS = CASE_FIELDS.reduce((acc, f) => ({ ...acc, [f.key]: '' }), {});

function NewSuiteForm({ onCreated }) {
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const suite = await createManualTestSuite(name.trim());
      onCreated(suite);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor="suite-name">Suite name (optional)</label>
      <input
        id="suite-name"
        type="text"
        placeholder="Checkout API test cases"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Start building a suite'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function AddCaseForm({ suiteId, nextOrder, onAdded }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [fields, setFields] = useState(EMPTY_CASE_FIELDS);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  function setField(key, value) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!name.trim()) {
      setError('Provide a name for the test case.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload = { name: name.trim(), description: description.trim() };
      for (const f of CASE_FIELDS) payload[f.key] = fields[f.key].trim();
      const testCase = await addManualTestCase(suiteId, payload);
      onAdded(testCase);
      setName('');
      setDescription('');
      setFields(EMPTY_CASE_FIELDS);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <h3>Add test case #{nextOrder}</h3>
      <label htmlFor={`case-name-${nextOrder}`}>Test Case Name</label>
      <input
        id={`case-name-${nextOrder}`}
        type="text"
        placeholder="Login with valid credentials"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />

      <label htmlFor={`case-description-${nextOrder}`}>Test Case Description</label>
      <textarea
        id={`case-description-${nextOrder}`}
        rows={2}
        placeholder="Verify a user with valid credentials can log in"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />

      {CASE_FIELDS.map((f) => (
        <div key={f.key}>
          <label htmlFor={`case-${f.key}-${nextOrder}`}>{f.label}</label>
          <input
            id={`case-${f.key}-${nextOrder}`}
            type="text"
            placeholder={f.placeholder}
            value={fields[f.key]}
            onChange={(e) => setField(f.key, e.target.value)}
          />
        </div>
      ))}

      <button type="submit" disabled={submitting}>
        {submitting ? 'Adding…' : 'Add test case'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function AddStepForm({ caseId, nextOrder, onAdded }) {
  const [description, setDescription] = useState('');
  const [testData, setTestData] = useState('');
  const [expectedResult, setExpectedResult] = useState('');
  const [actualResult, setActualResult] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (![description, testData, expectedResult, actualResult].some((v) => v.trim())) {
      setError('Fill in at least one of Step Description / Test Data / Expected Result / Actual Result.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const step = await addManualTestStep(caseId, {
        description: description.trim(),
        test_data: testData.trim(),
        expected_result: expectedResult.trim(),
        actual_result: actualResult.trim(),
      });
      onAdded(step);
      setDescription('');
      setTestData('');
      setExpectedResult('');
      setActualResult('');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="jmeter-form" onSubmit={handleSubmit}>
      <label htmlFor={`step-description-${caseId}-${nextOrder}`}>Step {nextOrder} — Step Description</label>
      <input
        id={`step-description-${caseId}-${nextOrder}`}
        type="text"
        placeholder="Enter valid username and password, click Login"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />

      <label htmlFor={`step-testdata-${caseId}-${nextOrder}`}>Test Data</label>
      <textarea
        id={`step-testdata-${caseId}-${nextOrder}`}
        rows={2}
        placeholder="username=alice, password=Secret123"
        value={testData}
        onChange={(e) => setTestData(e.target.value)}
      />

      <label htmlFor={`step-expected-${caseId}-${nextOrder}`}>Expected Result</label>
      <textarea
        id={`step-expected-${caseId}-${nextOrder}`}
        rows={2}
        placeholder="User is redirected to the dashboard"
        value={expectedResult}
        onChange={(e) => setExpectedResult(e.target.value)}
      />

      <label htmlFor={`step-actual-${caseId}-${nextOrder}`}>Actual Result (optional — fill in as you test)</label>
      <textarea
        id={`step-actual-${caseId}-${nextOrder}`}
        rows={2}
        value={actualResult}
        onChange={(e) => setActualResult(e.target.value)}
      />

      <button type="submit" disabled={submitting}>
        {submitting ? 'Adding…' : 'Add step'}
      </button>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}

function StepTable({ steps }) {
  if (steps.length === 0) return <p className="group-hint">No steps yet — add one below.</p>;
  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Step Description</th>
          <th>Test Data</th>
          <th>Expected Result</th>
          <th>Actual Result</th>
        </tr>
      </thead>
      <tbody>
        {steps.map((step) => (
          <tr key={step.id}>
            <td>{step.order}</td>
            <td>{step.description}</td>
            <td>{step.test_data}</td>
            <td>{step.expected_result}</td>
            <td>{step.actual_result}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TestCaseCard({ testCase, onStepAdded }) {
  const [expanded, setExpanded] = useState(true);
  return (
    <div className="curl-import-form">
      <div className="chain-header">
        <h3>
          #{testCase.order} {testCase.name}
        </h3>
        <button type="button" className="secondary" onClick={() => setExpanded((v) => !v)}>
          {expanded ? 'Collapse' : 'Expand'}
        </button>
      </div>
      {testCase.description && <p className="group-hint">{testCase.description}</p>}
      {expanded && (
        <>
          <p className="group-hint">
            {[
              testCase.environment && `Environment: ${testCase.environment}`,
              testCase.sprint && `Sprint: ${testCase.sprint}`,
              testCase.labels && `Labels: ${testCase.labels}`,
              testCase.test_case_status && `Status: ${testCase.test_case_status}`,
            ]
              .filter(Boolean)
              .join(' · ') || 'No optional metadata set for this case.'}
          </p>
          <StepTable steps={testCase.steps} />
          <AddStepForm
            caseId={testCase.id}
            nextOrder={testCase.steps.length + 1}
            onAdded={(step) => onStepAdded(testCase.id, step)}
          />
        </>
      )}
    </div>
  );
}

function ExportSuiteForm({ suiteId }) {
  const [open, setOpen] = useState(false);
  const [excelPath, setExcelPath] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!excelPath.trim()) {
      setError('Provide where the Excel file should be saved.');
      return;
    }
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const response = await exportManualTestSuiteExcel(suiteId, excelPath.trim());
      setResult(response);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="secondary export-excel-toggle" onClick={() => setOpen(true)}>
        Export to Excel
      </button>
    );
  }

  return (
    <form className="jmeter-form export-excel-form" onSubmit={handleSubmit}>
      <label htmlFor="manual-export-excel-path">Excel file location (absolute path, ending in .xlsx)</label>
      <input
        id="manual-export-excel-path"
        type="text"
        placeholder="/Users/you/testcases/manual-test-cases.xlsx"
        value={excelPath}
        onChange={(e) => setExcelPath(e.target.value)}
      />
      <div className="export-excel-actions">
        <button type="submit" disabled={submitting}>
          {submitting ? 'Exporting…' : 'Export'}
        </button>
        <button type="button" className="secondary" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {result && (
        <p className="export-excel-success">
          Exported {result.exported_case_count} test case{result.exported_case_count === 1 ? '' : 's'} (
          {result.exported_step_count} step{result.exported_step_count === 1 ? '' : 's'}) to{' '}
          <code>{result.excel_path}</code>
        </p>
      )}
    </form>
  );
}

function ManualTestHistory({ onOpen }) {
  const [suites, setSuites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listManualTestSuites()
      .then(setSuites)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading history…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (suites.length === 0) return <p>No test suites yet.</p>;

  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>Suite</th>
          <th>Test cases</th>
          <th>Steps</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {suites.map((suite) => (
          <tr key={suite.id} className="result-row" onClick={() => onOpen(suite.id)}>
            <td>{suite.name || `Suite #${suite.id}`}</td>
            <td>{suite.test_case_count}</td>
            <td>{suite.step_count}</td>
            <td>{new Date(suite.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ManualTestCaseTool() {
  const [view, setView] = useState('build'); // 'build' | 'history'
  const [suite, setSuite] = useState(null);
  const [error, setError] = useState(null);

  function handleSuiteCreated(newSuite) {
    setError(null);
    setSuite(newSuite);
  }

  function handleNewSuite() {
    setError(null);
    setSuite(null);
  }

  function handleCaseAdded(testCase) {
    setSuite((prev) => ({ ...prev, test_cases: [...prev.test_cases, { ...testCase, steps: [] }] }));
  }

  function handleStepAdded(caseId, step) {
    setSuite((prev) => ({
      ...prev,
      test_cases: prev.test_cases.map((tc) => (tc.id === caseId ? { ...tc, steps: [...tc.steps, step] } : tc)),
    }));
  }

  async function handleOpenFromHistory(suiteId) {
    setError(null);
    try {
      const fullSuite = await getManualTestSuite(suiteId);
      setSuite(fullSuite);
      setView('build');
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="manual-test-case-tool">
      <nav className="tool-subnav">
        <button className={view === 'build' ? 'active' : ''} onClick={() => setView('build')}>
          Build
        </button>
        <button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}>
          History
        </button>
      </nav>

      {view === 'build' && (
        <>
          {!suite && <NewSuiteForm onCreated={handleSuiteCreated} />}

          {suite && (
            <>
              <div className="chain-header">
                <h2>{suite.name || `Suite #${suite.id}`}</h2>
                <div className="export-excel-actions">
                  <ExportSuiteForm suiteId={suite.id} />
                  <button type="button" className="secondary" onClick={handleNewSuite}>
                    + New suite
                  </button>
                </div>
              </div>

              {suite.test_cases.map((testCase) => (
                <TestCaseCard key={testCase.id} testCase={testCase} onStepAdded={handleStepAdded} />
              ))}

              <AddCaseForm suiteId={suite.id} nextOrder={suite.test_cases.length + 1} onAdded={handleCaseAdded} />
            </>
          )}

          {error && <p className="error-text">{error}</p>}
        </>
      )}

      {view === 'history' && <ManualTestHistory onOpen={handleOpenFromHistory} />}
    </div>
  );
}
