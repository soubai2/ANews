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

test("news details use local article snapshots instead of embedded source iframes", () => {
  const app = readDesktopFile("src/App.jsx");
  const main = readDesktopFile("electron/main.js");
  const styles = readDesktopFile("src/styles.css");

  assert.match(app, /article_snapshot/);
  assert.match(app, /renderMarkdownMessage\(selectedNews\.article_snapshot/);
  assert.match(app, /article-reader/);
  assert.doesNotMatch(app, /<iframe/);
  assert.doesNotMatch(app, /readerUrl/);
  assert.doesNotMatch(app, /openOriginalInApp/);
  assert.doesNotMatch(main, /shell\.openExternal/);
  assert.match(styles, /\.article-reader/);
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
  assert.match(app, /agent_max_tool_calls/);
  assert.match(app, /agent_max_search_queries/);
  assert.match(app, /agent_max_read_urls/);
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

test("manual push shows an accessible progress indicator while running", () => {
  const app = readDesktopFile("src/App.jsx");
  const styles = readDesktopFile("src/styles.css");

  assert.match(app, /pushProgress/);
  assert.match(app, /PushProgress/);
  assert.match(app, /PUSH_PROGRESS_PENDING_STEPS/);
  assert.match(app, /PUSH_PROGRESS_PENDING_STEPS = PUSH_PROGRESS_STEPS\.filter/);
  assert.match(app, /step\.key !== "refresh"/);
  assert.match(app, /role="progressbar"/);
  assert.match(app, /aria-valuenow=\{progress\.value\}/);
  assert.match(app, /disabled=\{pushBusy\}/);
  assert.match(styles, /\.push-progress/);
  assert.match(styles, /\.push-progress__fill/);
});

test("manual push prefers concrete backend errors over generic failure codes", () => {
  const app = readDesktopFile("src/App.jsx");

  assert.match(app, /agentFailureReason/);
  assert.match(app, /"model_search_push_failed", "model_tool_arguments_invalid"/);
  assert.match(app, /\.includes\(\s*detail\?\.degradation_reason/);
  assert.match(app, /detail\?\.error_message \|\| detail\?\.message/);
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

test("news cards render focused and followed states", () => {
  const app = readDesktopFile("src/App.jsx");
  const styles = readDesktopFile("src/styles.css");

  assert.match(app, /is_focused/);
  assert.match(app, /is_followed/);
  assert.match(app, /已关注/);
  assert.match(app, /已跟进/);
  assert.match(app, /updateBundleNewsState/);
  assert.match(styles, /\.card-actions button\.selected/);
});

test("news focus and follow controls are toggle actions", () => {
  const app = readDesktopFile("src/App.jsx");

  assert.match(app, /toggleFocusNews/);
  assert.match(app, /toggleFollowNews/);
  assert.match(app, /isFocused \? false : true/);
  assert.match(app, /isFollowed \? false : true/);
});

test("sources can be deleted from the UI", () => {
  const app = readDesktopFile("src/App.jsx");
  const api = readDesktopFile("src/api.js");

  assert.match(api, /deleteSource: \(id\) => request\(`\/api\/sources\/\$\{id\}`/);
  assert.match(app, /deleteSource/);
  assert.match(app, /api\.deleteSource/);
  assert.match(app, /Trash2/);
});

test("chat page supports sessions markdown and product actions", () => {
  const app = readDesktopFile("src/App.jsx");
  const api = readDesktopFile("src/api.js");
  const styles = readDesktopFile("src/styles.css");

  assert.match(api, /listChatSessions/);
  assert.match(api, /getChatSession/);
  assert.match(app, /chatSessions/);
  assert.match(app, /loadChatSession/);
  assert.match(app, /renderMarkdownMessage/);
  assert.match(app, /chatActions/);
  assert.match(app, /actions/);
  assert.match(styles, /\.chat-shell/);
  assert.match(styles, /\.markdown-body/);
  assert.match(styles, /\.chat-actions/);
});

test("importance score has a nonzero readable display path", () => {
  const app = readDesktopFile("src/App.jsx");

  assert.match(app, /importanceLabel/);
  assert.match(app, /importanceScoreClass/);
  assert.match(app, /importance_score/);
});
