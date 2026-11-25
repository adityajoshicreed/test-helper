import { useEffect, useState } from 'react';

const filename = 'karate-passed-only.zip';

export default function KaratePassedReportTool() {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [downloadUrl, setDownloadUrl] = useState('');
  const [error, setError] = useState('');
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    if (!result) {
      setDownloadUrl('');
      return;
    }
    const url = URL.createObjectURL(result.archive);
    setDownloadUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [result]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!file || processing) return;

    setResult(null);
    setError('');
    setProcessing(true);
    try {
      const { filterKarateReport } = await import('../reports/karatePassedReport');
      setResult(await filterKarateReport(file));
    } catch (err) {
      setError(err.message || 'Could not process the Karate report ZIP.');
    } finally {
      setProcessing(false);
    }
  }

  return (
    <>
      <h2>Karate Report Filter</h2>
      <p>Upload a ZIP of your Karate v2 HTML report folder to create a passed-only copy with the original layout.</p>
      <form className="jmeter-form" onSubmit={handleSubmit} aria-busy={processing}>
        <label htmlFor="karate-report-zip">Karate report ZIP</label>
        <input
          id="karate-report-zip"
          type="file"
          accept=".zip,application/zip"
          required
          disabled={processing}
          aria-describedby="karate-report-help"
          onChange={(event) => {
            setFile(event.target.files[0] ?? null);
            setError('');
            setResult(null);
          }}
        />
        <p id="karate-report-help">Include the summary, feature pages, and assets. The ZIP is processed in your browser.</p>
        <button type="submit" disabled={!file || processing}>
          {processing ? 'Filtering report…' : 'Filter report'}
        </button>
        {error && <p role="alert">{error}</p>}
      </form>
      {result && (
        <section className="jmeter-job-status" aria-label="Filtered Karate report">
          <p role="status">{result.passed} passed included · {result.excluded} non-passing excluded</p>
          <p>Extract the ZIP and open <code>karate-summary.html</code>.</p>
          {downloadUrl && <a href={downloadUrl} download={filename}>Download filtered report ZIP</a>}
        </section>
      )}
    </>
  );
}
