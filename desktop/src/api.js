const API_BASE = "http://127.0.0.1:8765";

async function request(path, options = {}) {
  const { headers = {}, ...requestOptions } = options;
  const response = await fetch(`${API_BASE}${path}`, {
    ...requestOptions,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = null;
    try {
      detail = JSON.parse(text).detail;
    } catch {
      detail = null;
    }
    const message =
      detail?.message || detail?.error_message || text || `Request failed: ${response.status}`;
    const error = new Error(message);
    error.detail = detail;
    throw error;
  }
  return response.json();
}

export const api = {
  health: () => request("/api/health"),
  getPush: () => request("/api/push"),
  runPush: () => request("/api/push/run", { method: "POST" }),
  runAgentPush: () => request("/api/agent/push/run", { method: "POST" }),
  getAgentRunTrace: (id) => request(`/api/agent/runs/${id}/trace`),
  listNews: (query = "") => request(`/api/news?q=${encodeURIComponent(query)}`),
  getNews: (id) => request(`/api/news/${id}`),
  createChatSession: (payload) =>
    request("/api/chat/sessions", { method: "POST", body: JSON.stringify(payload) }),
  getChatSession: (id) => request(`/api/chat/sessions/${id}`),
  sendChatMessage: (id, payload) =>
    request(`/api/chat/sessions/${id}/messages`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
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
  searchStatus: () => request("/api/search/status"),
  updateAISettings: (payload) =>
    request("/api/ai/settings", { method: "PATCH", body: JSON.stringify(payload) }),
  testAI: () => request("/api/ai/test", { method: "POST" }),
};
