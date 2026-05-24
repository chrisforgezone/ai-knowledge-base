---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# GitHub Trending 技能

## 使用场景

- 采集 GitHub Trending 当日热门仓库原始数据
- 为 Collector Agent 提供 GitHub 数据源
- 手动查看 GitHub 上当前热门开源项目

## 执行步骤

### Step 1: 搜索热门仓库

通过 GitHub Search API 搜索热门仓库：

**API 端点：**

```
GET https://api.github.com/search/repositories
```

**请求参数：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `q` | `stars:>1000 created:>={date}` | 按 stars 过滤，创建日期在 7 天内 |
| `sort` | `stars` | 按 star 数降序 |
| `order` | `desc` | 从高到低 |
| `per_page` | `25` | 每页数量（预期 ~25 条） |

**备选查询（按 trending）：**

```
GET https://api.github.com/search/repositories?q=stars:>1000+pushed:>{date}&sort=stars&order=desc&per_page=25
```

- 目标：获取近期热门 trending repositories
- 时间范围：daily（默认），可选调整 `created`/`pushed` 日期范围实现 weekly / monthly
- 请求头：
  - `Accept: application/vnd.github+json`
  - `User-Agent: ai-knowledge-base/1.0`
- 超时：30 秒，失败后间隔 60 秒重试 1 次
- 无需 Token 即可访问（公开仓库搜索），若有 Token 可设 `Authorization: Bearer <token>` 提升速率限制

### Step 2: 垃圾过滤

对获取到的仓库列表进行两轮过滤：

#### 2.1 基础校验

- 去除 `owner` 或 `repo` 为空的无效条目
- 去除重复 `url`（同次抓取中只保留第一条）
- 校验 `url` 格式为 `https://github.com/{owner}/{repo}`

#### 2.2 垃圾仓库初筛

基于以下规则标记并剔除明确垃圾仓库，不确定的条目保留并加 `filter_reason` 标记，交由 Analyzer 层二次判断。

**明确丢弃（直接剔除）：**

| 规则 | 检测方式 | 示例 |
|------|---------|------|
| 破解/盗版关键词 | description 或 repo 名包含 `crack` `bypass` `unlock` `keygen` `activator` `license key` | "Full feature activation...crack bypass" |
| 免费下载推广 | description 包含 `free download` 且描述长度 > 100 字符（纯 SEO 堆砌） | "Free Download PC Windows 11..." |
| 纯 emoji 推广 | description 以 🚀⭐🎮 等 emoji 开头，且无实质技术描述 | "🚀 Ultimate Free Tool 2026 – Download Now" |
| 无语言无描述 | `language` 为 null 且 `description` 为空 | 完全无法判断用途 |
| 星标农场 | `stargazers_count` ≤ 450 且 description 为纯营销语（全大写比例 > 50%） | 多个仓库相同 star 数的推广号 |

**AI/LLM/Agent 白名单（无条件保留）：**

description、repo 名或 topics 命中以下任一关键词即保留：
`ai` `llm` `agent` `gpt` `claude` `transformer` `neural` `deep-learning` `machine-learning` `model` `copilot` `rag` `embedding` `fine-tune` `inference` `open-source` `prompt`

**无法界定（暂留，标记 `filter_reason`）：**

不满足明确丢弃条件、也不命中白名单的条目保留，追加 `filter_reason` 字段说明原因（如 `no_ai_keyword`），供 Analyzer 层决策。

#### 2.3 过滤后检查

- 过滤后条目 < 3 条：记录 `logger.warning("low_quality_ratio")`，保留全部原始条目（降级策略）
- 过滤后条目 ≥ 3 条：使用过滤后列表，在输出 JSON 中记录 `filtered_out` 数量

### Step 3: 提取元信息

对每条仓库提取以下字段：

| 字段 | 说明 |
|------|------|
| `rank` | 排名，从 1 开始递增 |
| `owner` | 仓库所有者 |
| `repo` | 仓库名称 |
| `description` | 仓库描述，可为空字符串 |
| `url` | 完整仓库地址 |
| `language` | 编程语言，可为 null |
| `stars_today` | 当日新增 star 数 |
| `stars_total` | 总 star 数 |
| `scraped_at` | 该条目的抓取时间戳 |

### Step 4: 输出为 JSON

将结构化数据输出为 JSON，格式与 Collector Agent 的 `github_trending.json` 匹配。

## 注意事项

- 请求间隔 ≥ 60 秒，尊重 GitHub rate limit
- 禁止伪造 User-Agent 为浏览器 UA（合规红线）
- 不在 18:00–20:00（UTC+8）时段高频率抓取
- 抓取失败时返回空 items 并记录 error，不阻断管线
- 单条字段缺失时对应字段设为 `null`，记录 warning
- **垃圾过滤原则**：明确垃圾直接剔除，不确定的保留并加 `filter_reason`，不误杀潜在优质项目
- 过滤后条目 < 3 条时降级为全量保留，避免过度过滤导致空管线

## 输出格式

输出 JSON 写入 `knowledge/raw/YYYY-MM-DD/github_trending.json`，格式如下：

```json
{
  "source": "github_trending",
  "fetched_at": "2026-05-21T19:00:05+08:00",
  "count": 25,
  "filtered_out": 15,
  "items": [
    {
      "rank": 1,
      "owner": "microsoft",
      "repo": "autogen",
      "description": "A programming framework for agentic AI",
      "url": "https://github.com/microsoft/autogen",
      "language": "Python",
      "stars_today": 342,
      "stars_total": 28000,
      "scraped_at": "2026-05-21T19:00:05+08:00",
      "filter_reason": null
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | `str` | 固定值 `"github_trending"` |
| `fetched_at` | `ISO 8601` | 抓取开始时间 |
| `count` | `int` | 过滤后保留的条目数 |
| `filtered_out` | `int` | 被垃圾过滤器剔除的条目数 |
| `items[].rank` | `int` | 排名（1-based） |
| `items[].owner` | `str` | 仓库所有者 |
| `items[].repo` | `str` | 仓库名称 |
| `items[].description` | `str` | 仓库描述 |
| `items[].url` | `str` | `https://github.com/{owner}/{repo}` |
| `items[].language` | `str \| null` | 编程语言 |
| `items[].stars_today` | `int \| null` | 当日新增 star 数 |
| `items[].stars_total` | `int` | 总 star 数 |
| `items[].scraped_at` | `ISO 8601` | 条目解析时间 |
| `items[].filter_reason` | `str \| null` | 标记原因（`no_ai_keyword` 等），未被标记则为 null |
