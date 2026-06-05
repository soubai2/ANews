import {
  Bell,
  Bot,
  ExternalLink,
  Heart,
  LoaderCircle,
  Newspaper,
  Play,
  Plus,
  Radio,
  Settings,
  Star,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api.js";

const emptyBundle = {
  latest: [],
  relevant: [],
  follow_updates: [],
  last_push_at: null,
  next_push_at: null,
};

const navItems = [
  { id: "push", label: "推送", icon: Newspaper },
  { id: "dialog", label: "对话", icon: Bot },
  { id: "sources", label: "来源", icon: Radio },
  { id: "preferences", label: "偏好", icon: Heart },
  { id: "follows", label: "跟进", icon: Bell },
  { id: "settings", label: "设置", icon: Settings },
];

const sourceTypes = [
  { value: "news", label: "新闻" },
  { value: "rss", label: "RSS" },
  { value: "blog", label: "博客" },
  { value: "company", label: "公司" },
  { value: "regulatory", label: "监管" },
  { value: "search", label: "搜索" },
  { value: "mock", label: "模拟" },
];

const PUSH_PROGRESS_IDLE = {
  visible: false,
  running: false,
  value: 0,
  label: "等待推送",
  detail: "模型推送尚未开始",
  tone: "idle",
};

const PUSH_PROGRESS_STEPS = [
  { key: "preflight", value: 14, label: "准备推送", detail: "检查 DeepSeek 与搜索 API 状态" },
  { key: "search", value: 38, label: "联网搜索", detail: "按偏好检索新闻与指定来源" },
  { key: "select", value: 68, label: "模型筛选", detail: "去重、翻译并生成本地快照" },
  { key: "wait", value: 82, label: "等待模型", detail: "等待 DeepSeek 返回筛选和推送结果" },
  { key: "refresh", value: 92, label: "同步页面", detail: "写入新闻池并刷新推送列表" },
];

const PUSH_PROGRESS_PENDING_STEPS = PUSH_PROGRESS_STEPS.filter((step) => step.key !== "refresh");

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function normalizeBundle(value) {
  return {
    ...emptyBundle,
    ...(value || {}),
    latest: asArray(value?.latest),
    relevant: asArray(value?.relevant),
    follow_updates: asArray(value?.follow_updates),
  };
}

function updateBundleNewsState(bundle, id, patch) {
  const updateItems = (items) =>
    asArray(items).map((item) => (item.id === id ? { ...item, ...patch } : item));
  return normalizeBundle({
    ...bundle,
    latest: updateItems(bundle.latest),
    relevant: updateItems(bundle.relevant),
    follow_updates: updateItems(bundle.follow_updates),
  });
}

function findBundleNews(bundle, id) {
  return [...asArray(bundle.latest), ...asArray(bundle.relevant), ...asArray(bundle.follow_updates)].find(
    (item) => item.id === id,
  );
}

function formatTime(value) {
  if (!value) return "尚未运行";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatScore(value) {
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(1) : "0.0";
}

function importanceLabel(value) {
  const score = Number(value);
  if (!Number.isFinite(score) || score <= 0) return "待评分";
  if (score >= 8) return `高 ${score.toFixed(1)}`;
  if (score >= 4) return `中 ${score.toFixed(1)}`;
  return `低 ${score.toFixed(1)}`;
}

function importanceScoreClass(value) {
  const score = Number(value);
  if (!Number.isFinite(score) || score <= 0) return "score score--muted";
  if (score >= 8) return "score score--high";
  if (score >= 4) return "score score--medium";
  return "score score--low";
}

function formatError(error) {
  if (error instanceof Error && error.message) return error.message;
  return "请求失败";
}

function agentFailureReason(error) {
  const detail = error?.detail;
  if (
    ["model_search_push_failed", "model_tool_arguments_invalid"].includes(
      detail?.degradation_reason,
    )
  ) {
    return detail?.error_message || detail?.message || formatError(error);
  }
  return detail?.degradation_reason || detail?.error_message || detail?.message || formatError(error);
}

function providerStateLabel(statusValue) {
  if (!statusValue) return "未知";
  if (statusValue.available && !statusValue.degraded) return "可用";
  if (statusValue.degraded) return "降级";
  return "不可用";
}

function providerStateClass(statusValue) {
  if (!statusValue) return "status-pill status-pill--muted";
  if (statusValue.available && !statusValue.degraded) return "status-pill status-pill--ok";
  if (statusValue.degraded) return "status-pill status-pill--warn";
  return "status-pill status-pill--muted";
}

function renderInlineMarkdown(text) {
  const nodes = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={`${match.index}-strong`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      nodes.push(<code key={`${match.index}-code`}>{token.slice(1, -1)}</code>);
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      nodes.push(
        <a href={link?.[2] || "#"} key={`${match.index}-link`} rel="noreferrer" target="_blank">
          {link?.[1] || token}
        </a>,
      );
    }
    cursor = match.index + token.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function renderMarkdownMessage(content) {
  const lines = String(content || "").split(/\r?\n/);
  const blocks = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line.trim()) continue;
    if (line.startsWith("### ")) {
      blocks.push(<h3 key={index}>{renderInlineMarkdown(line.slice(4))}</h3>);
    } else if (line.startsWith("## ")) {
      blocks.push(<h3 key={index}>{renderInlineMarkdown(line.slice(3))}</h3>);
    } else if (line.startsWith("# ")) {
      blocks.push(<h3 key={index}>{renderInlineMarkdown(line.slice(2))}</h3>);
    } else if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      index -= 1;
      blocks.push(
        <ul key={index}>
          {items.map((item, itemIndex) => (
            <li key={`${index}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>,
      );
    } else {
      blocks.push(<p key={index}>{renderInlineMarkdown(line)}</p>);
    }
  }
  return blocks.length ? blocks : [<p key="empty">暂无内容</p>];
}

function summarizeChatActions(actions) {
  const parts = [];
  if (actions?.preferences_updated) parts.push(`偏好 +${actions.preferences_updated}`);
  if (actions?.push_news_count) parts.push(`推送 +${actions.push_news_count}`);
  if (actions?.candidates_written) parts.push(`候选 +${actions.candidates_written}`);
  return parts;
}

function pushProgressClass(progress) {
  const tone = progress?.tone || "idle";
  return `push-progress push-progress--${tone}`;
}

function PushProgress({ progress }) {
  if (!progress?.visible) return null;
  return (
    <section className={pushProgressClass(progress)} aria-label="模型推送进度">
      <div className="push-progress__header">
        <div>
          <strong>{progress.label}</strong>
          <span>{progress.detail}</span>
        </div>
        <span className="push-progress__value">{progress.value}%</span>
      </div>
      <div
        className="push-progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress.value}
        aria-label={progress.label}
      >
        <div className="push-progress__fill" style={{ width: `${progress.value}%` }} />
      </div>
      <div className="push-progress__steps">
        {PUSH_PROGRESS_STEPS.map((step) => (
          <span
            className={progress.value >= step.value ? "is-complete" : ""}
            key={step.key}
          >
            {step.label}
          </span>
        ))}
      </div>
    </section>
  );
}

function NewsCard({ item, onFocus, onFollow, onOpen }) {
  const tags = asArray(item.tags).slice(0, 4);
  const reasons = asArray(item.recommendation_reasons).slice(0, 2);
  const isFocused = Boolean(item.is_focused);
  const isFollowed = Boolean(item.is_followed);

  return (
    <article className="news-card">
      <div className="news-card__meta">
        <span className="truncate">{item.source_name || "未知来源"}</span>
        <span>{formatTime(item.published_at)}</span>
        <span>{item.category || "general"}</span>
        <span className={importanceScoreClass(item.importance_score)}>
          重要性 {importanceLabel(item.importance_score)}
        </span>
      </div>
      <h3>{item.title || "未命名新闻"}</h3>
      <p>{item.summary || "暂无摘要。"}</p>
      <div className="tag-row">
        {tags.length > 0 ? (
          tags.map((tag) => (
            <span className="tag" key={tag}>
              {tag}
            </span>
          ))
        ) : (
          <span className="tag tag--muted">未标记</span>
        )}
      </div>
      {reasons.length > 0 && (
        <div className="reason-row">
          {reasons.map((reason) => (
            <span key={reason}>{reason}</span>
          ))}
        </div>
      )}
      <div className="card-actions">
        <button
          className={isFocused ? "selected" : ""}
          type="button"
          onClick={() => onFocus(item.id)}
          title={isFocused ? "取消长期关注" : "加入长期关注"}
        >
          <Heart fill={isFocused ? "currentColor" : "none"} size={16} />
          <span>{isFocused ? "已关注" : "关注"}</span>
        </button>
        <button
          className={isFollowed ? "selected" : ""}
          type="button"
          onClick={() => onFollow(item.id)}
          title={isFollowed ? "取消跟进" : "跟进后续变化"}
        >
          <Star fill={isFollowed ? "currentColor" : "none"} size={16} />
          <span>{isFollowed ? "已跟进" : "跟进"}</span>
        </button>
        <button type="button" onClick={() => onOpen(item)} title="查看新闻详情">
          <ExternalLink size={16} />
          <span>打开</span>
        </button>
      </div>
    </article>
  );
}

function Section({ title, items, empty, onFocus, onFollow, onOpen }) {
  const normalizedItems = asArray(items);

  return (
    <section className="section">
      <header className="section__header">
        <h2>{title}</h2>
        <span>{normalizedItems.length}</span>
      </header>
      {normalizedItems.length === 0 ? (
        <div className="empty">{empty}</div>
      ) : (
        <div className="section-list">
          {normalizedItems.map((item) => (
            <NewsCard
              item={item}
              key={item.id}
              onFocus={onFocus}
              onFollow={onFollow}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export function App() {
  const [active, setActive] = useState("push");
  const [status, setStatus] = useState("连接中");
  const [bundle, setBundle] = useState(emptyBundle);
  const [sources, setSources] = useState([]);
  const [preferences, setPreferences] = useState([]);
  const [follows, setFollows] = useState([]);
  const [aiStatus, setAiStatus] = useState(null);
  const [searchStatus, setSearchStatus] = useState(null);
  const [lastAgentRun, setLastAgentRun] = useState(null);
  const [selectedNews, setSelectedNews] = useState(null);
  const [sourceForm, setSourceForm] = useState({
    name: "",
    url: "",
    source_type: "news",
  });
  const [chatInput, setChatInput] = useState("");
  const [chatSessions, setChatSessions] = useState([]);
  const [chatSessionId, setChatSessionId] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [chatActions, setChatActions] = useState(null);
  const [chatBusy, setChatBusy] = useState(false);
  const [pushProgress, setPushProgress] = useState(PUSH_PROGRESS_IDLE);
  const detailRequestRef = useRef(0);
  const pushProgressTimerRef = useRef(null);
  const pushProgressResetRef = useRef(null);

  function clearPushProgressTimers() {
    if (pushProgressTimerRef.current) {
      window.clearInterval(pushProgressTimerRef.current);
      pushProgressTimerRef.current = null;
    }
    if (pushProgressResetRef.current) {
      window.clearTimeout(pushProgressResetRef.current);
      pushProgressResetRef.current = null;
    }
  }

  function startPushProgress() {
    clearPushProgressTimers();
    let stepIndex = 0;
    setPushProgress({
      ...PUSH_PROGRESS_PENDING_STEPS[stepIndex],
      visible: true,
      running: true,
      tone: "running",
    });
    pushProgressTimerRef.current = window.setInterval(() => {
      stepIndex = Math.min(stepIndex + 1, PUSH_PROGRESS_PENDING_STEPS.length - 1);
      setPushProgress((current) => ({
        ...current,
        ...PUSH_PROGRESS_PENDING_STEPS[stepIndex],
        visible: true,
        running: true,
        tone: "running",
      }));
    }, 1400);
  }

  function markPushProgressStep(stepKey) {
    const step = PUSH_PROGRESS_STEPS.find((item) => item.key === stepKey);
    if (!step) return;
    setPushProgress((current) => ({
      ...current,
      ...step,
      visible: true,
      running: true,
      tone: "running",
    }));
  }

  function finishPushProgress(tone, detail) {
    clearPushProgressTimers();
    setPushProgress({
      visible: true,
      running: false,
      value: 100,
      label: tone === "error" ? "推送失败" : "推送完成",
      detail,
      tone,
    });
    pushProgressResetRef.current = window.setTimeout(() => {
      setPushProgress(PUSH_PROGRESS_IDLE);
      pushProgressResetRef.current = null;
    }, 3600);
  }

  async function refreshAll() {
    try {
      await api.health();
      const [push, sourceList, preferenceList, followList, ai, search, sessionList] = await Promise.all([
        api.getPush(),
        api.listSources(),
        api.listPreferences(),
        api.listFollows(),
        api.aiStatus(),
        api.searchStatus(),
        api.listChatSessions(),
      ]);
      setBundle(normalizeBundle(push));
      setSources(asArray(sourceList));
      setPreferences(asArray(preferenceList));
      setFollows(asArray(followList));
      setAiStatus(ai || null);
      setSearchStatus(search || null);
      setChatSessions(asArray(sessionList));
      setStatus("已连接");
    } catch (error) {
      setStatus(`后端不可用：${formatError(error)}`);
    }
  }

  async function runPush() {
    if (pushProgress.running) return;
    startPushProgress();
    setStatus("正在通过模型搜索推送");
    try {
      const result = await api.runAgentPush();
      setLastAgentRun(result?.run || null);
      markPushProgressStep("refresh");
      await refreshAll();
      finishPushProgress("success", `已完成 ${result?.run?.id || "本轮推送"}`);
      setStatus(`模型推送完成：${result?.run?.id || "已完成"}`);
    } catch (error) {
      setLastAgentRun(error.detail || null);
      const reason = agentFailureReason(error);
      finishPushProgress("error", reason || formatError(error));
      setStatus(`模型推送失败：${reason || formatError(error)}`);
    }
  }

  async function toggleFocusNews(id) {
    if (!id) return;
    const currentItem = findBundleNews(bundle, id);
    const isFocused = Boolean(currentItem?.is_focused);
    const nextFocused = isFocused ? false : true;
    setStatus(nextFocused ? "正在加入关注" : "正在取消关注");
    setBundle((current) => updateBundleNewsState(current, id, { is_focused: nextFocused }));
    try {
      await api.focusNews(id);
      await refreshAll();
    } catch (error) {
      setBundle((current) => updateBundleNewsState(current, id, { is_focused: isFocused }));
      setStatus(`关注更新失败：${formatError(error)}`);
    }
  }

  async function toggleFollowNews(id) {
    if (!id) return;
    const currentItem = findBundleNews(bundle, id);
    const isFollowed = Boolean(currentItem?.is_followed);
    const nextFollowed = isFollowed ? false : true;
    setStatus(nextFollowed ? "正在添加跟进" : "正在取消跟进");
    setBundle((current) => updateBundleNewsState(current, id, { is_followed: nextFollowed }));
    try {
      await api.followNews(id);
      await refreshAll();
    } catch (error) {
      setBundle((current) => updateBundleNewsState(current, id, { is_followed: isFollowed }));
      setStatus(`跟进更新失败：${formatError(error)}`);
    }
  }

  async function openNews(item) {
    if (!item?.id) return;
    const requestId = detailRequestRef.current + 1;
    detailRequestRef.current = requestId;
    setStatus("正在打开详情");
    try {
      const news = await api.getNews(item.id);
      if (detailRequestRef.current !== requestId) return;
      setSelectedNews(news);
      setStatus("已打开详情");
    } catch (error) {
      if (detailRequestRef.current !== requestId) return;
      setSelectedNews(item);
      setStatus(`打开详情失败：${formatError(error)}`);
    }
  }

  function closeDetail() {
    detailRequestRef.current += 1;
    setSelectedNews(null);
  }

  async function addSource(event) {
    event.preventDefault();
    if (!sourceForm.name.trim() || !sourceForm.url.trim()) return;
    setStatus("正在添加来源");
    try {
      await api.addSource({ ...sourceForm, user_specified: true });
      setSourceForm({ name: "", url: "", source_type: "news" });
      await refreshAll();
    } catch (error) {
      setStatus(`添加来源失败：${formatError(error)}`);
    }
  }

  async function deleteSource(source) {
    if (!source?.id) return;
    setStatus("正在删除来源");
    try {
      await api.deleteSource(source.id);
      await refreshAll();
    } catch (error) {
      setStatus(`删除来源失败：${formatError(error)}`);
    }
  }

  async function loadChatSession(id) {
    if (!id) return;
    setStatus("正在加载会话");
    try {
      const response = await api.getChatSession(id);
      setChatSessionId(response.session?.id || id);
      setChatMessages(asArray(response.messages));
      setChatActions(null);
      setStatus("会话已加载");
    } catch (error) {
      setStatus(`加载会话失败：${formatError(error)}`);
    }
  }

  function createNewChat() {
    setChatSessionId("");
    setChatMessages([]);
    setChatActions(null);
    setChatInput("");
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    const text = chatInput.trim();
    if (!text) return;

    setChatBusy(true);
    setStatus("正在与模型对话");
    try {
      let sessionId = chatSessionId;
      if (!sessionId) {
        const session = await api.createChatSession({ title: text.slice(0, 24) || "新闻对话" });
        sessionId = session.id;
        setChatSessionId(sessionId);
        setChatSessions((current) => [session, ...asArray(current).filter((item) => item.id !== session.id)]);
      }
      setChatInput("");
      const response = await api.sendChatMessage(sessionId, { content: text });
      setChatMessages(asArray(response.messages));
      setLastAgentRun(response.agent_run || null);
      setChatActions(response.actions || null);
      await refreshAll();
      const reason = response.agent_run?.degradation_reason;
      const actionParts = summarizeChatActions(response.actions);
      setStatus(
        reason
          ? `对话降级：${reason}`
          : actionParts.length
            ? `对话已联动：${actionParts.join(" / ")}`
            : "对话已返回",
      );
    } catch (error) {
      setStatus(`对话失败：${formatError(error)}`);
    } finally {
      setChatBusy(false);
    }
  }

  async function toggleSource(source) {
    setStatus("正在更新来源");
    try {
      await api.patchSource(source.id, { enabled: !source.enabled });
      await refreshAll();
    } catch (error) {
      setStatus(`来源更新失败：${formatError(error)}`);
    }
  }

  async function deletePreference(id) {
    setStatus("正在删除偏好");
    try {
      await api.deletePreference(id);
      await refreshAll();
    } catch (error) {
      setStatus(`删除偏好失败：${formatError(error)}`);
    }
  }

  async function cancelFollow(id) {
    setStatus("正在取消跟进");
    try {
      await api.cancelFollow(id);
      await refreshAll();
    } catch (error) {
      setStatus(`取消跟进失败：${formatError(error)}`);
    }
  }

  useEffect(() => {
    refreshAll();
    return () => {
      clearPushProgressTimers();
    };
  }, []);

  const pageTitle = useMemo(
    () => navItems.find((item) => item.id === active)?.label || "推送",
    [active],
  );

  const counts = useMemo(
    () => ({
      latest: asArray(bundle.latest).length,
      relevant: asArray(bundle.relevant).length,
      followUpdates: asArray(bundle.follow_updates).length,
    }),
    [bundle],
  );

  const pushBusy = pushProgress.running;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>ANews</span>
          <small>Desktop Agent</small>
        </div>
        <nav aria-label="主导航">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={active === item.id ? "active" : ""}
                key={item.id}
                type="button"
                onClick={() => setActive(item.id)}
                title={item.label}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="topbar__title">
            <p>{pageTitle}</p>
            <h1>新闻推送 Agent</h1>
          </div>
          <div className="topbar__status">
            <span className={providerStateClass(aiStatus)} title={aiStatus?.degradation_reason || ""}>
              DeepSeek {providerStateLabel(aiStatus)}
            </span>
            <span
              className={providerStateClass(searchStatus)}
              title={searchStatus?.degradation_reason || searchStatus?.live_check_note || ""}
            >
              搜索 API {providerStateLabel(searchStatus)}
            </span>
            <span className="connection-status" title={status}>
              {status}
            </span>
            <span>上次 {formatTime(bundle.last_push_at)}</span>
            <span>下次 {formatTime(bundle.next_push_at)}</span>
            <button
              className="push-trigger"
              type="button"
              onClick={runPush}
              disabled={pushBusy}
              title="立即执行一轮推送"
            >
              {pushBusy ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
              <span>{pushBusy ? "推送中" : "刷新"}</span>
            </button>
          </div>
        </header>
        <PushProgress progress={pushProgress} />

        {active === "push" && (
          <>
            <div className="summary-strip">
              <span>最新 {counts.latest}</span>
              <span>相关 {counts.relevant}</span>
              <span>跟进 {counts.followUpdates}</span>
            </div>
            <div className="push-grid">
              <Section
                title="最新"
                items={bundle.latest}
                empty="暂无本轮新增新闻"
                onFocus={toggleFocusNews}
                onFollow={toggleFollowNews}
                onOpen={openNews}
              />
              <Section
                title="相关"
                items={bundle.relevant}
                empty="暂无高相关新闻"
                onFocus={toggleFocusNews}
                onFollow={toggleFollowNews}
                onOpen={openNews}
              />
              <Section
                title="跟进"
                items={bundle.follow_updates}
                empty="暂无跟进更新"
                onFocus={toggleFocusNews}
                onFollow={toggleFollowNews}
                onOpen={openNews}
              />
            </div>
          </>
        )}

        {active === "dialog" && (
          <section className="panel panel--wide">
            <header className="panel__header">
              <h2>Agent 对话</h2>
              <span>{chatSessionId ? "上下文会话" : "新会话"}</span>
            </header>
            <div className="chat-shell">
              <aside className="chat-sessions" aria-label="历史会话">
                <button className="chat-sessions__new" type="button" onClick={createNewChat}>
                  <Plus size={16} />
                  <span>新会话</span>
                </button>
                <div className="chat-session-list">
                  {chatSessions.length === 0 ? (
                    <div className="empty empty--compact">暂无历史会话</div>
                  ) : (
                    chatSessions.map((session) => (
                      <button
                        className={session.id === chatSessionId ? "active" : ""}
                        key={session.id}
                        type="button"
                        onClick={() => loadChatSession(session.id)}
                      >
                        <strong>{session.title || "新闻对话"}</strong>
                        <span>{formatTime(session.updated_at)}</span>
                      </button>
                    ))
                  )}
                </div>
              </aside>
              <div className="chat-workspace">
                <div className="chat-list">
                  {chatMessages.length === 0 ? (
                    <div className="empty">暂无对话消息</div>
                  ) : (
                    chatMessages.map((message) => (
                      <div className={`chat-message chat-message--${message.role}`} key={message.id}>
                        <span>{message.role === "user" ? "你" : "ANews"}</span>
                        <div className="markdown-body">{renderMarkdownMessage(message.content)}</div>
                      </div>
                    ))
                  )}
                  {chatBusy && (
                    <div className="chat-message chat-message--assistant">
                      <span>ANews</span>
                      <div className="markdown-body">
                        <p>正在查询偏好、搜索、写入新闻池或整理回答...</p>
                      </div>
                    </div>
                  )}
                </div>
                {summarizeChatActions(chatActions).length > 0 && (
                  <div className="chat-actions">
                    {summarizeChatActions(chatActions).map((item) => (
                      <span key={item}>{item}</span>
                    ))}
                    {chatActions?.push_news_count > 0 && (
                      <button type="button" onClick={() => setActive("push")}>
                        查看推送
                      </button>
                    )}
                  </div>
                )}
                <form className="command-form" onSubmit={sendChatMessage}>
                  <input
                    value={chatInput}
                    onChange={(event) => setChatInput(event.target.value)}
                    placeholder="例如：记住我关注 AI 芯片，并查今天相关新闻"
                  />
                  <button type="submit" disabled={chatBusy}>
                    <Bot size={16} />
                    <span>{chatBusy ? "处理中" : "发送"}</span>
                  </button>
                </form>
                <div className="hint-row">
                  <button type="button" onClick={runPush} disabled={pushBusy}>
                    {pushBusy ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
                    <span>{pushBusy ? "推送中" : "立即推送"}</span>
                  </button>
                  <button type="button" onClick={createNewChat}>
                    <Plus size={16} />
                    <span>新会话</span>
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}

        {active === "sources" && (
          <section className="panel">
            <header className="panel__header">
              <h2>指定来源</h2>
              <span>{sources.length} 个来源</span>
            </header>
            <form className="source-form" onSubmit={addSource}>
              <input
                placeholder="名称"
                value={sourceForm.name}
                onChange={(event) =>
                  setSourceForm((current) => ({ ...current, name: event.target.value }))
                }
              />
              <input
                placeholder="URL 或 mock://source"
                value={sourceForm.url}
                onChange={(event) =>
                  setSourceForm((current) => ({ ...current, url: event.target.value }))
                }
              />
              <select
                value={sourceForm.source_type}
                onChange={(event) =>
                  setSourceForm((current) => ({
                    ...current,
                    source_type: event.target.value,
                  }))
                }
              >
                {sourceTypes.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
              <button type="submit">
                <Plus size={16} />
                <span>添加</span>
              </button>
            </form>
            <div className="table-list">
              {sources.length === 0 ? (
                <div className="empty">暂无指定来源</div>
              ) : (
                sources.map((source) => (
                  <div className="table-row" key={source.id}>
                    <div className="row-main">
                      <strong>{source.name}</strong>
                      <span className="row-detail">{source.url}</span>
                      {source.failure_reason && (
                        <span className="row-error">{source.failure_reason}</span>
                      )}
                    </div>
                    <div className="row-meta">
                      <span className={source.enabled ? "state enabled" : "state muted"}>
                        {source.enabled ? "启用" : "停用"}
                      </span>
                      <span>{source.source_type}</span>
                      <span>{source.user_specified ? "用户指定" : "默认"}</span>
                      <button type="button" onClick={() => toggleSource(source)}>
                        {source.enabled ? "停用" : "启用"}
                      </button>
                      <button
                        className="icon-button danger"
                        type="button"
                        onClick={() => deleteSource(source)}
                        title="删除来源"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        )}

        {active === "preferences" && (
          <section className="panel">
            <header className="panel__header">
              <h2>偏好</h2>
              <span>{preferences.length} 条规则</span>
            </header>
            <div className="table-list">
              {preferences.length === 0 ? (
                <div className="empty">暂无偏好记录</div>
              ) : (
                preferences.map((preference) => (
                  <div className="table-row" key={preference.id}>
                    <div className="row-main">
                      <strong>{preference.value}</strong>
                      <span>
                        {preference.kind} / 权重 {formatScore(preference.weight)} / 来源{" "}
                        {preference.created_from || "manual"}
                      </span>
                    </div>
                    <button
                      className="icon-button danger"
                      type="button"
                      onClick={() => deletePreference(preference.id)}
                      title="删除偏好"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
        )}

        {active === "follows" && (
          <section className="panel">
            <header className="panel__header">
              <h2>跟进事件</h2>
              <span>{follows.length} 个事件</span>
            </header>
            <div className="table-list">
              {follows.length === 0 ? (
                <div className="empty">暂无跟进事件</div>
              ) : (
                follows.map((follow) => (
                  <div className="table-row" key={follow.id}>
                    <div className="row-main">
                      <strong>{follow.title}</strong>
                      <span>
                        {asArray(follow.keywords).join(" / ") || "无关键词"} /{" "}
                        {formatTime(follow.created_at)}
                      </span>
                    </div>
                    <button type="button" onClick={() => cancelFollow(follow.id)}>
                      取消
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
        )}

        {active === "settings" && (
          <div className="settings-stack">
            <section className="panel">
              <header className="panel__header">
                <h2>DeepSeek 设置</h2>
                <span>{providerStateLabel(aiStatus)}</span>
              </header>
              <div className="settings-grid">
                <span>Provider</span>
                <strong>{aiStatus?.provider || "deepseek"}</strong>
                <span>Model</span>
                <strong>{aiStatus?.model || "deepseek-v4-flash"}</strong>
                <span>Base URL</span>
                <strong>{aiStatus?.base_url || "https://api.deepseek.com"}</strong>
                <span>API Key</span>
                <strong>{aiStatus?.api_key_configured ? "已配置" : "未配置"}</strong>
                <span>可用状态</span>
                <strong>{providerStateLabel(aiStatus)}</strong>
                <span>降级原因</span>
                <strong>{aiStatus?.degradation_reason || "无"}</strong>
                <span>Fallback</span>
                <strong>{aiStatus?.fallback_enabled ? "启用" : "关闭"}</strong>
              </div>
            </section>
            <section className="panel">
              <header className="panel__header">
                <h2>搜索 API</h2>
                <span>{providerStateLabel(searchStatus)}</span>
              </header>
              <div className="settings-grid">
                <span>Provider</span>
                <strong>{searchStatus?.provider || "tavily"}</strong>
                <span>API Key</span>
                <strong>{searchStatus?.configured ? "已配置" : "未配置"}</strong>
                <span>可用状态</span>
                <strong>{providerStateLabel(searchStatus)}</strong>
                <span>降级原因</span>
                <strong>{searchStatus?.degradation_reason || "无"}</strong>
                <span>搜索深度</span>
                <strong>{searchStatus?.search_depth || "basic"}</strong>
                <span>额度策略</span>
                <strong>{searchStatus?.credit_policy || "basic search uses 1 Tavily API credit"}</strong>
                <span>工具预算</span>
                <strong>{searchStatus?.agent_max_tool_calls || "未配置"}</strong>
                <span>搜索预算</span>
                <strong>{searchStatus?.agent_max_search_queries || "未配置"}</strong>
                <span>读 URL 预算</span>
                <strong>{searchStatus?.agent_max_read_urls || "未配置"}</strong>
                <span>探活</span>
                <strong>{searchStatus?.live_check_note || "未执行"}</strong>
              </div>
            </section>
            <section className="panel">
              <header className="panel__header">
                <h2>最近 Agent 推送</h2>
                <span>{lastAgentRun?.status || "暂无"}</span>
              </header>
              <div className="settings-grid">
                <span>Run ID</span>
                <strong>{lastAgentRun?.id || lastAgentRun?.run_id || "无"}</strong>
                <span>状态</span>
                <strong>{lastAgentRun?.status || "无"}</strong>
                <span>是否降级</span>
                <strong>{lastAgentRun?.degraded ? "是" : "否"}</strong>
                <span>降级原因</span>
                <strong>{lastAgentRun?.degradation_reason || "无"}</strong>
              </div>
            </section>
          </div>
        )}
      </main>

      {selectedNews && (
        <div className="drawer-layer">
          <button
            aria-label="关闭详情"
            className="drawer-scrim"
            type="button"
            onClick={closeDetail}
          />
          <aside className="drawer drawer--article" aria-label="新闻详情">
            <button className="drawer__close" type="button" onClick={closeDetail}>
              关闭
            </button>
            <p className="drawer__meta">
              {selectedNews.source_name || "未知来源"} / {formatTime(selectedNews.published_at)}
            </p>
            <h2>{selectedNews.article_snapshot?.title || selectedNews.title}</h2>
            <p>{selectedNews.summary || "暂无摘要。"}</p>
            <div className="tag-row">
              {asArray(selectedNews.tags).map((tag) => (
                <span className="tag" key={tag}>
                  {tag}
                </span>
              ))}
            </div>
            <div className="reason-list">
              {asArray(selectedNews.recommendation_reasons).map((reason) => (
                <span key={reason}>{reason}</span>
              ))}
            </div>
            <div className="article-reader">
              <div className="article-reader__bar">
                <span>
                  {selectedNews.article_snapshot?.status === "translated"
                    ? "本地中文快照"
                    : "摘要快照"}
                </span>
                <span>{selectedNews.article_snapshot?.layout_style || "article"}</span>
              </div>
              <div className="markdown-body article-reader__body">
                {selectedNews.article_snapshot?.markdown
                  ? renderMarkdownMessage(selectedNews.article_snapshot.markdown)
                  : renderMarkdownMessage(
                      `## ${selectedNews.title || "新闻详情"}\n\n${
                        selectedNews.summary || "这条新闻暂未生成本地文章快照。"
                      }\n\n### 原始来源\n- ${selectedNews.source_name || "未知来源"}: ${
                        selectedNews.url || "无"
                      }`,
                    )}
              </div>
            </div>
            {selectedNews.url && (
              <div className="source-evidence">
                <span>原始来源</span>
                <strong>{selectedNews.url}</strong>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
