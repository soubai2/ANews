# ANews

ANews 是一个面向 Windows 桌面的新闻推送 Agent。项目由本地 FastAPI 后端和 Electron + React 桌面前端组成，用于在 App 内完成新闻抓取、排序、推送、阅读、关注、跟进、来源管理和对话查询。

## 核心能力

- 每隔 2 小时执行一次新闻抓取、入库、排序和推送。
- 按 `last_push_at - 10 分钟` 到 `now + 10 分钟` 的窗口抓取新新闻，降低来源发布时间误差带来的漏抓风险。
- 推送页包含“最新”“相关”“跟进”三个板块。
- 用户可对新闻点击“关注”，让主题、来源、实体和关键词进入偏好体系。
- 用户可对新闻点击“跟进”，让 Agent 在后续推送中追踪事件变化。
- 用户可添加指定来源，例如新闻站点、RSS、公司公告页、监管披露页或博客。
- 支持 DeepSeek 模型增强摘要、筛选、推荐原因和本地中文文章快照。
- 支持 Tavily 搜索作为联网新闻检索来源，也可使用 mock 来源做本地验证。

## 技术栈

- 后端：Python 3.13+、FastAPI、APScheduler、SQLite、httpx
- 桌面端：Electron、React、Vite、lucide-react
- AI：DeepSeek 优先，兼容 `OPENAI_*` 环境变量别名
- 搜索：Tavily 或 mock provider

## 项目结构

```text
.
├── src/anews_agent/          # Python 后端、Agent 运行时、存储、评分、搜索和 API
│   ├── api/                  # FastAPI app 与服务入口
│   ├── agent_push.py         # 模型搜索推送流程
│   ├── agent_runtime.py      # 工具调用运行时
│   ├── storage.py            # SQLite schema 与 Repository
│   └── ...
├── desktop/                  # Electron + React 桌面 App
│   ├── electron/             # Electron main/preload
│   └── src/                  # React UI
├── tests/                    # Python 测试
├── docs/                     # 设计文档与计划软件工程文档
├── .anews.env.example        # 本地配置示例
└── pyproject.toml            # Python 项目配置
```

## 本地配置

复制配置示例：

```powershell
Copy-Item .anews.env.example .anews.env
```

常用配置项：

```env
ANEWS_DB_PATH=anews.db

DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT_SECONDS=60

ANEWS_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=
ANEWS_SEARCH_BASE_URL=https://api.tavily.com/search
ANEWS_SEARCH_TIMEOUT_SECONDS=15

ANEWS_AGENT_MAX_TOOL_CALLS=16
ANEWS_AGENT_MAX_SEARCH_QUERIES=8
ANEWS_AGENT_MAX_READ_URLS=20
```

未配置 DeepSeek 或 Tavily Key 时，相关功能会进入降级状态；基础后端、mock 来源、偏好、跟进和本地数据管理仍可用于开发验证。

## 安装依赖

后端：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m pip install pytest
```

桌面端：

```powershell
Set-Location desktop
npm install
Set-Location ..
```

## 运行项目

方式一：直接启动 Electron。Electron 会自动启动本地后端，并将后端绑定到 `127.0.0.1:8765`。

```powershell
Set-Location desktop
npm start
```

方式二：分别启动后端和前端，适合调试 API 与 UI。

```powershell
# 终端 1：启动后端
.\.venv\Scripts\Activate.ps1
python -m anews_agent.api.server
```

```powershell
# 终端 2：启动桌面端
Set-Location desktop
npm start
```

后端健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

## 常用 API

- `GET /api/health`：健康检查
- `GET /api/push`：读取当前推送结果
- `POST /api/push/run`：运行基础推送流程
- `POST /api/agent/push/run`：运行模型搜索推送流程
- `GET /api/news?q=关键词`：检索本地新闻池
- `POST /api/news/{news_id}/focus`：关注或取消关注新闻
- `POST /api/news/{news_id}/follow`：跟进或取消跟进新闻
- `GET /api/sources` / `POST /api/sources`：管理指定来源
- `GET /api/preferences`：查看偏好
- `GET /api/follows`：查看跟进事件
- `POST /api/chat/sessions`：创建对话会话
- `POST /api/chat/sessions/{session_id}/messages`：发送对话消息
- `GET /api/ai/status`：查看模型配置状态
- `GET /api/search/status`：查看搜索配置状态

## 测试

运行 Python 测试：

```powershell
python -m pytest
```

运行桌面端契约测试：

```powershell
Set-Location desktop
npm run test:contracts
```

构建桌面前端：

```powershell
Set-Location desktop
npm run build
```

## 数据与本地文件

- 默认数据库为项目根目录下的 `anews.db`。
- `.anews.env` 保存本地 API Key 和运行配置，不应提交到仓库。
- 用户来源、偏好、跟进事件、新闻池、Agent 运行记录、搜索结果和文章快照都写入 SQLite。

## 开发备注

- 桌面端 API Base 固定为 `http://127.0.0.1:8765`。
- Electron main 进程会以 `python -m anews_agent.api.server` 启动后端，并设置 `PYTHONPATH=src`。
- 定时推送由 APScheduler 驱动，默认间隔来自 `ANEWS_PUSH_INTERVAL_HOURS`，默认值为 2。
- 模型搜索推送要求先查询偏好，再执行搜索或读 URL，最后选择推送项；运行轨迹可通过 `/api/agent/runs/{run_id}/trace` 查看。
