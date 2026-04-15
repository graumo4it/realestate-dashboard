/**
 * API client — все запросы к backend
 */
const API_BASE = window.API_BASE || 'http://localhost:8000/api';

async function apiFetch(path, params = {}) {
  const url = new URL(API_BASE + path, location.href);
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  const resp = await fetch(url.toString());
  if (!resp.ok) throw new Error(`API ${resp.status}: ${url}`);
  return resp.json();
}

const api = {
  categories:          ()           => apiFetch('/categories'),
  categoryIndicators:  (code)       => apiFetch(`/categories/${code}/indicators`),
  indicator:           (code)       => apiFetch(`/indicators/${code}`),
  indicatorData:       (code, from, to) => apiFetch(`/indicators/${code}/data`, { from, to }),
  indicatorXlsx:       (code)       => `${API_BASE}/indicators/${code}/data.xlsx`,
  search:              (q)          => apiFetch('/search', { q }),
  lastUpdate:          ()           => apiFetch('/meta/last-update'),
};
