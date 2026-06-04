# ANews Phase 2 Model-Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade ANews into a DeepSeek-first model-search news Agent. Scheduled push, manual refresh, chat search, and follow-up checks must all run through the model-driven search pipeline.

**Approved design:** `docs/superpowers/specs/2026-06-05-anews-phase2-model-search-design.md`

**Primary constraint:** Do not implement real push refresh as a backend-only crawler or rule sorter. The model must query preferences, create search plans, call search/read tools, filter candidates, and submit push selections.

---

## Task 0: External Search Decision And Configuration

**Files:**
- Modify: `src/anews_agent/config.py`
- Modify: `.anews.env`
- Test: `tests/test_config.py`

- [ ] Choose the first real search provider adapter. Keep the interface provider-neutral, but implement one usable provider behind env config.
- [ ] Add config keys:
  - `ANEWS_SEARCH_PROVIDER`
  - `ANEWS_SEARCH_API_KEY`
  - `ANEWS_SEARCH_BASE_URL`
  - `ANEWS_SEARCH_TIMEOUT_SECONDS`
  - `ANEWS_AGENT_MAX_TOOL_CALLS`
  - `ANEWS_AGENT_MAX_SEARCH_QUERIES`
  - `ANEWS_AGENT_MAX_READ_URLS`
- [ ] Keep mock search provider for tests and offline development.
- [ ] Add config tests for DeepSeek, search provider and agent budgets.

## Task 1: Schema Migration For Agent Runs, Search And Chat

**Files:**
- Modify: `src/anews_agent/storage.py`
- Modify: `src/anews_agent/domain.py`
- Test: `tests/test_storage.py`

- [ ] Add domain models for `ChatSession`, `ChatMessage`, `AgentRun`, `AgentToolCall`, `SearchQuery`, `SearchResult`, `RetrievedDocument`, `CandidateNews`, `PushSelection`, `PreferenceFact`, `PreferenceSummary`, `NewsUserState`.
- [ ] Add SQLite tables for those models.
- [ ] Add repository methods to create agent runs, append tool calls, save search results, save retrieved documents and persist chat messages.
- [ ] Add `news_user_state` to persist read/focused/followed UI state per news item.
- [ ] Add tests that prove user state survives refresh and process restart.

## Task 2: Search Provider And Web Reader Layer

**Files:**
- Create: `src/anews_agent/search.py`
- Test: `tests/test_search.py`

- [ ] Define `SearchProvider` protocol.
- [ ] Define `WebReader` protocol.
- [ ] Implement `MockSearchProvider` with deterministic results for tests.
- [ ] Implement one real search provider adapter behind env config.
- [ ] Implement URL read pipeline with timeout, content-type checks, title extraction, published time extraction and text cleanup.
- [ ] Cache search results and retrieved documents to SQLite.
- [ ] Add tests for query normalization, failure handling, caching and document extraction.

## Task 3: Preference Knowledge Base

**Files:**
- Create: `src/anews_agent/preferences_kb.py`
- Modify: `src/anews_agent/storage.py`
- Test: `tests/test_preferences_kb.py`

- [ ] Store preference facts separately from simple MVP preferences.
- [ ] Support positive preferences, negative preferences, source preferences, entity preferences and behavior-derived signals.
- [ ] Add SQLite FTS5 index for preference values and summaries.
- [ ] Implement `query_preferences(task, limit)` for model tools.
- [ ] Implement `update_preferences(changes, source_message_id)` for explicit user preference changes.
- [ ] Generate compact prompt-ready preference summaries.
- [ ] Add tests for preference merging, weight updates, negative preference handling and FTS query behavior.

## Task 4: Agent Tool Registry

**Files:**
- Create: `src/anews_agent/agent_tools.py`
- Test: `tests/test_agent_tools.py`

- [ ] Define tool schemas for DeepSeek:
  - `query_preferences`
  - `search_web`
  - `search_user_sources`
  - `read_url`
  - `query_news_pool`
  - `query_followed_stories`
  - `write_candidate_news`
  - `select_push_items`
  - `update_preferences`
  - `follow_story`
  - `explain_ranking`
- [ ] Validate all tool arguments before execution.
- [ ] Convert tool results into compact JSON-safe payloads.
- [ ] Add tests for schema validity, argument validation and permission boundaries.

## Task 5: DeepSeek Tool-Calling Runtime

**Files:**
- Modify: `src/anews_agent/ai.py`
- Create: `src/anews_agent/agent_runtime.py`
- Test: `tests/test_agent_runtime.py`

- [ ] Extend the DeepSeek provider to support tool definitions, tool-call responses and multi-turn tool loops.
- [ ] Preserve the existing enrichment path, but separate it from Agent runtime.
- [ ] Add strict JSON validation on model outputs before executing tools.
- [ ] Add max tool calls, max runtime and max token budget enforcement.
- [ ] Persist each model message and tool call into `agent_runs`.
- [ ] Add tests with a fake model that calls tools across multiple turns.
- [ ] Add tests for malformed tool arguments, tool failure, budget exhaustion and final answer validation.

## Task 6: Model-Driven Push Service

**Files:**
- Create: `src/anews_agent/agent_push.py`
- Modify: `src/anews_agent/services.py`
- Modify: `src/anews_agent/api/app.py`
- Test: `tests/test_agent_push.py`
- Test: `tests/test_api.py`

- [ ] Create `ModelSearchPushService`.
- [ ] Implement push prompt that forces the model to first call `query_preferences`.
- [ ] Force every real push run to use search tools before `select_push_items`.
- [ ] Include user specified sources and followed stories in the model search planning prompt.
- [ ] Validate final push selection has source URLs, evidence and recommendation reasons.
- [ ] Keep old deterministic push service only for explicit demo/test mode.
- [ ] Add `POST /api/agent/push/run`.
- [ ] Make existing `POST /api/push/run` call the model-search path in real mode.
- [ ] Do not advance `last_push_at` when model, search or validation fails.
- [ ] Add tests proving scheduled and manual push both go through Agent tool calls.

## Task 7: Chat Sessions And Real News Conversation

**Files:**
- Create: `src/anews_agent/chat.py`
- Modify: `src/anews_agent/api/app.py`
- Modify: `desktop/src/api.js`
- Test: `tests/test_chat.py`
- Test: `desktop/tests/ui-contracts.test.mjs`

- [ ] Add chat session and message APIs.
- [ ] Implement chat Agent prompt for news questions, source management, follow-up requests and preference edits.
- [ ] Let chat Agent call the same search/read/preference tools used by push.
- [ ] Return assistant message with citations and follow-up actions.
- [ ] Persist full chat history.
- [ ] Expose run events through polling endpoint first; SSE can be added after stable contracts.
- [ ] Add tests proving chat search performs tool calls and returns cited answers.

## Task 8: Frontend State Feedback

**Files:**
- Modify: `desktop/src/App.jsx`
- Modify: `desktop/src/styles.css`
- Modify: `desktop/src/api.js`
- Test: `desktop/tests/ui-contracts.test.mjs`

- [ ] Add `is_focused`, `is_followed`, `is_read` state to news cards.
- [ ] Make focus/follow operations optimistic with loading state and rollback on failure.
- [ ] Change button labels and icons to clearly show `已关注` and `已跟进`.
- [ ] Add card-local error feedback for failed actions.
- [ ] Add Agent run progress panel for push refresh.
- [ ] Replace command box with chat transcript.
- [ ] Show assistant messages, user messages, tool progress and cited source cards.
- [ ] Add UI contract tests for followed/focused button states and chat event rendering.

## Task 9: Scheduler And Follow-Up Search

**Files:**
- Modify: `src/anews_agent/scheduler.py`
- Modify: `src/anews_agent/agent_push.py`
- Test: `tests/test_scheduler.py`
- Test: `tests/test_agent_push.py`

- [ ] Route scheduled jobs to `ModelSearchPushService`.
- [ ] Ensure followed stories are included in every scheduled search plan.
- [ ] Require model to distinguish substantive follow-up updates from duplicate reposts.
- [ ] Save follow-up updates with changed facts and source evidence.
- [ ] Add tests that failed scheduled runs do not move `last_push_at`.

## Task 10: Trace, Debugging And Verification

**Files:**
- Modify: `src/anews_agent/api/app.py`
- Modify: `desktop/src/App.jsx`
- Test: `tests/test_api.py`

- [ ] Add `GET /api/agent/runs/{run_id}`.
- [ ] Add `GET /api/agent/runs/{run_id}/trace`.
- [ ] Show recent Agent run trace in settings or debug panel.
- [ ] Include searched queries, read URLs, selected news and filtered reasons.
- [ ] Add smoke script or documented commands for:
  - backend tests
  - desktop contract tests
  - desktop build
  - one manual model-search push run
  - one chat search run

## Delivery Order

- [ ] Finish Tasks 0-2 first so networking and search are real.
- [ ] Finish Tasks 3-5 next so DeepSeek can use preference and search tools.
- [ ] Finish Task 6 before changing scheduler behavior.
- [ ] Finish Task 7 and Task 8 together so the product clearly shows real Agent behavior.
- [ ] Finish Task 9 after manual push is stable.
- [ ] Finish Task 10 before declaring phase 2 complete.

## Definition Of Done

- [ ] `python -m pytest -q --basetemp .tmp_pytest` passes.
- [ ] `npm run test:contracts` passes in `desktop`.
- [ ] `npm run build` passes in `desktop`.
- [ ] Manual push creates an `agent_run` with preference query, search calls, read calls and push selection.
- [ ] Scheduled push uses the same model-search pipeline as manual push.
- [ ] Chat can answer a fresh news query with source citations.
- [ ] Focus/follow buttons visibly persist their state.
- [ ] User preference changes from chat are written to the knowledge base.
- [ ] Push results can be explained from stored trace.
