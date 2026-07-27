import { useState } from 'react';
import FieldTestMatrix from './FieldTestMatrix';

function defaultSelection(options, keyName) {
  const map = new Map();
  for (const opt of options) {
    map.set(opt[keyName], new Set(opt.tests.map((t) => t.code)));
  }
  return map;
}

function emptySelection(options, keyName) {
  const map = new Map();
  for (const opt of options) {
    map.set(opt[keyName], new Set());
  }
  return map;
}

function toggleInMap(map, name, code) {
  const next = new Map(map);
  const set = new Set(next.get(name) || []);
  if (set.has(code)) set.delete(code);
  else set.add(code);
  next.set(name, set);
  return next;
}

function countSelected(map) {
  let total = 0;
  for (const set of map.values()) total += set.size;
  return total;
}

export default function ParsedRequestView({ importedRequest, onRunTests, running }) {
  const bodyOptions = importedRequest.body_field_options || [];
  const headerOptions = importedRequest.header_field_options || [];
  const blanketCategories = importedRequest.available_test_categories.filter(
    (c) => c.code !== 'baseline'
  );

  const [bodyFieldSelected, setBodyFieldSelected] = useState(() => defaultSelection(bodyOptions, 'field'));
  const [headerSelected, setHeaderSelected] = useState(() => defaultSelection(headerOptions, 'header'));
  const [blanketSelected, setBlanketSelected] = useState(() => {
    const initial = new Set();
    for (const cat of blanketCategories) {
      if (cat.applicable) initial.add(cat.code);
    }
    return initial;
  });

  function toggleBlanket(code) {
    setBlanketSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  const totalSelected =
    countSelected(bodyFieldSelected) + countSelected(headerSelected) + blanketSelected.size;

  function handleRun() {
    const body_field_tests = {};
    for (const [field, codes] of bodyFieldSelected) {
      if (codes.size) body_field_tests[field] = Array.from(codes);
    }
    const header_tests = {};
    for (const [header, codes] of headerSelected) {
      if (codes.size) header_tests[header] = Array.from(codes);
    }
    onRunTests({
      categories: Array.from(blanketSelected),
      body_field_tests,
      header_tests,
    });
  }

  const bodyPreview = importedRequest.is_json_body
    ? JSON.stringify(importedRequest.body, null, 2)
    : importedRequest.body_raw || '(no body)';

  return (
    <div className="parsed-request-view">
      <h2>Parsed request</h2>
      <div className="parsed-summary">
        <span className={`method-badge method-${importedRequest.method}`}>
          {importedRequest.method}
        </span>
        <span className="url-text">{importedRequest.url}</span>
      </div>

      <details>
        <summary>Headers ({Object.keys(importedRequest.headers).length})</summary>
        <pre>{JSON.stringify(importedRequest.headers, null, 2)}</pre>
      </details>

      {importedRequest.dynamic_headers?.length > 0 && (
        <p className="dynamic-headers-note">
          ⚡ Detected per-request header{importedRequest.dynamic_headers.length > 1 ? 's' : ''}:{' '}
          {importedRequest.dynamic_headers.map((h) => (
            <code key={h}>{h}</code>
          ))}
          . A fresh value is generated for each test case so requests aren't rejected as duplicates —
          except in the specific test that removes or empties that header on purpose.
        </p>
      )}

      <details>
        <summary>Body</summary>
        <pre>{bodyPreview}</pre>
      </details>

      <h3>Select tests to run</h3>

      <FieldTestMatrix
        title="Body field tests"
        hint="Pick which mutations to run on which fields."
        keyLabel="Field"
        items={bodyOptions.map((o) => ({ name: o.field, tests: o.tests }))}
        selected={bodyFieldSelected}
        onToggle={(name, code) => setBodyFieldSelected((prev) => toggleInMap(prev, name, code))}
        onSelectAll={() => setBodyFieldSelected(defaultSelection(bodyOptions, 'field'))}
        onSelectNone={() => setBodyFieldSelected(emptySelection(bodyOptions, 'field'))}
      />

      <FieldTestMatrix
        title="Header tests"
        hint="Pick which mutations to run on which headers."
        keyLabel="Header"
        items={headerOptions.map((o) => ({ name: o.header, tests: o.tests }))}
        selected={headerSelected}
        onToggle={(name, code) => setHeaderSelected((prev) => toggleInMap(prev, name, code))}
        onSelectAll={() => setHeaderSelected(defaultSelection(headerOptions, 'header'))}
        onSelectNone={() => setHeaderSelected(emptySelection(headerOptions, 'header'))}
      />

      {blanketCategories.length > 0 && (
        <fieldset>
          <legend>Whole-request tests</legend>
          <p className="group-hint">Blanket tests that don't target a specific field.</p>
          {blanketCategories.map((cat) => (
            <label key={cat.code} className={cat.applicable ? '' : 'disabled'}>
              <input
                type="checkbox"
                checked={blanketSelected.has(cat.code)}
                disabled={!cat.applicable}
                onChange={() => toggleBlanket(cat.code)}
              />
              {cat.label}
              {!cat.applicable && <span className="na-tag"> (not applicable)</span>}
            </label>
          ))}
        </fieldset>
      )}

      <button className="run-button" disabled={running || totalSelected === 0} onClick={handleRun}>
        {running ? 'Running tests…' : `Run ${totalSelected} test${totalSelected === 1 ? '' : 's'}`}
      </button>
    </div>
  );
}
