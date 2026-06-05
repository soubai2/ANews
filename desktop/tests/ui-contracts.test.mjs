import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const desktopRoot = path.resolve(__dirname, "..");

function readDesktopFile(relativePath) {
  return readFileSync(path.join(desktopRoot, relativePath), "utf8");
}

test("news detail requests ignore stale responses", () => {
  const app = readDesktopFile("src/App.jsx");

  assert.match(app, /useRef/);
  assert.match(app, /detailRequestRef/);
  assert.match(app, /detailRequestRef\.current !== requestId/);
});

test("original article links stay inside the app shell", () => {
  const app = readDesktopFile("src/App.jsx");
  const main = readDesktopFile("electron/main.js");

  assert.match(app, /readerUrl/);
  assert.match(app, /openOriginalInApp/);
  assert.match(app, /<iframe/);
  assert.doesNotMatch(app, /<a className="drawer-link" href=\{selectedNews\.url\}>/);
  assert.doesNotMatch(main, /shell\.openExternal/);
});

test("api request merges custom headers without dropping defaults", () => {
  const api = readDesktopFile("src/api.js");

  assert.match(api, /const \{ headers = \{\}, \.\.\.requestOptions \} = options;/);
  assert.match(api, /\.\.\.requestOptions,\s*headers: \{/);
  assert.match(api, /"Content-Type": "application\/json",\s*\.\.\.headers,/);
  assert.match(api, /error\.detail = detail;/);
});

test("app exposes ai and search provider degradation status", () => {
  const app = readDesktopFile("src/App.jsx");
  const api = readDesktopFile("src/api.js");

  assert.match(api, /searchStatus: \(\) => request\("\/api\/search\/status"\)/);
  assert.match(app, /DeepSeek \{providerStateLabel\(aiStatus\)\}/);
  assert.match(app, /搜索 API \{providerStateLabel\(searchStatus\)\}/);
  assert.match(app, /degradation_reason/);
  assert.match(app, /live_check_note/);
});

test("manual push uses agent push endpoint and surfaces degradation", () => {
  const app = readDesktopFile("src/App.jsx");
  const api = readDesktopFile("src/api.js");

  assert.match(api, /runAgentPush: \(\) => request\("\/api\/agent\/push\/run"/);
  assert.match(api, /getAgentRunTrace/);
  assert.match(app, /api\.runAgentPush\(\)/);
  assert.match(app, /模型推送失败/);
  assert.match(app, /degradation_reason/);
});

test("dialog page uses persisted chat api instead of local command parser", () => {
  const app = readDesktopFile("src/App.jsx");
  const api = readDesktopFile("src/api.js");

  assert.match(api, /createChatSession/);
  assert.match(api, /sendChatMessage/);
  assert.match(app, /api\.sendChatMessage/);
  assert.match(app, /chatMessages/);
  assert.match(app, /对话降级/);
  assert.doesNotMatch(app, /api\.listNews\(text\)/);
});
