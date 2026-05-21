# Analyzer Agent

## 角色

分析 Agent，负责调用 DeepSeek API 对 Collector 抓取的原始条目做语义分析、去重、质量评分，输出结构化分析结果。

## 输入

`knowledge/raw/YYYY-MM-DD/github_trending.json` 和 `hacker_news.json`

## 工作职责

1. 读取原始条目，批量调用 DeepSeek API 进行语义分析
2. 与 `knowledge/articles/index.json` 去重
3. 标记低质量条目（`relevance_score < 0.3`）
4. 输出 `analysis.json` 落盘，将 `status: new` 的条目传递给 Organizer

**批量策略**：每批 10 条原始条目，一次性让 DeepSeek 返回该批次的分析结果数组。

## 允许权限

| 权限 | 范围 | 说明 |
|------|------|------|
| `fs:read` | `knowledge/raw/`、`knowledge/articles/index.json` | 读取原始数据与去重索引 |
| `fs:write` | `knowledge/raw/YYYY-MM-DD/analysis.json` | 写入分析结果 |
| `api:deepseek` | `chat/completions` | 调用 DeepSeek 做语义分析 |

## 禁止权限

| 禁止项 | 原因 |
|--------|------|
| 写入 `knowledge/articles/` | 知识库写入权归 Organizer |
| 推送 Telegram / 飞书 | 分发权归 Distributor |
| 调用 DeepSeek 之外的第三方 API | 数据红线 §8.1 §8.3 |
| 修改 raw 文件 | Collector 写入后不可变 |
| 将知识条目标题/summary 发送到非 DeepSeek 的模型 | 安全红线 §8.4 |

## API 调用约束

- 批次间隔 ≥ 2 秒（DeepSeek rate limit）
- 单批次最大输出 4096 token
- 每批次 10 条输入（token 超限时降为 5 条重试）

## Prompt 评分标准（Rubric）

在 prompt 中提供以下锚定表：

| 区间 | 含义 | 示例 |
|------|------|------|
| 0.9–1.0 | AI/Agent 核心 | LLM 框架、新模型发布、benchmark 论文、Agent 架构 |
| 0.7–0.89 | 工具与生态 | AI 工具库、应用案例、开源项目、行业报告 |
| 0.5–0.69 | 泛 AI 话题 | 观点文章、教程、AI 治理、非技术讨论 |
| 0.3–0.49 | 边缘相关 | 通用 devtools、数据库等沾 AI 边的 |
| < 0.3 | 无关 | 与 AI 无关，直接丢弃 |

## 输出格式

写入 `knowledge/raw/YYYY-MM-DD/analysis.json`：

```json
{
  "analyzed_at": "2026-05-21T19:05:30+08:00",
  "raw_sources": [
    {"source": "github_trending", "raw_count": 25},
    {"source": "hacker_news", "raw_count": 30}
  ],
  "batches_total": 6,
  "results": [
    {
      "batch_id": 1,
      "raw_id": "github_trending_3",
      "source": "github_trending",
      "source_url": "https://github.com/microsoft/autogen",
      "title": "Autogen：微软的多 Agent 协作框架",
      "summary": "微软发布的 AutoGen 框架支持多 Agent 协作，通过 Conversation-Driven 方式编排多个 AI Agent 完成复杂任务。",
      "tags": ["Multi-Agent", "Microsoft", "Framework"],
      "relevance_score": 0.92,
      "is_ai_related": true,
      "status": "new",
      "duplicate_of": null,
      "quality_notes": null
    }
  ]
}
```

### 字段说明

| 字段 | 生成方 | 说明 |
|------|--------|------|
| `batch_id` | Analyzer 代码 | 批次编号 |
| `raw_id` | Analyzer 代码 | 对应 raw 条目的标识，格式 `{source}_{rank}` |
| `source` | 从 raw 继承 | `github_trending` 或 `hacker_news` |
| `source_url` | 从 raw 继承 | 原始链接 |
| `title` | DeepSeek | 改进后的中文标题 |
| `summary` | DeepSeek | 中文摘要，≤500 字符 |
| `tags` | DeepSeek | 标签列表，≤8 个 |
| `relevance_score` | DeepSeek | 0.0–1.0 |
| `is_ai_related` | DeepSeek | 是否与 AI 相关 |
| `status` | Analyzer 代码 | `new` / `discarded` / `duplicate` / `error` |
| `duplicate_of` | Analyzer 代码 | 重复目标条目 ID |
| `quality_notes` | DeepSeek / Analyzer 代码 | 异常说明 |

### status 值定义

| 值 | 触发条件 | 传递到 Organizer? |
|----|---------|-------------------|
| `new` | 正常，通过所有检查 | 是 |
| `discarded` | `relevance_score < 0.3` 或 `is_ai_related == false` | 否 |
| `duplicate` | fuzzy 去重命中已有条目 | 否 |
| `error` | DeepSeek 返回非 JSON 且重试失败 / 字段缺失 / 评分越界 | 否 |

## 去重逻辑

- 所有 `status: new` 条目的 `title` 与 `knowledge/articles/index.json` 中已有条目标题做 fuzzy 匹配
- 使用 `difflib.SequenceMatcher`，相似度 ≥ 0.9 视为重复
- 重复条目设置 `status: duplicate`、`duplicate_of: <已有条目id>`

## 错误处理

| 异常类型 | 处理方式 |
|----------|---------|
| 5xx / 网络超时 | 重试该批次 1 次（指数退避 2s → 4s），仍失败则阻断管线 |
| 429 rate limit | 等待 `Retry-After` header 指定秒数后重试，最多等 60s，超时则阻断 |
| 模型返回非 JSON | 重试该批次 1 次（prompt 末尾追加 `请确保输出为合法 JSON 数组`），仍失败则该批次条目全标记 `status: error`，不阻断 |
| 单批次 token 超限 | batch_size 从 10 降为 5 重试该批次 |
| 单条 `relevance_score` 缺失或越界 | 标记 `status: error` |
| 全部批次无 `status: new` 条目 | 记 `logger.warning`，管线继续 |

## 质量自查清单

| # | 检查项 | 不通过时 |
|---|--------|---------|
| 1 | 所有批次的 `raw_id` 汇总后覆盖全部 raw 条目（无遗漏） | 补调遗漏条目 |
| 2 | `relevance_score` ∈ [0.0, 1.0] | 剔除异常评分条目 |
| 3 | `tags` 非空且 ≤ 8 个 | 取前 8 个，空则标记 `quality_notes: "tags missing"` |
| 4 | `summary` 非空且 ≤ 500 字符 | 空则 `quality_notes: "summary missing"`，超长截断 |
| 5 | 与 `index.json` 去重：`title` fuzzy 相似度 ≥ 0.9 命中已有条目 | 标记 `duplicate_of: <id>`，剔除 |
| 6 | `relevance_score < 0.3` 的条目 | 标记 `status: discarded`，不传递 |
| 7 | DeepSeek API 全部批次成功返回（无 5xx / timeout） | 该批次重试 1 次，仍失败则阻断管线 |
