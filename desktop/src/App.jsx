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

const sectionVariantClass = {
  latest: "section--latest",
  relevant: "section--relevant",
  follow: "section--follow",
};

const pageRegistry = {
  push: PushPage,
  dialog: DialogPage,
  sources: SourcesPage,
  preferences: PreferencesPage,
  follows: FollowsPage,
  settings: SettingsPage,
};

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

function useAnewsDashboard() {
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
  const [sourceForm, setSourceForm] = useState({ name: "", url: "", source_type: "news" });
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

  const dashboardView = useMemo(
    () => ({
      active,
      status,
      bundle,
      sources,
      preferences,
      follows,
      aiStatus,
      searchStatus,
      lastAgentRun,
      selectedNews,
      sourceForm,
      chatInput,
      chatSessions,
      chatSessionId,
      chatMessages,
      chatActions,
      chatBusy,
      pushProgress,
      pushBusy: pushProgress.running,
      pageTitle: navItems.find((item) => item.id === active)?.label || "推送",
      counts: {
        latest: asArray(bundle.latest).length,
        relevant: asArray(bundle.relevant).length,
        followUpdates: asArray(bundle.follow_updates).length,
      },
    }),
    [
      active,
      status,
      bundle,
      sources,
      preferences,
      follows,
      aiStatus,
      searchStatus,
      lastAgentRun,
      selectedNews,
      sourceForm,
      chatInput,
      chatSessions,
      chatSessionId,
      chatMessages,
      chatActions,
      chatBusy,
      pushProgress,
    ],
  );

  const dashboardActions = useMemo(
    () => ({
      setActive,
      setSourceForm,
      setChatInput,
      runPush,
      toggleFocusNews,
      toggleFollowNews,
      openNews,
      closeDetail,
      addSource,
      deleteSource,
      loadChatSession,
      createNewChat,
      sendChatMessage,
      toggleSource,
      deletePreference,
      cancelFollow,
    }),
    [bundle, sourceForm, chatInput, chatSessionId, pushProgress.running],
  );

  return { dashboardView, dashboardActions };
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
          <span className={progress.value >= step.value ? "is-complete" : ""} key={step.key}>
            {step.label}
          </span>
        ))}
      </div>
    </section>
  );
}

function MetricRail({ view }) {
  const metrics = [
    { label: "本轮最新", value: view.counts.latest, detail: "上次推送后新增" },
    { label: "相关排序", value: view.counts.relevant, detail: "按偏好与热度排序" },
    { label: "跟进更新", value: view.counts.followUpdates, detail: "仅显示实质变化" },
    { label: "指定来源", value: view.sources.length, detail: "每轮强制纳入" },
    { label: "偏好规则", value: view.preferences.length, detail: "影响相关板块" },
    { label: "跟进事件", value: view.follows.length, detail: "持续追踪后续" },
  ];

  return (
    <section className="metric-rail" aria-label="新闻工作台指标">
      {metrics.map((metric) => (
        <div className="metric-card" key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
          <small>{metric.detail}</small>
        </div>
      ))}
      <div className="metric-card metric-card--schedule">
        <span>推送窗口</span>
        <strong>{formatTime(view.bundle.last_push_at)}</strong>
        <small>下次 {formatTime(view.bundle.next_push_at)}</small>
      </div>
    </section>
  );
}

function NewsCard({ item, actions }) {
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
          onClick={() => actions.toggleFocusNews(item.id)}
          title={isFocused ? "取消长期关注" : "加入长期关注"}
        >
          <Heart fill={isFocused ? "currentColor" : "none"} size={16} />
          <span>{isFocused ? "已关注" : "关注"}</span>
        </button>
        <button
          className={isFollowed ? "selected" : ""}
          type="button"
          onClick={() => actions.toggleFollowNews(item.id)}
          title={isFollowed ? "取消跟进" : "跟进后续变化"}
        >
          <Star fill={isFollowed ? "currentColor" : "none"} size={16} />
          <span>{isFollowed ? "已跟进" : "跟进"}</span>
        </button>
        <button type="button" onClick={() => actions.openNews(item)} title="查看新闻详情">
          <ExternalLink size={16} />
          <span>打开</span>
        </button>
      </div>
    </article>
  );
}

function NewsSection({ section, actions }) {
  const items = asArray(section.items);
  const variantClass = sectionVariantClass[section.variant] || "";

  return (
    <section className={`section ${variantClass}`}>
      <header className="section__header">
        <div>
          <h2>{section.title}</h2>
          <p>{section.note}</p>
        </div>
        <span>{items.length}</span>
      </header>
      {items.length === 0 ? (
        <div className="empty">{section.empty}</div>
      ) : (
        <div className="section-list">
          {items.map((item) => (
            <NewsCard actions={actions} item={item} key={item.id} />
          ))}
        </div>
      )}
    </section>
  );
}

function PushPage({ view, actions }) {
  const pushSections = [
    {
      title: "最新",
      variant: "latest",
      note: "本轮抓取到的新内容",
      items: view.bundle.latest,
      empty: "暂无本轮新增新闻",
    },
    {
      title: "相关",
      variant: "relevant",
      note: "偏好、热度与来源权威性综合排序",
      items: view.bundle.relevant,
      empty: "暂无高相关新闻",
    },
    {
      title: "跟进",
      variant: "follow",
      note: "你要求持续追踪的事件更新",
      items: view.bundle.follow_updates,
      empty: "暂无跟进更新",
    },
  ];

  return (
    <div className="push-dashboard">
      <MetricRail view={view} />
      <section className="control-card" aria-label="推送控制">
        <div>
          <span>两小时窗口</span>
          <strong>上次推送 -10 分钟 到 当前 +10 分钟</strong>
          <p>最新新闻入池后会同步更新最新、相关和跟进三个板块。</p>
        </div>
        <button
          className="push-trigger push-trigger--primary"
          type="button"
          onClick={actions.runPush}
          disabled={view.pushBusy}
        >
          {view.pushBusy ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
          <span>{view.pushBusy ? "推送中" : "立即推送"}</span>
        </button>
      </section>
      <div className="push-grid">
        {pushSections.map((section) => (
          <NewsSection actions={actions} key={section.variant} section={section} />
        ))}
      </div>
    </div>
  );
}

function DialogPage({ view, actions }) {
  const actionParts = summarizeChatActions(view.chatActions);

  return (
    <section className="command-center chatgpt-shell">
      <aside className="chat-sessions" aria-label="历史会话">
        <div className="chat-sessions__inner">
          <div className="chat-sessions__title">
            <strong>会话队列</strong>
            <span>{view.chatSessions.length} 条记录</span>
          </div>
          <button className="chat-sessions__new" type="button" onClick={actions.createNewChat}>
            <Plus size={16} />
            <span>新会话</span>
          </button>
          <div className="chat-session-list">
            {view.chatSessions.length === 0 ? (
              <div className="empty empty--compact">暂无历史会话</div>
            ) : (
              view.chatSessions.map((session) => (
                <button
                  className={session.id === view.chatSessionId ? "active" : ""}
                  key={session.id}
                  type="button"
                  onClick={() => actions.loadChatSession(session.id)}
                >
                  <strong>{session.title || "新闻对话"}</strong>
                  <span>{formatTime(session.updated_at)}</span>
                </button>
              ))
            )}
          </div>
        </div>
      </aside>
      <div className="chat-workspace">
        <header className="chat-header">
          <div>
            <h2>Agent 对话</h2>
            <span>{view.chatSessionId ? "上下文会话" : "新会话"}</span>
          </div>
        </header>
        <div className="chat-thread">
          <div className="chat-list">
            {view.chatMessages.length === 0 ? (
              <div className="empty">暂无对话消息</div>
            ) : (
              view.chatMessages.map((message) => (
                <div className={`chat-message chat-message--${message.role}`} key={message.id}>
                  <span>{message.role === "user" ? "你" : "ANews"}</span>
                  <div className="markdown-body">{renderMarkdownMessage(message.content)}</div>
                </div>
              ))
            )}
            {view.chatBusy && (
              <div className="chat-message chat-message--assistant">
                <span>ANews</span>
                <div className="markdown-body">
                  <p>正在查询偏好、搜索、写入新闻池或整理回答...</p>
                </div>
              </div>
            )}
          </div>
          {actionParts.length > 0 && (
            <div className="chat-actions">
              {actionParts.map((item) => (
                <span key={item}>{item}</span>
              ))}
              {view.chatActions?.push_news_count > 0 && (
                <button type="button" onClick={() => actions.setActive("push")}>
                  查看推送
                </button>
              )}
            </div>
          )}
        </div>
        <form className="command-form chat-composer" onSubmit={actions.sendChatMessage}>
          <input
            value={view.chatInput}
            onChange={(event) => actions.setChatInput(event.target.value)}
            placeholder="输入新闻查询、偏好调整或来源管理指令"
          />
          <button type="submit" disabled={view.chatBusy}>
            <Bot size={16} />
            <span>{view.chatBusy ? "处理中" : "发送"}</span>
          </button>
        </form>
      </div>
    </section>
  );
}

function SourcesPage({ view, actions }) {
  return (
    <section className="panel">
      <header className="panel__header">
        <h2>指定来源</h2>
        <span>{view.sources.length} 个来源</span>
      </header>
      <form className="source-form" onSubmit={actions.addSource}>
        <input
          placeholder="名称"
          value={view.sourceForm.name}
          onChange={(event) => actions.setSourceForm((current) => ({ ...current, name: event.target.value }))}
        />
        <input
          placeholder="URL 或 mock://source"
          value={view.sourceForm.url}
          onChange={(event) => actions.setSourceForm((current) => ({ ...current, url: event.target.value }))}
        />
        <select
          value={view.sourceForm.source_type}
          onChange={(event) =>
            actions.setSourceForm((current) => ({ ...current, source_type: event.target.value }))
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
        {view.sources.length === 0 ? (
          <div className="empty">暂无指定来源</div>
        ) : (
          view.sources.map((source) => (
            <div className="table-row" key={source.id}>
              <div className="row-main">
                <strong>{source.name}</strong>
                <span className="row-detail">{source.url}</span>
                {source.failure_reason && <span className="row-error">{source.failure_reason}</span>}
              </div>
              <div className="row-meta">
                <span className={source.enabled ? "state enabled" : "state muted"}>
                  {source.enabled ? "启用" : "停用"}
                </span>
                <span>{source.source_type}</span>
                <span>{source.user_specified ? "用户指定" : "默认"}</span>
                <button type="button" onClick={() => actions.toggleSource(source)}>
                  {source.enabled ? "停用" : "启用"}
                </button>
                <button
                  className="icon-button danger"
                  type="button"
                  onClick={() => actions.deleteSource(source)}
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
  );
}

function PreferencesPage({ view, actions }) {
  return (
    <section className="panel">
      <header className="panel__header">
        <h2>偏好</h2>
        <span>{view.preferences.length} 条规则</span>
      </header>
      <div className="table-list">
        {view.preferences.length === 0 ? (
          <div className="empty">暂无偏好记录</div>
        ) : (
          view.preferences.map((preference) => (
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
                onClick={() => actions.deletePreference(preference.id)}
                title="删除偏好"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function FollowsPage({ view, actions }) {
  return (
    <section className="panel">
      <header className="panel__header">
        <h2>跟进事件</h2>
        <span>{view.follows.length} 个事件</span>
      </header>
      <div className="table-list">
        {view.follows.length === 0 ? (
          <div className="empty">暂无跟进事件</div>
        ) : (
          view.follows.map((follow) => (
            <div className="table-row" key={follow.id}>
              <div className="row-main">
                <strong>{follow.title}</strong>
                <span>
                  {asArray(follow.keywords).join(" / ") || "无关键词"} / {formatTime(follow.created_at)}
                </span>
              </div>
              <button type="button" onClick={() => actions.cancelFollow(follow.id)}>
                取消
              </button>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function SettingsPage({ view }) {
  return (
    <div className="settings-stack">
      <ProviderPanel title="DeepSeek 设置" statusValue={view.aiStatus}>
        <span>Provider</span>
        <strong>{view.aiStatus?.provider || "deepseek"}</strong>
        <span>Model</span>
        <strong>{view.aiStatus?.model || "deepseek-v4-flash"}</strong>
        <span>Base URL</span>
        <strong>{view.aiStatus?.base_url || "https://api.deepseek.com"}</strong>
        <span>API Key</span>
        <strong>{view.aiStatus?.api_key_configured ? "已配置" : "未配置"}</strong>
        <span>可用状态</span>
        <strong>{providerStateLabel(view.aiStatus)}</strong>
        <span>降级原因</span>
        <strong>{view.aiStatus?.degradation_reason || "无"}</strong>
        <span>Fallback</span>
        <strong>{view.aiStatus?.fallback_enabled ? "启用" : "关闭"}</strong>
      </ProviderPanel>
      <ProviderPanel title="搜索 API" statusValue={view.searchStatus}>
        <span>Provider</span>
        <strong>{view.searchStatus?.provider || "tavily"}</strong>
        <span>API Key</span>
        <strong>{view.searchStatus?.configured ? "已配置" : "未配置"}</strong>
        <span>可用状态</span>
        <strong>{providerStateLabel(view.searchStatus)}</strong>
        <span>降级原因</span>
        <strong>{view.searchStatus?.degradation_reason || "无"}</strong>
        <span>搜索深度</span>
        <strong>{view.searchStatus?.search_depth || "basic"}</strong>
        <span>额度策略</span>
        <strong>{view.searchStatus?.credit_policy || "basic search uses 1 Tavily API credit"}</strong>
        <span>工具预算</span>
        <strong>{view.searchStatus?.agent_max_tool_calls || "未配置"}</strong>
        <span>搜索预算</span>
        <strong>{view.searchStatus?.agent_max_search_queries || "未配置"}</strong>
        <span>读 URL 预算</span>
        <strong>{view.searchStatus?.agent_max_read_urls || "未配置"}</strong>
        <span>探活</span>
        <strong>{view.searchStatus?.live_check_note || "未执行"}</strong>
      </ProviderPanel>
      <section className="panel">
        <header className="panel__header">
          <h2>最近 Agent 推送</h2>
          <span>{view.lastAgentRun?.status || "暂无"}</span>
        </header>
        <div className="settings-grid">
          <span>Run ID</span>
          <strong>{view.lastAgentRun?.id || view.lastAgentRun?.run_id || "无"}</strong>
          <span>状态</span>
          <strong>{view.lastAgentRun?.status || "无"}</strong>
          <span>是否降级</span>
          <strong>{view.lastAgentRun?.degraded ? "是" : "否"}</strong>
          <span>降级原因</span>
          <strong>{view.lastAgentRun?.degradation_reason || "无"}</strong>
        </div>
      </section>
    </div>
  );
}

function ProviderPanel({ title, statusValue, children }) {
  return (
    <section className="panel">
      <header className="panel__header">
        <h2>{title}</h2>
        <span>{providerStateLabel(statusValue)}</span>
      </header>
      <div className="settings-grid">{children}</div>
    </section>
  );
}

function ArticleDrawer({ news, actions }) {
  if (!news) return null;
  const fallbackMarkdown = `## ${news.title || "新闻详情"}\n\n${
    news.summary || "这条新闻暂未生成本地文章快照。"
  }\n\n### 原始来源\n- ${news.source_name || "未知来源"}: ${news.url || "无"}`;

  return (
    <div className="drawer-layer">
      <button aria-label="关闭详情" className="drawer-scrim" type="button" onClick={actions.closeDetail} />
      <aside className="drawer drawer--article" aria-label="新闻详情">
        <button className="drawer__close" type="button" onClick={actions.closeDetail}>
          关闭
        </button>
        <p className="drawer__meta">
          {news.source_name || "未知来源"} / {formatTime(news.published_at)}
        </p>
        <h2>{news.article_snapshot?.title || news.title}</h2>
        <p>{news.summary || "暂无摘要。"}</p>
        <div className="tag-row">
          {asArray(news.tags).map((tag) => (
            <span className="tag" key={tag}>
              {tag}
            </span>
          ))}
        </div>
        <div className="reason-list">
          {asArray(news.recommendation_reasons).map((reason) => (
            <span key={reason}>{reason}</span>
          ))}
        </div>
        <div className="article-reader">
          <div className="article-reader__bar">
            <span>{news.article_snapshot?.status === "translated" ? "本地中文快照" : "摘要快照"}</span>
            <span>{news.article_snapshot?.layout_style || "article"}</span>
          </div>
          <div className="markdown-body article-reader__body">
            {news.article_snapshot?.markdown
              ? renderMarkdownMessage(news.article_snapshot.markdown)
              : renderMarkdownMessage(fallbackMarkdown)}
          </div>
        </div>
        {news.url && (
          <div className="source-evidence">
            <span>原始来源</span>
            <strong>{news.url}</strong>
          </div>
        )}
      </aside>
    </div>
  );
}

function renderActivePage(view, actions) {
  const Page = pageRegistry[view.active] || pageRegistry.push;
  return <Page actions={actions} view={view} />;
}

export function App() {
  const { dashboardView, dashboardActions } = useAnewsDashboard();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>ANews</span>
          <small>新闻工作台</small>
        </div>
        <nav aria-label="主导航">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={dashboardView.active === item.id ? "active" : ""}
                key={item.id}
                type="button"
                onClick={() => dashboardActions.setActive(item.id)}
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
            <p>{dashboardView.pageTitle}</p>
            <h1>新闻工作台</h1>
            <span>抓取、排序、推送和跟进都在 App 内完成。</span>
          </div>
          <div className="topbar__status">
            <span className={providerStateClass(dashboardView.aiStatus)} title={dashboardView.aiStatus?.degradation_reason || ""}>
              DeepSeek {providerStateLabel(dashboardView.aiStatus)}
            </span>
            <span
              className={providerStateClass(dashboardView.searchStatus)}
              title={dashboardView.searchStatus?.degradation_reason || dashboardView.searchStatus?.live_check_note || ""}
            >
              搜索 API {providerStateLabel(dashboardView.searchStatus)}
            </span>
            <span className="connection-status" title={dashboardView.status}>
              {dashboardView.status}
            </span>
            <span>上次 {formatTime(dashboardView.bundle.last_push_at)}</span>
            <span>下次 {formatTime(dashboardView.bundle.next_push_at)}</span>
          </div>
        </header>

        <PushProgress progress={dashboardView.pushProgress} />
        {renderActivePage(dashboardView, dashboardActions)}
      </main>

      <ArticleDrawer actions={dashboardActions} news={dashboardView.selectedNews} />
    </div>
  );
}
