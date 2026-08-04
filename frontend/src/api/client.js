const BASE_URL = 'http://localhost:8000/api';

async function request(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    // Never set Content-Type ourselves for FormData -- the browser needs to
    // add its own multipart boundary, which we'd clobber by setting it here.
    headers: isFormData ? options.headers : { 'Content-Type': 'application/json', ...options.headers },
  });
  const isJson = response.headers.get('content-type')?.includes('application/json');
  const data = isJson ? await response.json() : null;
  if (!response.ok) {
    const message = data?.error || `Request failed with status ${response.status}`;
    throw new Error(message);
  }
  return data;
}

export function importCurl(curl) {
  return request('/import-curl/', {
    method: 'POST',
    body: JSON.stringify({ curl }),
  });
}

export function listImportedRequests() {
  return request('/imported-requests/');
}

export function getImportedRequest(id) {
  return request(`/imported-requests/${id}/`);
}

export function createTestRun(importedRequestId, selection) {
  return request(`/imported-requests/${importedRequestId}/test-runs/`, {
    method: 'POST',
    body: JSON.stringify(selection),
  });
}

export function listTestRuns() {
  return request('/test-runs/');
}

export function getTestRun(id) {
  return request(`/test-runs/${id}/`);
}

export function stopTestRun(id) {
  return request(`/test-runs/${id}/stop/`, { method: 'POST' });
}

export function exportTestRunExcel(id, payload) {
  return request(`/test-runs/${id}/export-excel/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createJmeterReportJob(formData) {
  return request('/jmeter/jobs/', {
    method: 'POST',
    body: formData,
  });
}

export function listJmeterReportJobs() {
  return request('/jmeter/jobs/');
}

export function getJmeterReportJob(id) {
  return request(`/jmeter/jobs/${id}/`);
}

export function jmeterReportUrl(id) {
  return `${BASE_URL}/jmeter/jobs/${id}/report/`;
}

export function createKarateJob(payload) {
  return request('/karate/jobs/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listKarateJobs() {
  return request('/karate/jobs/');
}

export function getKarateJob(id) {
  return request(`/karate/jobs/${id}/`);
}

export function createChain(name) {
  return request('/chains/chains/', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

export function getChain(id) {
  return request(`/chains/chains/${id}/`);
}

export function addChainStep(chainId, payload) {
  return request(`/chains/chains/${chainId}/steps/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createChainRun(chainId, selection) {
  return request(`/chains/chains/${chainId}/runs/`, {
    method: 'POST',
    body: JSON.stringify(selection),
  });
}

export function listChainRuns() {
  return request('/chains/runs/');
}

export function getChainRun(id) {
  return request(`/chains/runs/${id}/`);
}

export function parseCredentialCurl(rawCurl) {
  return request('/credential-tests/parse-curl/', {
    method: 'POST',
    body: JSON.stringify({ raw_curl: rawCurl }),
  });
}

export function createCredentialRun(payload) {
  return request('/credential-tests/runs/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listCredentialRuns() {
  return request('/credential-tests/runs/');
}

export function getCredentialRun(id) {
  return request(`/credential-tests/runs/${id}/`);
}

export function resumeCredentialRun(id, currentValues) {
  return request(`/credential-tests/runs/${id}/resume/`, {
    method: 'POST',
    body: JSON.stringify({ current_values: currentValues }),
  });
}

export function createLoadTestPlan(payload) {
  return request('/load-tests/plans/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listLoadTestPlans() {
  return request('/load-tests/plans/');
}

export function getLoadTestPlan(id) {
  return request(`/load-tests/plans/${id}/`);
}

export function addPlannedLoadTest(planId, payload) {
  return request(`/load-tests/plans/${planId}/tests/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function recordLoadTestResult(testId, jmeterCsvFile, serverMetricsCsvFile) {
  const formData = new FormData();
  formData.append('jmeter_csv', jmeterCsvFile);
  formData.append('server_metrics_csv', serverMetricsCsvFile);
  return request(`/load-tests/tests/${testId}/record/`, {
    method: 'POST',
    body: formData,
  });
}
