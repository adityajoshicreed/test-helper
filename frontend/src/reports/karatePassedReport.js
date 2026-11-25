import { BlobReader, BlobWriter, TextReader, ZipReader, ZipWriter } from '@zip.js/zip.js';

const summaryPage = 'karate-summary.html';
const reportData = /(<script\b[^>]*\sid\s*=\s*["']karate-data["'][^>]*>)([\s\S]*?)(<\/script\s*>)/i;
const timelineLink = /<a\b[^>]*\shref=["'](?:\.\/)?karate-timeline\.html["'][^>]*>[\s\S]*?<\/a>/gi;
const zipOptions = { useWebWorkers: false };

function localPath(value) {
  const parts = value.split('/').filter((part) => part && part !== '.');
  if (!parts.length || value.startsWith('/') || /[\\:]/.test(value) || value.includes('\0') || parts.includes('..')) {
    throw new Error(`Unsupported report path: ${value}`);
  }
  return parts.join('/');
}

async function readHtml(files, name) {
  const entry = files.get(name);
  if (!entry) throw new Error(`Missing ${name}. Upload the complete Karate report folder as a ZIP.`);

  const html = await (await entry.getData(new BlobWriter(), zipOptions)).text();
  const match = reportData.exec(html);
  if (!match) throw new Error(`${name} is missing embedded Karate v2 report data.`);

  let data;
  try {
    data = JSON.parse(match[2]);
  } catch {
    throw new Error(`${name} contains invalid Karate report data.`);
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error(`${name} contains unsupported Karate report data.`);
  }
  return { html, data };
}

function updateHtml(html, data, label) {
  const encoded = JSON.stringify(data).replaceAll('<', '\\u003c');
  return html.replace(reportData, (_, start, _content, end) => start + encoded + end)
    .replace(/<h1\b[^>]*>[\s\S]*?<\/h1>/i, (heading) => (
      `${heading}<p class="my-2 text-sm font-semibold">${label}</p>`
    ));
}

function collectAttachments(value, assets) {
  if (!value || typeof value !== 'object') return;
  if (Array.isArray(value.parts)) {
    for (const part of value.parts) {
      if (typeof part?.mime !== 'string') continue;
      if (typeof part.file === 'string' && part.file) {
        assets.add(`embeds/${localPath(part.file)}`);
      } else if (typeof part.url === 'string' && part.url && !/^(?:[\w+.-]+:|\/\/)/.test(part.url)) {
        assets.add(localPath(decodeURIComponent(part.url.split(/[?#]/, 1)[0])));
      }
    }
  }
  for (const child of Object.values(value)) collectAttachments(child, assets);
}

function summarizeFeature(row, scenarios, durationMillis) {
  return {
    name: row.name,
    relativePath: row.relativePath,
    fileName: row.fileName,
    passed: true,
    failed: false,
    durationMillis,
    scenarioCount: scenarios.length,
    passedCount: scenarios.length,
    failedCount: 0,
    skippedCount: 0,
    passedRate: 100,
    scenarios: scenarios.map(({ name, refId, passed, skipped, durationMillis, tags }) => (
      { name, refId, passed, skipped, durationMillis, tags }
    )),
  };
}

export async function filterKarateReport(archive) {
  const reader = new ZipReader(new BlobReader(archive), zipOptions);
  try {
    const entries = new Map();
    for (const entry of await reader.getEntries()) {
      if (entry.directory) continue;
      const name = localPath(entry.filename);
      if (entries.has(name)) throw new Error(`Duplicate report file: ${name}`);
      entries.set(name, entry);
    }

    const summaries = [...entries.keys()].filter((name) => name.split('/').at(-1) === summaryPage);
    if (summaries.length !== 1) throw new Error(`The ZIP must contain exactly one ${summaryPage}.`);

    const prefix = summaries[0].slice(0, -summaryPage.length);
    const files = new Map([...entries].filter(([name]) => name.startsWith(prefix))
      .map(([name, entry]) => [name.slice(prefix.length), entry]));
    const { html: summaryHtml, data: summaryData } = await readHtml(files, summaryPage);
    if (!Array.isArray(summaryData.features) || !summaryData.summary) {
      throw new Error('Expected a Karate v2 summary with embedded feature results.');
    }

    const assets = new Set([...files.keys()].filter((name) => name.startsWith('res/')));
    for (const name of ['res/karate-report.js', 'res/karate-report.css', 'res/alpine.min.js']) {
      if (!assets.has(name)) throw new Error(`Missing ${name}. Upload the complete Karate report folder as a ZIP.`);
    }

    const output = new ZipWriter(new BlobWriter('application/zip'), zipOptions);
    const features = [];
    let passed = 0;
    let excluded = 0;
    let duration = 0;

    for (const row of summaryData.features) {
      const name = row?.fileName;
      if (typeof name !== 'string' || name.includes('/') || localPath(name) !== name) {
        throw new Error('The summary contains an invalid Karate feature filename.');
      }
      const path = `feature-html/${name}.html`;
      const { html, data } = await readHtml(files, path);
      if (!Array.isArray(data.scenarios) || data.scenarios.some((item) => typeof item?.passed !== 'boolean')) {
        throw new Error(`${path} is missing Karate scenario results.`);
      }

      const scenarios = data.scenarios.filter((item) => item.passed && !item.skipped);
      excluded += data.scenarios.length - scenarios.length;
      if (!scenarios.length) continue;

      const durationMillis = scenarios.reduce((total, item) => total + (item.durationMillis || 0), 0);
      passed += scenarios.length;
      duration += durationMillis;
      features.push(summarizeFeature(row, scenarios, durationMillis));
      collectAttachments(scenarios, assets);
      const featureData = { ...data, passed: true, durationMillis, scenarios };
      delete featureData.failed;
      await output.add(path, new TextReader(updateHtml(html, featureData, 'Passed-only report')));
    }

    const { env, reportDate, karateVersion, threads } = summaryData;
    const summary = {
      env, reportDate, karateVersion, threads, features,
      summary: {
        feature_count: features.length,
        feature_passed: features.length,
        feature_failed: 0,
        scenario_count: passed,
        scenario_passed: passed,
        scenario_failed: 0,
        scenario_skipped: 0,
        duration_millis: duration,
        status: passed ? 'passed' : 'skipped',
      },
    };
    const label = `Passed-only report · ${excluded} non-passing scenarios excluded.`;
    const filteredHtml = updateHtml(summaryHtml.replace(timelineLink, ''), summary, label);
    await output.add(summaryPage, new TextReader(filteredHtml));

    for (const path of assets) {
      const entry = files.get(path);
      if (!entry) throw new Error(`Missing report asset: ${path}`);
      const asset = await entry.getData(new BlobWriter(), zipOptions);
      await output.add(path, new BlobReader(asset));
    }
    return { archive: await output.close(), passed, excluded };
  } finally {
    await reader.close();
  }
}
