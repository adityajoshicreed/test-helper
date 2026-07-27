import { useState } from 'react';
import { importCurl } from '../api/client';

const SAMPLE_CURL = `curl -X POST https://httpbin.org/post \\
  -H 'Content-Type: application/json' \\
  -H 'Authorization: Bearer sample-token' \\
  -d '{"name": "Ada Lovelace", "age": 30, "active": true, "tags": ["math", "cs"]}'`;

export default function CurlImportForm({ onImported }) {
  const [curl, setCurl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!curl.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const imported = await importCurl(curl);
      onImported(imported);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="curl-import-form" onSubmit={handleSubmit}>
      <label htmlFor="curl-input">Paste a curl command</label>
      <textarea
        id="curl-input"
        rows={8}
        value={curl}
        onChange={(e) => setCurl(e.target.value)}
        placeholder={SAMPLE_CURL}
      />
      <div className="curl-import-actions">
        <button type="submit" disabled={loading}>
          {loading ? 'Importing…' : 'Import curl'}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => setCurl(SAMPLE_CURL)}
          disabled={loading}
        >
          Use sample curl
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
    </form>
  );
}
