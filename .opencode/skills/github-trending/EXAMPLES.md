# Examples: GitHub Trending

## 示例 1：每日默认抓取

抓取近 7 天创建、star > 1000 的热门仓库，按 star 降序排列。

```
GET https://api.github.com/search/repositories?q=stars:>1000+created:>=2026-05-17&sort=stars&order=desc&per_page=25
```

输出：最多 25 条仓库，经垃圾过滤后写入 `knowledge/raw/github_trending_20260524.json`。

---

## 示例 2：按近期推送趋势（周趋势）

改用 `pushed` 日期，关注近期活跃的不一定是新仓库。

```
GET https://api.github.com/search/repositories?q=stars:>1000+pushed:>=2026-05-17&sort=stars&order=desc&per_page=25
```

---

## 示例 3：过滤输出（含 filter_reason）

输入 25 条，3 条被明确丢弃（破解工具/星标农场），22 条保留（其中 5 条命中 AI 白名单，17 条标记 `no_ai_keyword`）。

```json
{
  "source": "github_trending",
  "fetched_at": "2026-05-24T19:00:00+08:00",
  "count": 22,
  "filtered_out": 3,
  "items": [
    {
      "rank": 1,
      "owner": "FoundZiGu",
      "repo": "GuJumpgate",
      "description": "",
      "url": "https://github.com/FoundZiGu/GuJumpgate",
      "language": "JavaScript",
      "stars_today": null,
      "stars_total": 2053,
      "scraped_at": "2026-05-24T19:00:00+08:00",
      "filter_reason": "no_ai_keyword"
    },
    {
      "rank": 5,
      "owner": "google",
      "repo": "gemma.cpp",
      "description": "Lightweight C++ inference engine for Gemma models",
      "url": "https://github.com/google/gemma.cpp",
      "language": "C++",
      "stars_today": null,
      "stars_total": 8200,
      "scraped_at": "2026-05-24T19:00:00+08:00",
      "filter_reason": null
    }
  ]
}
```

> `filter_reason: null` 表示通过白名单或无需标记；`no_ai_keyword` 表示不命中 AI 关键词但也不满足丢弃条件。

---

## 示例 4：边界场景

### 4.1 空结果 / API 超时

GitHub API 返回空 items 或超时 → 重试 1 次（60s 间隔），仍失败则：

```json
{
  "source": "github_trending",
  "fetched_at": "2026-05-24T19:00:05+08:00",
  "count": 0,
  "filtered_out": 0,
  "items": []
}
```

记录 `logger.warning("github_api_returned_no_items")`，不阻断管线。

### 4.2 过滤后条目不足（降级）

过滤后仅剩 2 条（< 3 条阈值）→ 触发降级，保留全部原始条目：

```json
{
  "count": 25,
  "filtered_out": 0,
}
```

记录 `logger.warning("low_quality_ratio: fallback to raw items")`。

### 4.3 字段缺失

单条 `description` 为空 / `language` 为 null → 对应字段设为 `""` 或 `null`，记录 `logger.warning`，不丢弃该条目。
