# Reference: GitHub Trending

## API 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `q` | `stars:>1000 created:>={date}` | 按 stars 过滤，创建日期在 7 天内 |
| `sort` | `stars` | 按 star 数降序 |
| `order` | `desc` | 从高到低 |
| `per_page` | `25` | 每页数量（预期 ~25 条） |

备选查询（按推送趋势）：`q=stars:>1000+pushed:>{date}&sort=stars&order=desc&per_page=25`

### 请求头

```
Accept: application/vnd.github+json
User-Agent: ai-knowledge-base/1.0
```

可选 `Authorization: Bearer <token>` 提升速率限制（无 Token 也可访问公开仓库搜索）。

---

## 垃圾过滤规则

### 基础校验

| 规则 | 动作 |
|------|------|
| owner 或 repo 为空 | 剔除 |
| url 重复（同次抓取） | 保留第一条 |
| url 格式非 `https://github.com/{owner}/{repo}` | 剔除 |

### 明确丢弃

| 规则 | 检测方式 | 示例 |
|------|---------|------|
| 破解/盗版关键词 | description 或 repo 名含 `crack` `bypass` `unlock` `keygen` `activator` `license key` | "Full feature activation...crack bypass" |
| 免费下载推广 | description 含 `free download` 且长度 > 100 字符 | "Free Download PC Windows 11..." |
| 纯 emoji 推广 | description 以 🚀⭐🎮 等 emoji 开头，无实质技术描述 | "🚀 Ultimate Free Tool 2026" |
| 无语言无描述 | `language` 为 null 且 `description` 为空 | 无法判断用途 |
| 星标农场 | stargazers_count ≤ 450 且 description 全大写比例 > 50% | 多个仓库相同 star 数 |

### AI/LLM/Agent 白名单（无条件保留）

以下关键词任一命中即保留：

`ai` `llm` `agent` `gpt` `claude` `transformer` `neural` `deep-learning` `machine-learning` `model` `copilot` `rag` `embedding` `fine-tune` `inference` `open-source` `prompt` `reasoning` `mcp`

匹配范围：description、repo 名、topics。

### 无法界定

不满足丢弃条件、也不命中白名单 → 保留，追加 `filter_reason: "no_ai_keyword"`，交 Analyzer 层决策。

### 降级策略

- 过滤后条目 < 3 条 → `logger.warning("low_quality_ratio")`，保留全部原始条目
- 过滤后条目 ≥ 3 条 → 使用过滤后列表，记录 `filtered_out` 数量

---

## 输出 Schema

写入 `knowledge/raw/YYYY-MM-DD/github_trending.json`：

```json
{
  "source": "github_trending",
  "fetched_at": "2026-05-24T19:00:05+08:00",
  "count": 22,
  "filtered_out": 3,
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
      "scraped_at": "2026-05-24T19:00:05+08:00",
      "filter_reason": null
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | `str` | 固定值 `"github_trending"` |
| `fetched_at` | ISO 8601 | 抓取开始时间 |
| `count` | `int` | 过滤后保留的条目数 |
| `filtered_out` | `int` | 被垃圾过滤器剔除的条目数 |
| `items[].rank` | `int` | 排名（1-based） |
| `items[].owner` | `str` | 仓库所有者 |
| `items[].repo` | `str` | 仓库名称 |
| `items[].description` | `str` | 仓库描述（可为空字符串） |
| `items[].url` | `str` | `https://github.com/{owner}/{repo}` |
| `items[].language` | `str \| null` | 编程语言 |
| `items[].stars_today` | `int \| null` | 当日新增 star 数（GitHub Search API 不直接提供，可为 null） |
| `items[].stars_total` | `int` | 总 star 数 |
| `items[].scraped_at` | ISO 8601 | 条目解析时间 |
| `items[].filter_reason` | `str \| null` | 标记原因（`no_ai_keyword` / `spam_crack` / `spam_star_farm` 等），未被标记则为 null |

---

## 合规红线

- 请求间隔 ≥ 60 秒，尊重 GitHub rate limit
- 禁止伪造 User-Agent 为浏览器 UA（合规红线 §8.2）
- 不在 18:00–20:00（UTC+8）时段高频率抓取
- 抓取失败时返回空 items 并记录 error，不阻断管线
