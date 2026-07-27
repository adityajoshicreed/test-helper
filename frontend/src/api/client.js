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
