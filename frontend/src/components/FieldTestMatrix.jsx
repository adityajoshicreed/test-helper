export default function FieldTestMatrix({ title, hint, keyLabel, items, selected, onToggle, onSelectAll, onSelectNone }) {
  if (items.length === 0) return null;

  const allCodes = [];
  const labelByCode = {};
  for (const item of items) {
    for (const test of item.tests) {
      if (!(test.code in labelByCode)) {
        allCodes.push(test.code);
        labelByCode[test.code] = test.label;
      }
    }
  }

  return (
    <fieldset className="field-test-matrix">
      <legend>{title}</legend>
      <p className="group-hint">{hint}</p>
      <div className="matrix-actions">
        <button type="button" onClick={onSelectAll}>Select all</button>
        <button type="button" onClick={onSelectNone}>Select none</button>
      </div>
      <div className="matrix-scroll">
        <table className="matrix-table">
          <thead>
            <tr>
              <th>{keyLabel}</th>
              {allCodes.map((code) => (
                <th key={code}>{labelByCode[code]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const applicableCodes = new Set(item.tests.map((t) => t.code));
              const selectedCodes = selected.get(item.name) || new Set();
              return (
                <tr key={item.name}>
                  <td className="matrix-row-label">{item.name}</td>
                  {allCodes.map((code) => (
                    <td key={code} className="matrix-cell">
                      {applicableCodes.has(code) ? (
                        <input
                          type="checkbox"
                          checked={selectedCodes.has(code)}
                          onChange={() => onToggle(item.name, code)}
                        />
                      ) : (
                        <span className="na-dash">—</span>
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </fieldset>
  );
}
