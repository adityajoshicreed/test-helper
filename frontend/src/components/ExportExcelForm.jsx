import { useState } from 'react';
import { exportTestRunExcel } from '../api/client';

const FIELDS = [
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

const EMPTY_VALUES = FIELDS.reduce((acc, f) => ({ ...acc, [f.key]: '' }), {});

export default function ExportExcelForm({ testRunId, executedCount }) {
  const [open, setOpen] = useState(false);
  const [excelPath, setExcelPath] = useState('');
  const [values, setValues] = useState(EMPTY_VALUES);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  function setField(key, value) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

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
      const payload = { excel_path: excelPath.trim() };
      for (const f of FIELDS) payload[f.key] = values[f.key].trim();
      const response = await exportTestRunExcel(testRunId, payload);
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
      <p className="group-hint">
        Exports the {executedCount} executed test case{executedCount === 1 ? '' : 's'} from this run into the
        same Excel format the Karate Test Case Generator produces.
      </p>

      <label htmlFor="export-excel-path">Excel file location (absolute path, ending in .xlsx)</label>
      <input
        id="export-excel-path"
        type="text"
        placeholder="/Users/you/testcases/api-test-cases.xlsx"
        value={excelPath}
        onChange={(e) => setExcelPath(e.target.value)}
      />

      {FIELDS.map((f) => (
        <div key={f.key}>
          <label htmlFor={`export-${f.key}`}>{f.label}</label>
          <input
            id={`export-${f.key}`}
            type="text"
            placeholder={f.placeholder}
            value={values[f.key]}
            onChange={(e) => setField(f.key, e.target.value)}
          />
        </div>
      ))}

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
          Exported {result.exported_case_count} test case{result.exported_case_count === 1 ? '' : 's'} to{' '}
          <code>{result.excel_path}</code>
        </p>
      )}
    </form>
  );
}
