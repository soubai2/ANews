import {
  Bell,
  Bot,
  ExternalLink,
  Heart,
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

function formatError(error) {
  if (error instanceof Error && error.message) return error.message;
  return "请求失败";
}

function extractSourceUrl(text) {
  const match = text.match(/\b(https?:\/\/\S+|mock:\/\/\S+)/i);
  return match?.[1]?.replace(/[，。,.]+$/, "") || "";
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

function NewsCard({ item, onFocus, onFollow, onOpen }) {
  const tags = asArray(item.tags).slice(0, 4);
  const reasons = asArray(item.recommendation_reasons).slice(0, 2);

  return (
    <article className="news-card">
      <div className="news-card__meta">
        <span className="truncate">{item.source_name || "未知来源"}</span>
        <span>{formatTime(item.published_at)}</span>
        <span>{item.category || "general"}</span>
        <span className="score">重要性 {formatScore(item.importance_score)}</span>
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
        <button type="button" onClick={() => onFocus(item.id)} title="加入长期关注">
          <Heart size={16} />
          <span>关注</span>
        </button>
        <button type="button" onClick={() => onFollow(item.id)} title="跟进后续变化">
          <Star size={16} />
          <span>跟进</span>
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
  const [readerUrl, setReaderUrl] = useState("");
  const [sourceForm, setSourceForm] = useState({
    name: "",
    url: "",
    source_type: "news",
  });
  const [command, setCommand] = useState("");
  const detailRequestRef = useRef(0);

  async function refreshAll() {
    try {
      await api.health();
      const [push, sourceList, preferenceList, followList, ai, search] = await Promise.all([
        api.getPush(),
        api.listSources(),
        api.listPreferences(),
        api.listFollows(),
        api.aiStatus(),
        api.searchStatus(),
      ]);
      setBundle(normalizeBundle(push));
      setSources(asArray(sourceList));
      setPreferences(asArray(preferenceList));
      setFollows(asArray(followList));
      setAiStatus(ai || null);
      setSearchStatus(search || null);
      setStatus("已连接");
    } catch (error) {
      setStatus(`后端不可用：${formatError(error)}`);
    }
  }

  async function runPush() {
    setStatus("正在通过模型搜索推送");
    try {
      const result = await api.runAgentPush();
      setLastAgentRun(result?.run || null);
      setStatus(`模型推送完成：${result?.run?.id || "已完成"}`);
      await refreshAll();
    } catch (error) {
      setLastAgentRun(error.detail || null);
      const reason = error.detail?.degradation_reason || error.detail?.error_message;
      setStatus(`模型推送失败：${reason || formatError(error)}`);
    }
  }

  async function focusNews(id) {
    if (!id) return;
    setStatus("正在更新偏好");
    try {
      await api.focusNews(id);
      await refreshAll();
    } catch (error) {
      setStatus(`关注失败：${formatError(error)}`);
    }
  }

  async function followNews(id) {
    if (!id) return;
    setStatus("正在添加跟进");
    try {
      await api.followNews(id);
      await refreshAll();
    } catch (error) {
      setStatus(`跟进失败：${formatError(error)}`);
    }
  }

  async function openNews(item) {
    if (!item?.id) return;
    const requestId = detailRequestRef.current + 1;
    detailRequestRef.current = requestId;
    setReaderUrl("");
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
    setReaderUrl("");
  }

  function openOriginalInApp(event) {
    event.preventDefault();
    if (!selectedNews?.url) return;
    setReaderUrl(selectedNews.url);
    setStatus("正在应用内打开原文");
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

  async function runCommand(event) {
    event.preventDefault();
    const text = command.trim();
    if (!text) return;

    setStatus("正在处理指令");
    try {
      const sourceUrl = extractSourceUrl(text);
      if (sourceUrl && /(添加|来源|source|add)/i.test(text)) {
        await api.addSource({
          name: sourceUrl.startsWith("mock://") ? "对话添加模拟来源" : "对话添加来源",
          url: sourceUrl,
          source_type: sourceUrl.startsWith("mock://") ? "mock" : "news",
          user_specified: true,
        });
        setActive("sources");
        setCommand("");
        await refreshAll();
        return;
      }

      if (text.toLowerCase().includes("mock")) {
        await api.addSource({
          name: "对话添加模拟来源",
          url: `mock://dialog-${Date.now()}`,
          source_type: "mock",
          user_specified: true,
        });
        setActive("sources");
        setCommand("");
        await refreshAll();
        return;
      }

      const results = await api.listNews(text);
      setBundle((current) =>
        normalizeBundle({
          ...current,
          latest: asArray(results),
          relevant: asArray(results),
        }),
      );
      setActive("push");
      setCommand("");
      setStatus(`查询返回 ${asArray(results).length} 条新闻`);
    } catch (error) {
      setStatus(`指令失败：${formatError(error)}`);
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
            <button type="button" onClick={runPush} title="立即执行一轮推送">
              <Play size={16} />
              <span>刷新</span>
            </button>
          </div>
        </header>

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
                onFocus={focusNews}
                onFollow={followNews}
                onOpen={openNews}
              />
              <Section
                title="相关"
                items={bundle.relevant}
                empty="暂无高相关新闻"
                onFocus={focusNews}
                onFollow={followNews}
                onOpen={openNews}
              />
              <Section
                title="跟进"
                items={bundle.follow_updates}
                empty="暂无跟进更新"
                onFocus={focusNews}
                onFollow={followNews}
                onOpen={openNews}
              />
            </div>
          </>
        )}

        {active === "dialog" && (
          <section className="panel">
            <header className="panel__header">
              <h2>Agent 控制台</h2>
              <span>查询、添加来源或立即推送</span>
            </header>
            <form className="command-form" onSubmit={runCommand}>
              <input
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                placeholder="例如：AI 芯片新闻，或 添加来源 mock://tech"
              />
              <button type="submit">
                <Bot size={16} />
                <span>执行</span>
              </button>
            </form>
            <div className="hint-row">
              <button type="button" onClick={runPush}>
                <Play size={16} />
                <span>立即推送</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setCommand("添加来源 mock://tech");
                }}
              >
                <Plus size={16} />
                <span>填入模拟来源</span>
              </button>
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
          <aside
            className={readerUrl ? "drawer drawer--reader" : "drawer"}
            aria-label="新闻详情"
          >
            <button className="drawer__close" type="button" onClick={closeDetail}>
              关闭
            </button>
            <p className="drawer__meta">
              {selectedNews.source_name || "未知来源"} / {formatTime(selectedNews.published_at)}
            </p>
            <h2>{selectedNews.title}</h2>
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
            {selectedNews.url && (
              <a className="drawer-link" href={selectedNews.url} onClick={openOriginalInApp}>
                <ExternalLink size={16} />
                <span>在应用内打开原文</span>
              </a>
            )}
            {readerUrl && (
              <div className="reader-panel">
                <div className="reader-panel__bar">
                  <span>{readerUrl}</span>
                  <button type="button" onClick={() => setReaderUrl("")}>
                    收起
                  </button>
                  <button type="button" onClick={() => setReaderUrl(selectedNews.url)}>
                    重试
                  </button>
                </div>
                <iframe
                  className="reader-frame"
                  src={readerUrl}
                  title={selectedNews.title || "新闻原文"}
                  sandbox="allow-forms allow-popups allow-same-origin allow-scripts"
                  referrerPolicy="no-referrer-when-downgrade"
                  onError={() => setStatus("原文无法在应用内显示，可重试")}
                />
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
