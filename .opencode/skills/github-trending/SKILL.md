---
name: github-trending
description: 抓取 GitHub Trending 热门仓库并进行垃圾过滤和质量分类。Use when 需要采集 GitHub trending 数据、搜索热门 AI/LLM 开源仓库、或执行每日技术情报采集管线。
---

# GitHub Trending

## Quick start

```bash
# 每日趋势（默认，按 star 排序，近 7 天创建）
GET https://api.github.com/search/repositories?q=stars:>1000+created:>=2026-05-17&sort=stars&order=desc&per_page=25
```

可选调整 `created` → `pushed` 实现 weekly/monthly 视角。请求头：`Accept: application/vnd.github+json`、`User-Agent: ai-knowledge-base/1.0`。

## Workflow

1. **搜索热门仓库** — 调用 GitHub Search API 获取 25 条候选仓库
2. **垃圾过滤** — 三层过滤管线（基础校验 → 垃圾初筛 → 白名单保留），详见 [REFERENCE.md](REFERENCE.md)
3. **提取元信息** — 对保留条目提取 rank / owner / repo / description / url / language / stars_today / stars_total / scraped_at / filter_reason
4. **输出 JSON** — 写入 `knowledge/raw/YYYY-MM-DD/github_trending.json`，格式与 Collector Agent 一致

### 过滤管线概览

```
原始条目 → [基础校验] → [明确丢弃] → [白名单保留] → [标记 filter_reason]
                ↓              ↓              ↓                ↓
         剔除无效/重复    剔除垃圾仓库    无条件保留      暂留，交 Analyzer 决策
```

- **明确丢弃**：破解/盗版关键词、SEO 堆砌、纯 emoji 推广、无语言无描述、星标农场（详见 REFERENCE.md）
- **白名单保留**：命中 `ai` `llm` `agent` `gpt` `transformer` `rag` 等 18 个关键词即保留
- **降级策略**：过滤后条目 < 3 条时，保留全部原始条目

## Constraints

- 请求间隔 ≥ 60 秒
- 禁止伪造 User-Agent（合规红线 §8.2）
- 抓取失败重试 1 次（间隔 60s），仍失败返回空 items
- 单条字段缺失设为 `null`，记录 warning

## Reference

- 详细过滤规则与完整输出 Schema：[REFERENCE.md](REFERENCE.md)
- 典型使用示例：[EXAMPLES.md](EXAMPLES.md)
