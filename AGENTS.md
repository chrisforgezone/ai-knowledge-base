# AGENTS.md

## 1. 项目概述

AI 知识库助手是一个自动化技术情报管线：每天 19:00（UTC+8）从 GitHub Trending 和 Hacker News 抓取 AI/LLM/Agent 领域的最新动态，经 DeepSeek 语义分析与结构化处理后存储为 JSON 知识条目，最终通过 Telegram Bot 和飞书 Webhook 多渠道推送给订阅者，帮助团队持续追踪 AI 前沿进展。

## 2. 技术栈

| 组件 | 技术选型 | 用途 |
|------|---------|------|
| 运行时 | Python 3.13 | 核心编程语言 |
| AI 编排 | OpenCode + DeepSeek | Agent 驱动的内容采集、分析、整理 |
| 工作流引擎 | LangGraph | 定义采集→分析→分发多步骤有状态管道 |
| 网页抓取 | OpenClaw | 结构化抓取 GitHub Trending / Hacker News |
| HTTP 客户端 | httpx | 异步 HTTP 请求与 API 调用 |
| 数据校验 | Pydantic v2 | JSON Schema 定义与数据校验 |
| 定时调度 | APScheduler | 每天 19:00 触发采集流水线 |
| 日志工具 | loguru | 结构化日志（替代 print） |
| 配置管理 | python-dotenv + pydantic-settings | 环境变量 / .env 管理 |
| 消息分发 | python-telegram-bot + httpx (飞书 Webhook) | 多渠道推送 |
| 数据库 | 文件系统 JSON（knowledge/） | 轻量级本地知识库存储 |

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    定时调度层 (APScheduler)               │
│                    cron: 0 19 * * *                      │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   Agent 编排层 (OpenCode)                 │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐      │
│  │ 采集 Agent │───▶│ 分析 Agent │───▶│ 整理 Agent   │ ───▶ 分发Agent     │
│  │ Collector │    │ Analyzer  │    │ Organizer    │    │ Distributor     │            
│  └──────────┘    └──────────┘    └──────────────┘      │
│                                                         │
│              工作流引擎: LangGraph                        │
└─────────────────────┬───────────────────────────────────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
┌────────────┐ ┌───────────┐ ┌──────────┐
│ OpenClaw   │ │ DeepSeek  │ │ httpx    │
│ 网页抓取    │ │ AI 分析   │ │ 消息推送  │
└────────────┘ └───────────┘ └──────────┘
          │           │           │
          ▼           ▼           ▼
    GitHub/HN   knowledge/   Telegram/飞书
```

### 各组件职责

| 组件 | 职责 |
|------|------|
| **APScheduler** | 定时触发：每天 19:00 启动 LangGraph 工作流 |
| **LangGraph 工作流** | 编排采集→分析→分发三阶段，管理状态传递与错误重试 |
| **采集 Agent (OpenCode)** | 驱动 OpenClaw 从 GitHub Trending / HN 抓取 AI 相关条目原始数据 |
| **分析 Agent (OpenCode)** | 调用 DeepSeek 对原始条目做语义摘要、标签提取、去重、质量评分 |
| **整理 Agent (OpenCode)** | 结构化输出为 JSON，写入 knowledge/，生成分发摘要 |
| **分发层 (httpx)** | 通过 Telegram Bot API / 飞书机器人 Webhook 推送知识条目 |

## 4. 编码规范

### 4.1 风格指南
- **PEP 8** — 严格遵循 Python 官方风格指南
- **snake_case** — 全部变量名、函数名、模块名使用 snake_case；类名使用 PascalCase
- **类型标注** — 所有函数签名必须包含完整类型标注（参数、返回值）
- **Google 风格 docstring** — 所有公开函数/类使用 Google 风格文档字符串，必须包含 `Args:` / `Returns:` / `Raises:` 段落

### 4.2 日志
```python
# ✅ 正确
from loguru import logger
logger.info("开始采集 GitHub Trending")

# ❌ 禁止
print("开始采集")  # 项目中禁止任何裸 print()
```

### 4.3 数据模型
```python
# ✅ 正确：使用 Pydantic 建模
from pydantic import BaseModel, HttpUrl
from datetime import datetime

class KnowledgeEntry(BaseModel):
    id: str
    title: str
    source_url: HttpUrl
    ...
```

### 4.4 其他约定
- 所有敏感配置通过 `.env` 注入，禁止硬编码密钥
- 异步优先：IO 密集型操作使用 `async/await`
- 单文件不超过 300 行，超过即拆分为模块
- 提交前必须通过 `ruff check` 和 `mypy` 静态检查

## 5. 项目结构

```
ai-knowledge-base/
├── .opencode/                  # OpenCode 插件运行时
│   ├── agents/                 # Agent 定义文件（*.md 或 *.json）
│   │   ├── collector.md        #   采集 Agent 指令
│   │   ├── analyzer.md         #   分析 Agent 指令
│   │   └── organizer.md        #   整理 Agent 指令
│   ├── skills/                 # 可复用技能模块
│   └── package.json            # 插件依赖
│
├── knowledge/                  # 知识库存储
│   ├── raw/                    # 原始抓取数据（采集阶段中间产物）
│   │   ├── github_trending_YYYYMMDD.json
│   │   ├── hacker_news_YYYYMMDD.json
│   │   └── tech_summary-YYYY-MM-DD.json
│   └── articles/               # 最终结构化知识条目（JSON）
│       ├── index.json          #   条目索引（id → 文件路径映射）
│       └── YYYY/MM/           #   按年月分目录
│           └── {uuid}.json     #   单条知识条目
│
├── src/                        # Python 源码
│   ├── __init__.py
│   ├── main.py                 #   入口：启动调度器
│   ├── config.py               #   配置管理（pydantic-settings）
│   ├── pipeline/               #   LangGraph 工作流
│   │   ├── __init__.py
│   │   ├── graph.py            #     工作流图定义
│   │   ├── state.py            #     工作流状态模型
│   │   └── nodes/              #     工作流节点实现
│   │       ├── __init__.py
│   │       ├── collect.py      #       采集节点
│   │       ├── analyze.py      #       分析节点
│   │       ├── organize.py     #       整理节点
│   │       └── distribute.py   #       分发节点
│   ├── agents/                 #   Agent 运行时封装（调用 OpenCode）
│   │   ├── __init__.py
│   │   ├── collector.py
│   │   ├── analyzer.py
│   │   └── organizer.py
│   ├── crawlers/               #   网页抓取模块（OpenClaw 封装）
│   │   ├── __init__.py
│   │   ├── github.py           #     GitHub Trending 抓取
│   │   └── hackernews.py       #     Hacker News 抓取
│   ├── knowledge/              #   知识库读写
│   │   ├── __init__.py
│   │   ├── models.py           #     Pydantic 数据模型
│   │   ├── store.py            #     存储层（读写 JSON）
│   │   └── index.py            #     索引管理
│   └── channels/               #   分发渠道
│       ├── __init__.py
│       ├── telegram.py         #     Telegram Bot 推送
│       └── feishu.py           #     飞书机器人推送
│
├── tests/                      # 测试
│   ├── __init__.py
│   ├── test_pipeline.py
│   ├── test_crawlers.py
│   └── fixtures/               #   测试用固定数据
│
├── AGENTS.md                   # 本文件
├── .env.example                # 环境变量模板
├── .gitignore
├── pyproject.toml              # 项目元数据与工具配置
├── requirements.txt            # 生产依赖
├── requirements-dev.txt        # 开发依赖
└── README.md
```

## 6. 知识条目 JSON 格式

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "OpenAI 发布 GPT-5 技术报告",
  "source": "hacker_news",
  "source_url": "https://news.ycombinator.com/item?id=12345678",
  "summary": "GPT-5 在推理、多模态、长上下文三方面取得显著突破，MMLU 评测达到 95.2%。",
  "tags": ["LLM", "OpenAI", "benchmark", "多模态"],
  "status": "published",
  "language": "zh",
  "relevance_score": 0.93,
  "stars": 342,
  "author": "OpenAI",
  "published_at": "2026-05-20T10:30:00+08:00",
  "created_at": "2026-05-20T19:05:00+08:00",
  "updated_at": "2026-05-20T19:05:00+08:00"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | `UUID v4` | 是 | 全局唯一标识 |
| `title` | `str` | 是 | 知识标题，≤200 字符 |
| `source` | `Literal["github_trending", "hacker_news"]` | 是 | 数据来源 |
| `source_url` | `HttpUrl` | 是 | 原始链接 |
| `summary` | `str` | 是 | AI 生成的中文摘要，≤500 字符 |
| `tags` | `list[str]` | 是 | 标签，≤8 个，按语义相关性排序 |
| `status` | `Literal["new", "reviewed", "published", "archived"]` | 是 | 条目生命周期状态 |
| `language` | `str` | 是 | 摘要语言（`zh` / `en`） |
| `relevance_score` | `float` | 是 | AI 相关性评分，范围 0.0–1.0 |
| `stars` | `int \| null` | 否 | GitHub Stars 数（仅 GitHub 来源有效） |
| `author` | `str \| null` | 否 | 作者/组织名 |
| `published_at` | `ISO 8601` | 是 | 源文章发布时间 |
| `created_at` | `ISO 8601` | 是 | 知识条目创建时间 |
| `updated_at` | `ISO 8601` | 是 | 知识条目最后更新时间 |

### 状态流转

```
new ──▶ reviewed ──▶ published ──▶ archived
  │                    │
  └────────────────────┘  （低质量条目直接归档）
```

## 7. Agent 角色概览

| Agent | 文件 | 触发时机 | 输入 | 输出 | 核心职责 |
|-------|------|---------|------|------|---------|
| **采集 Agent** (Collector) | `.opencode/agents/collector.md` | 每天 19:00 工作流启动 | 无（自动抓取） | `knowledge/raw/{source}_YYYYMMDD.json` | 驱动 OpenClaw 抓取 GitHub Trending / HN 前 50 条目；按关键词（AI/LLM/Agent）初筛；原始数据暂存 raw/ |
| **分析 Agent** (Analyzer) | `.opencode/agents/analyzer.md` | 采集完成后 | `knowledge/raw/` 原始条目 | 结构化中间结果传递给整理 Agent | 调用 DeepSeek 对每条做摘要、标签提取、相关性评分；与知识库已有条目去重；标记低质量条目 |
| **整理 Agent** (Organizer) | `.opencode/agents/organizer.md` | 分析完成后 | 分析结果集合 | `knowledge/articles/` 新 JSON 文件 | 生成最终 JSON 条目写入 articles/；更新 index.json；生成分发摘要（Top 5 高相关条目） |

## 8. 红线（绝对禁止）

### 8.1 安全红线
- **禁止在代码、配置文件或 commit 中硬编码任何密钥、Token、Webhook URL**
- **禁止将 `.env` 或任何含密钥的文件提交到 Git 仓库**
- **禁止将内部知识条目数据发送到未授权的第三方 API 或外部 LLM**
- **禁止跳过输入校验直接写入知识库**（所有数据必须经 Pydantic 校验）

### 8.2 合规红线
- **禁止以短于 60 秒的间隔对任何目标站点发起 HTTP 请求**（尊重 rate limit）
- **禁止伪造 User-Agent 绕过目标站点的爬虫限制**
- **禁止抓取目标站点 robots.txt 禁用的路径**

### 8.3 工程质量红线
- **禁止在生产代码中使用裸 `print()`**——所有输出必须使用 `loguru` logger
- **禁止跳过 ruff 和 mypy 检查直接提交代码**
- **禁止将未处理过的 raw 数据直接推送到 Telegram/飞书**（必须先经分析 Agent 结构化）
- **禁止单文件超过 300 行而不拆分模块**

### 8.4 数据红线
- **禁止人工修改 `knowledge/articles/` 下的 JSON 文件**——所有修改必须通过整理 Agent
- **禁止删除 `knowledge/raw/` 中除超过 30 天的过期数据之外的任何文件**
- **禁止修改已发布的条目的 `id`**（`status` 和 `updated_at` 可以更新）

### 8.5 操作红线
- **禁止在 main 分支上直接 push——必须先 PR 再 squash merge**
- **禁止在未运行 `pytest` 全量测试通过的前提下合并 PR**
- **禁止在 18:00–20:00（UTC+8）时段内部署或重启定时调度服务**（避免干扰每日采集）
