const API_BASE = "http://127.0.0.1:8765";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

export const api = {
  health: () => request("/api/health"),
  getPush: () => request("/api/push"),
  runPush: () => request("/api/push/run", { method: "POST" }),
  listNews: (query = "") => request(`/api/news?q=${encodeURIComponent(query)}`),
  getNews: (id) => request(`/api/news/${id}`),
  focusNews: (id) => request(`/api/news/${id}/focus`, { method: "POST" }),
  followNews: (id) => request(`/api/news/${id}/follow`, { method: "POST" }),
  listSources: () => request("/api/sources"),
  addSource: (payload) =>
    request("/api/sources", { method: "POST", body: JSON.stringify(payload) }),
  patchSource: (id, payload) =>
    request(`/api/sources/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  listPreferences: () => request("/api/preferences"),
  deletePreference: (id) => request(`/api/preferences/${id}`, { method: "DELETE" }),
  listFollows: () => request("/api/follows"),
  cancelFollow: (id) => request(`/api/follows/${id}`, { method: "DELETE" }),
  aiStatus: () => request("/api/ai/status"),
  updateAISettings: (payload) =>
    request("/api/ai/settings", { method: "PATCH", body: JSON.stringify(payload) }),
  testAI: () => request("/api/ai/test", { method: "POST" }),
};
