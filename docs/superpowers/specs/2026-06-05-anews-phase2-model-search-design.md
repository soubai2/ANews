# ANews Phase 2 Model-Search News Agent Design

## 目标

二期目标是把 ANews 从“本地新闻抓取和展示工具”升级为真正可用的联网新闻 Agent。系统必须以 DeepSeek 为首选模型，让模型主动读取用户偏好知识库、制定搜索计划、调用联网搜索工具、读取网页证据、筛选新闻、解释推荐原因，并最终生成 App 内推送和对话答案。

本阶段最重要的产品约束：

> 所有真实新闻推送更新都必须通过模型的 search 模块实现。无论是 2 小时定时推送、手动刷新，还是跟进事件更新，都必须先让模型读取偏好，再由模型生成搜索任务、调用搜索工具、筛选结果并产出推送。

旧的 RSS/URL 抓取和规则排序能力只能作为工具、缓存、测试夹具或显式离线演示模式存在，不能作为真实推送主路径绕过模型。

## 当前问题

MVP 已经完成基本桌面 App、后端 API、SQLite、新闻池、关注、跟进、来源管理和 DeepSeek-first AI 增强，但仍存在几个关键缺口：

- 对话页不是完整大模型对话，只是本地命令入口和新闻查询入口。
- DeepSeek 主要用于新闻摘要、标签和推荐原因增强，没有参与联网搜索决策。
- 定时推送仍以本地 source adapter 抓取为主，不是模型驱动的 search agent。
- 用户偏好只是排序输入，不是模型可主动查询和更新的知识库。
- 跟进、关注等按钮缺少明确的已操作状态，用户无法判断是否生效。
- 对话过程没有展示“正在搜索、正在读取、正在筛选、正在生成答案”的过程反馈。

## 架构原则

- DeepSeek 是首选模型提供方，不默认使用 GPT 或 OpenAI。
- DeepSeek 负责决策，后端负责执行工具、校验参数、落库、限流和审计。
- 模型不能直接联网。所有联网能力必须通过后端暴露的 search/read 工具实现。
- 所有推送结果必须可追溯到搜索 query、工具调用、来源 URL、证据片段、命中的偏好和筛选理由。
- 没有模型配置时，真实推送应进入“需要配置模型”的状态；离线规则 fallback 只能用于测试和显式演示，不应伪装成真实联网推送。
- App 内优先原则保持不变：搜索、阅读、关注、跟进、偏好管理和来源管理都在 App 内完成。

## 二期核心组件

### 1. Agent Runtime

新增模型工具调用运行时，负责执行以下循环：

1. 构造 system prompt、用户消息、推送上下文或定时任务上下文。
2. 把可用工具以 function schema 形式提供给 DeepSeek。
3. 接收模型返回的 tool call。
4. 后端校验 tool arguments。
5. 执行工具并把结果作为 tool message 回传给模型。
6. 重复直到模型产出最终推送包或对话答案。
7. 保存完整 trace。

每轮 Agent 运行必须有预算：

- 最大工具调用次数。
- 最大搜索 query 数。
- 最大读取 URL 数。
- 最大 tokens。
- 最大运行时长。
- 最大并发抓取数。

### 2. Search Module

Search 模块不是一个简单后端搜索函数，而是模型可调用的工具集合。建议工具边界：

- `query_preferences`：读取偏好知识库、负偏好、指定来源、历史行为摘要。
- `search_web`：联网搜索新闻、公告、官网、监管披露、博客或行业媒体。
- `search_user_sources`：优先查询用户指定来源。
- `read_url`：读取并清洗网页正文，返回标题、发布时间、正文摘要、关键片段和可引用 URL。
- `query_news_pool`：查询本地新闻池，避免重复推送并补充历史上下文。
- `query_followed_stories`：读取用户跟进事件，生成跟进搜索计划。
- `write_candidate_news`：把候选新闻标准化并写入候选池。
- `select_push_items`：提交模型筛选后的最新、相关、跟进结果。
- `update_preferences`：在用户明确表达长期兴趣或负偏好时更新知识库。
- `explain_ranking`：根据 trace、偏好和证据解释为什么推荐某条新闻。

搜索供应商通过接口抽象：

- `SearchProvider.search(query, time_window, domains, language, limit)`
- `WebReader.read(url)`
- `SourceCrawler.search_source(source, time_window, query)`

具体供应商可以后续选择 Brave Search、Tavily、Bing Web Search、SerpAPI 或其他 API。工程上先实现 provider protocol、mock provider 和一个真实 provider adapter，避免把业务逻辑绑定到单一搜索供应商。

### 3. Preference Knowledge Base

偏好知识库必须既能被模型查询，也能被系统稳定更新。首版使用 SQLite，不引入独立向量数据库。

核心数据：

- 主题偏好：AI 芯片、公司公告、政策、开源项目等。
- 实体偏好：公司、人物、产品、股票代码、项目名、地区。
- 来源偏好：用户指定网站、可信来源、英文来源优先等。
- 负偏好：减少娱乐新闻、排除标题党来源、降低重复转载。
- 行为信号：阅读、关注、跟进、忽略、取消跟进、删除偏好。
- 模型生成的偏好摘要：压缩成可直接放进 prompt 的短文本。
- 更新时间、权重、来源和触发原因。

检索方式：

- 结构化查询用于强约束。
- SQLite FTS5 用于关键词和实体检索。
- 后续可加 embedding 表，实现语义偏好匹配。

模型查询偏好时，后端不应把完整历史全部塞进上下文，而应返回：

- 高权重偏好。
- 近期行为变化。
- 负偏好。
- 必抓来源。
- 当前任务相关偏好。

### 4. Model-Driven Push Pipeline

二期推送流程必须改为：

1. 定时器或用户手动触发 `run_push`.
2. 创建 `push_run`，状态为 `running`.
3. Agent 调用 `query_preferences` 获取偏好知识库摘要。
4. Agent 调用 `query_followed_stories` 获取跟进事件。
5. Agent 生成本轮搜索计划，包括：
   - 用户高度关注主题。
   - 用户指定来源。
   - 正在跟进事件。
   - 主流重大新闻补充。
   - 负偏好规避。
6. Agent 多次调用 `search_web`、`search_user_sources` 和 `read_url`.
7. 后端把结果标准化为候选新闻，做 URL、标题、来源、发布时间和摘要指纹去重。
8. Agent 查询本地新闻池，判断是否重复、是否有新增事实。
9. Agent 对候选新闻筛选、合并、评分，并生成：
   - `latest`：本轮新增。
   - `relevant`：与偏好和主流热点最相关。
   - `follow_updates`：跟进事件的实质更新。
10. 后端校验输出结构和来源证据。
11. 写入新闻池、推送结果和 trace。
12. 只有整轮成功时才推进 `last_push_at`.

如果模型、搜索 API 或关键工具失败，本轮不得错误推进 `last_push_at`。失败原因要在 App 内显示，并写入 `push_runs`。

### 5. Chat Agent

对话页要从“命令框”升级为真正的 Agent 聊天。

用户可以问：

- “今天 AI 芯片有什么重要新闻？”
- “帮我查英伟达最近两小时的公告和相关新闻。”
- “为什么这条新闻排在相关第一？”
- “以后少给我推娱乐新闻，多看英文科技媒体。”
- “继续跟进这条并告诉我后续有无官方回应。”

对话流程：

1. 用户消息写入 `chat_messages`.
2. Agent 查询偏好和当前新闻池。
3. 如需联网，调用 search/read 工具。
4. 返回带引用来源的答案。
5. 如果用户表达偏好变化，模型必须调用 `update_preferences`。
6. 如果用户要求跟进，模型必须调用 `follow_story`。

前端必须展示：

- 用户消息。
- 助手消息。
- 工具过程状态，例如“正在搜索”“正在读取 3 个网页”“正在整理答案”。
- 引用来源卡片。
- 可执行后续动作，例如关注、跟进、添加来源。

### 6. Frontend Interaction

二期需要修复 MVP 交互反馈：

- 新闻卡片显示 `is_focused`、`is_followed`、`is_read`。
- 点击关注后按钮立即变成“已关注”，图标填充或使用明确选中样式。
- 点击跟进后按钮立即变成“已跟进”，并显示跟进状态。
- 操作期间按钮进入 loading/disabled 状态，失败后恢复并显示错误。
- 推送刷新期间显示 Agent 执行状态，而不是只显示一个顶部状态文本。
- 对话页显示消息流和工具执行过程。
- App 内阅读页保留返回、引用信息和源网页读取失败提示。

### 7. Data Model Additions

需要在现有 SQLite schema 上新增或扩展：

- `chat_sessions`
- `chat_messages`
- `agent_runs`
- `agent_tool_calls`
- `search_queries`
- `search_results`
- `retrieved_documents`
- `candidate_news`
- `push_selections`
- `preference_facts`
- `preference_summaries`
- `news_user_state`

`news_user_state` 用于稳定表达单条新闻的用户状态：

- `news_id`
- `is_read`
- `is_focused`
- `is_followed`
- `last_action_at`

### 8. API Surface

新增或调整 API：

- `POST /api/chat/sessions`
- `GET /api/chat/sessions`
- `GET /api/chat/sessions/{session_id}`
- `POST /api/chat/sessions/{session_id}/messages`
- `GET /api/chat/sessions/{session_id}/events`
- `POST /api/agent/push/run`
- `GET /api/agent/runs/{run_id}`
- `GET /api/agent/runs/{run_id}/trace`
- `GET /api/search/results`
- `GET /api/preferences/knowledge`
- `POST /api/preferences/knowledge`
- `PATCH /api/news/{news_id}/state`

保留旧 API，但真实刷新入口逐步迁移到 `POST /api/agent/push/run`。

### 9. Observability

每次模型搜索和推送必须保存：

- run 类型：scheduled push、manual push、chat、follow-up check。
- 输入上下文摘要。
- 模型 provider、model、base URL 和配置状态。
- tool calls 顺序、参数和耗时。
- 搜索 query。
- 被读取 URL。
- 候选新闻数量。
- 被筛掉新闻的主要原因。
- 最终入选新闻和推荐理由。
- 错误和重试信息。

App 设置页或调试面板可以展示最近一次 Agent run trace，便于判断系统是不是“真的在搜索”。

## 验收标准

二期完成后，必须满足：

- 手动刷新和定时刷新都走模型 search pipeline。
- 没有 DeepSeek key 时不会伪装成真实联网推送。
- 用户能看到 Agent 正在搜索、读取和筛选。
- 对话页能联网回答新闻问题，并带来源引用。
- 用户关注和跟进后，新闻卡片状态立即变化并持久化。
- 模型能读取偏好知识库并据此生成搜索 query。
- 用户在对话中表达偏好变化后，偏好知识库会更新。
- 每条推送新闻都有来源 URL、推荐原因、命中的偏好或主流热点理由。
- 跟进板块只展示有实质变化的更新。
- Agent run trace 能解释“为什么推这条”和“搜索过什么”。

## 参考

- DeepSeek Tool Calls 官方文档：https://api-docs.deepseek.com/guides/tool_calls
- DeepSeek Chat Completion 官方文档：https://api-docs.deepseek.com/api/create-chat-completion
