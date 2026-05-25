---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# 技术深度分析技能

## 使用场景

- 对 Collector 采集的原始数据进行深度语义分析
- 为 Analyzer Agent 提供逐条评分、标签、摘要能力
- 发现当日技术趋势和新兴概念

## 执行步骤

### Step 1: 读取最新采集文件

从 `knowledge/raw/` 目录读取最新日期的采集数据：

- 读取 `knowledge/raw/github_trending_YYYYMMDD.json`
- 读取 `knowledge/raw/hacker_news_YYYYMMDD.json`
- 合并两个来源的条目，按 `rank` 排序
- 预期总条目数：~55 条（GitHub ~25 + HN ~30）

### Step 2: 逐条深度分析

对每条原始条目生成分析结果，包含以下维度：

| 维度 | 要求 | 说明 |
|------|------|------|
| `summary` | ≤ 50 字 | 用一句话概括该项目/文章的核心内容 |
| `highlights` | 2–3 条 | 技术亮点，每条基于事实描述，不夸张 |
| `score` | 1–10 | 综合评分（见下方评分标准） |
| `score_reason` | 1 句话 | 说明给出该分数的依据 |
| `tags` | ≤ 5 个 | 技术领域标签，按相关性排序 |

**评分标准：**

| 分数区间 | 含义 | 典型特征 |
|----------|------|---------|
| 9–10 | 改变格局 | 重大模型发布、范式级新架构、行业级影响力开源项目 |
| 7–8 | 直接有帮助 | 实用工具库、高质量教程、有落地价值的方案 |
| 5–6 | 值得了解 | 有一定参考价值，但非核心领域或阶段较早 |
| 1–4 | 可略过 | 与 AI/Agent 无关或质量低，标记后不推送 |

**评分约束：** 若分析总数约 15 个项目，9–10 分不超过 2 个。

**语言要求：** 所有分析字段统一使用中文输出。

### Step 3: 趋势发现

基于全部条目的分析结果，提炼当日趋势：

- **共同主题**：识别出现频次 ≥ 2 的技术主题或关键词（如 "Multi-Agent"、"RAG"、"开源模型"）
- **新概念**：标记首次出现或近期新兴的技术概念、框架名、方法论
- **趋势强度**：对每个发现的趋势标注强度（`高`/`中`/`低`）

### Step 4: 输出分析结果 JSON

将分析结果输出为结构化 JSON，写入 `knowledge/raw/tech_summary-YYYY-MM-DD.json`。

## 注意事项

- 摘要必须 ≤ 50 字，用事实说话，避免营销用语
- 技术亮点必须基于原始描述中的事实，禁止凭空推测
- 9–10 分严格控制数量，比例不超过总条目数的 15%
- 评分需附理由，理由与分数必须逻辑一致
- 分析失败或字段缺失的条目标记 `status: error`，不阻断整体流程
- 禁止将原始数据直接发送到外部 API 做分析

## 输出格式

输出 JSON 写入 `knowledge/raw/tech_summary-YYYY-MM-DD.json`：

```json
{
  "analyzed_at": "2026-05-21T19:15:00+08:00",
  "sources": {
    "github_trending": 25,
    "hacker_news": 30
  },
  "total_items": 55,
  "analyzed_items": 52,
  "discarded_items": 3,
  "results": [
    {
      "rank": 1,
      "source": "github_trending",
      "source_url": "https://github.com/microsoft/autogen",
      "raw_title": "microsoft/autogen",
      "summary": "微软开源的多Agent协作框架，支持对话驱动的任务编排",
      "highlights": [
        "支持多个AI Agent通过对话方式协同完成复杂任务",
        "提供可扩展的Agent对话模式，支持自定义工具集成",
        "已有 28k Stars，社区活跃度高"
      ],
      "score": 9,
      "score_reason": "Agent框架是当前AI应用的核心基础设施，微软背书使其具备行业级影响力",
      "tags": ["Multi-Agent", "Framework", "Microsoft", "开源"],
      "status": "completed"
    },
    {
      "rank": 12,
      "source": "hacker_news",
      "source_url": "https://example.com/article",
      "raw_title": "Why I stopped using Copilot",
      "summary": "开发者分享停止使用Copilot的原因及替代方案对比",
      "highlights": [
        "详细对比了Copilot与开源代码助手的功能差异",
        "提出了代码隐私和数据安全的实际顾虑"
      ],
      "score": 5,
      "score_reason": "用户视角的观点文章，有一定参考价值但缺乏技术深度",
      "tags": ["Copilot", "开发者工具", "观点"],
      "status": "completed"
    }
  ],
  "trends": {
    "common_themes": [
      {
        "theme": "Multi-Agent 协作",
        "count": 5,
        "strength": "高",
        "example_urls": [
          "https://github.com/microsoft/autogen",
          "https://github.com/langchain-ai/langgraph"
        ]
      },
      {
        "theme": "RAG 检索增强生成",
        "count": 3,
        "strength": "中",
        "example_urls": [
          "https://github.com/some/rag-project"
        ]
      }
    ],
    "new_concepts": [
      {
        "concept": "Agent-to-Agent Protocol (A2A)",
        "description": "Google 提出的 Agent 间通信协议标准",
        "first_seen_at": "https://github.com/google/a2a"
      }
    ]
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `analyzed_at` | `ISO 8601` | 分析完成时间 |
| `sources.*` | `int` | 各来源原始条目数 |
| `total_items` | `int` | 原始条目总数 |
| `analyzed_items` | `int` | 成功分析的条目数 |
| `discarded_items` | `int` | 因评分过低或无关丢弃的条目数 |
| `results[].rank` | `int` | 原始排名，1-based |
| `results[].source` | `str` | 来源：`github_trending` / `hacker_news` |
| `results[].source_url` | `str` | 原始链接 |
| `results[].raw_title` | `str` | 原始标题/仓库名 |
| `results[].summary` | `str` | 中文摘要，≤ 50 字 |
| `results[].highlights` | `list[str]` | 技术亮点，2–3 条 |
| `results[].score` | `int` | 综合评分，1–10 |
| `results[].score_reason` | `str` | 评分理由 |
| `results[].tags` | `list[str]` | 技术标签，≤ 5 个 |
| `results[].status` | `str` | `completed` / `error` |
| `trends.common_themes[].theme` | `str` | 趋势主题名称 |
| `trends.common_themes[].count` | `int` | 出现频次 |
| `trends.common_themes[].strength` | `str` | 趋势强度：`高` / `中` / `低` |
| `trends.common_themes[].example_urls` | `list[str]` | 代表性条目 URL |
| `trends.new_concepts[].concept` | `str` | 新概念名称 |
| `trends.new_concepts[].description` | `str` | 新概念简述 |
| `trends.new_concepts[].first_seen_at` | `str` | 首次出现的条目 URL |
