import { Fragment, useEffect, useState } from 'react';
import { listLogEntries } from '../api/client';

const LEVELS = ['TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'];
const PAGE_SIZE = 100;
const SEARCH_DEBOUNCE_MS = 400;

function LevelBadge({ level }) {
  const cls = level ? level.toLowerCase() : 'unknown';
  return <span className={`log-level-badge log-level-${cls}`}>{level || '—'}</span>;
}

function formatTimestamp(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

export default function LogViewerDashboard({ job }) {
  const [levels, setLevels] = useState([]);
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');
  const [logger, setLogger] = useState('');
  const [quickFilter, setQuickFilter] = useState(''); // '' | 'request' | 'response'
  const [sort, setSort] = useState('timestamp');
  const [order, setOrder] = useState('asc');
  const [page, setPage] = useState(1);

  const [entries, setEntries] = useState([]);
  const [count, setCount] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    const handle = setTimeout(() => {
      setSearch(searchDraft);
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchDraft]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listLogEntries(job.id, {
      level: levels.join(','),
      search,
      logger,
      filter: quickFilter,
      sort,
      order,
      page,
      page_size: PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) return;
        setEntries(data.results);
        setCount(data.count);
        setTotalPages(data.total_pages);
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [job.id, levels, search, logger, quickFilter, sort, order, page]);

  function toggleLevel(level) {
    setLevels((prev) => (prev.includes(level) ? prev.filter((l) => l !== level) : [...prev, level]));
    setPage(1);
  }

  function handleQuickFilter(value) {
    setQuickFilter((prev) => (prev === value ? '' : value));
    setPage(1);
  }

  function handleLoggerChange(value) {
    setLogger(value);
    setPage(1);
  }

  return (
    <div className="log-viewer-dashboard">
      <div className="log-viewer-summary">
        <span className="summary-item">
          <strong>{job.file_count}</strong> file{job.file_count === 1 ? '' : 's'}
        </span>
        <span className="summary-item">
          <strong>{job.entry_count}</strong> entr{job.entry_count === 1 ? 'y' : 'ies'} parsed
        </span>
        <span className="summary-item log-pattern-note">
          {job.pattern_source === 'log4j_xml'
            ? 'Using the pattern from your log4j XML'
            : "No usable log4j XML pattern — using Spring Boot's default log format"}
        </span>
      </div>

      {job.warnings?.length > 0 && (
        <details className="log-viewer-warnings">
          <summary>Warnings ({job.warnings.length})</summary>
          <pre>{job.warnings.join('\n')}</pre>
        </details>
      )}

      <div className="log-viewer-toolbar">
        <input
          type="text"
          className="log-search-input"
          placeholder="Search message, logger, thread…"
          value={searchDraft}
          onChange={(e) => setSearchDraft(e.target.value)}
        />

        <input
          type="text"
          className="log-logger-input"
          placeholder="Filter by logger…"
          value={logger}
          onChange={(e) => handleLoggerChange(e.target.value)}
        />

        <div className="log-level-filters">
          {LEVELS.map((level) => (
            <label key={level} className={`log-level-chip log-level-${level.toLowerCase()}`}>
              <input type="checkbox" checked={levels.includes(level)} onChange={() => toggleLevel(level)} />
              {level}
            </label>
          ))}
        </div>

        <div className="log-quick-filters">
          <button
            type="button"
            className={quickFilter === 'request' ? 'active' : 'secondary'}
            onClick={() => handleQuickFilter('request')}
          >
            Requests
          </button>
          <button
            type="button"
            className={quickFilter === 'response' ? 'active' : 'secondary'}
            onClick={() => handleQuickFilter('response')}
          >
            Responses
          </button>
        </div>

        <div className="log-sort-controls">
          <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
            <option value="timestamp">Sort: Time</option>
            <option value="seq">Sort: Original order</option>
          </select>
          <button
            type="button"
            className="secondary"
            onClick={() => { setOrder((o) => (o === 'asc' ? 'desc' : 'asc')); setPage(1); }}
          >
            {order === 'asc' ? '↑ Oldest first' : '↓ Newest first'}
          </button>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}

      <table className="results-table log-table">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Level</th>
            <th>Thread</th>
            <th>Logger</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const isMultiline = entry.message.includes('\n');
            const firstLine = entry.message.split('\n')[0];
            return (
              <Fragment key={entry.id}>
                <tr
                  className="result-row"
                  onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                >
                  <td className="log-timestamp-cell">{formatTimestamp(entry.timestamp)}</td>
                  <td><LevelBadge level={entry.level} /></td>
                  <td>{entry.thread}</td>
                  <td className="log-logger-cell">{entry.logger}</td>
                  <td className="log-message-cell">
                    {firstLine}
                    {isMultiline && <span className="log-message-more"> …</span>}
                  </td>
                </tr>
                {expandedId === entry.id && (
                  <tr className="result-detail-row">
                    <td colSpan={5}>
                      <pre className="log-message-detail">{entry.message}</pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>

      {!loading && entries.length === 0 && <p>No log entries match the current filters.</p>}

      <div className="pagination-controls">
        <button type="button" className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          ← Prev
        </button>
        <span>
          Page {page} of {totalPages} ({count} entr{count === 1 ? 'y' : 'ies'})
        </span>
        <button
          type="button"
          className="secondary"
          disabled={page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
        >
          Next →
        </button>
      </div>
    </div>
  );
}
