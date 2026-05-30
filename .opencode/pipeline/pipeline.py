#!/usr/bin/env python3
"""四步知识库自动化流水线：采集 → 分析 → 整理 → 保存。

Usage:
    python pipeline.py --sources github,rss --limit 20
    python pipeline.py --sources github --limit 5 --dry-run
    python pipeline.py --sources rss --limit 10 --verbose
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

# ── 确保可 import 同目录模块 ────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from model_client import chat_with_retry, create_provider  # noqa: E402
from models import (  # noqa: E402
    Article,
    ArticleStatus,
    LLMAnalysisResult,
    OutputFile,
    RawDataFile,
    RawItem,
)

# ── 常量 ───────────────────────────────────────────────────────
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_QUERY = "ai+agent+llm+machine+learning"
GITHUB_PER_PAGE = 30
RSS_URL = "https://news.ycombinator.com/rss"
REQUEST_TIMEOUT = 30
LLM_BATCH_SIZE = 10
LLM_MAX_TOKENS = 4096
MAX_LIMIT = 30

KEYWORDS_SHORT = [
    "AI", "LLM", "GPT", "Agent", "大模型", "机器学习", "DeepSeek", "Claude", "OpenAI",
]
KEYWORDS_BROAD = KEYWORDS_SHORT + [
    "copilot", "transformer", "model", "neural", "token", "vector",
    "embedding", "RAG", "coding assistant", "chatbot",
]

ANALYSIS_SYSTEM_PROMPT = """\
你是一个 AI 技术分析师，专精于评估技术新闻和开源项目。你需要分析每条内容的 AI/ML/LLM/Agent 相关性，并生成结构化中文摘要。

评分锚定表：
| 9-10 | AI/Agent 核心突破 — LLM 框架、新模型发布、benchmark 论文、Agent 架构 |
| 7-8  | 工具与生态 — AI 工具库、应用案例、开源项目、行业报告 |
| 5-6  | 泛 AI 话题 — 观点文章、教程、AI 治理、非技术讨论 |
| 3-4  | 边缘相关 — 通用 devtools、数据库等沾 AI 边的内容 |
| 1-2  | 无关 — 与 AI 完全无关 |

请严格返回 JSON 数组，每个元素包含：
{
  "title": "改进后的中文标题（≤200字符）",
  "summary": "中文摘要（≤500字符）",
  "relevance_score": <1-10 整数>,
  "tags": ["标签1", "标签2", ...],  // ≤8个，中文或英文
  "score_reason": "评分理由（≤100字符）"
}

确保输出是合法 JSON 数组。"""


# ── 工具函数 ──────────────────────────────────────────────────

def _article_id(url: str) -> str:
    """生成确定性文章 ID（URL 的 SHA256 前 8 位 hex）。"""
    return hashlib.sha256(url.encode()).hexdigest()[:8]


def _pre_filter(title: str, description: str, keywords: list[str]) -> bool:
    """关键词预筛选：命中任一关键词则返回 True（保留）。"""
    text = f"{title} {description}".lower()
    return any(kw.lower() in text for kw in keywords)


def _strip_html(text: str) -> str:
    """去除 HTML 标签与 XML artifact，保留纯文本。"""
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _file_stem(source: str) -> str:
    """将 source 标识转为文件名前缀：github_search→github, hacker_news_rss→rss。"""
    return "github" if source == "github_search" else "rss"


# ── Step 1: 采集 ──────────────────────────────────────────────

def collect_github(
    limit: int, github_token: str | None = None
) -> tuple[list[RawItem], int, int]:
    """从 GitHub Search API 采集 AI 相关仓库。

    Returns:
        (items, total_api_results, pre_filter_discarded)
    """
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    params = {"q": GITHUB_QUERY, "sort": "stars", "order": "desc", "per_page": min(limit, GITHUB_PER_PAGE)}
    logger.info(f"[GitHub] 调用搜索 API: q={GITHUB_QUERY}, per_page={params['per_page']}")

    resp = httpx.get(GITHUB_SEARCH_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    total_count = data.get("total_count", 0)
    repos = data.get("items", [])
    logger.info(f"[GitHub] API 返回 {len(repos)} 条（总计 {total_count}）")

    items: list[RawItem] = []
    pre_filtered = 0
    for repo in repos[:limit]:
        desc = (repo.get("description") or "").strip()
        full_name = repo.get("full_name", "")
        if not desc:
            pre_filtered += 1
            continue
        if not _pre_filter(full_name, desc, KEYWORDS_SHORT):
            pre_filtered += 1
            continue
        items.append(RawItem(
            source="github_search",
            title=full_name,
            url=repo.get("html_url", ""),
            description=desc,
            extra={
                "full_name": full_name,
                "stargazers_count": repo.get("stargazers_count", 0),
                "language": repo.get("language"),
                "topics": repo.get("topics", []),
            },
        ))

    logger.info(f"[GitHub] 预筛选后保留 {len(items)} 条，丢弃 {pre_filtered} 条")
    return items, total_count, pre_filtered


def collect_rss(limit: int) -> tuple[list[RawItem], int, int]:
    """从 Hacker News RSS 采集 AI 相关内容。

    Returns:
        (items, total_feed_entries, pre_filter_discarded)
    """
    logger.info(f"[RSS] 获取: {RSS_URL}")
    resp = httpx.get(RSS_URL, timeout=REQUEST_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    xml_text = resp.text

    # 预处理：去除 CDATA 包裹
    xml_text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", xml_text, flags=re.DOTALL)

    # 简易正则解析 RSS <item> 块
    item_blocks = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
    logger.info(f"[RSS] 解析到 {len(item_blocks)} 条 RSS entry")

    items: list[RawItem] = []
    pre_filtered = 0
    for block in item_blocks:
        title_match = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
        link_match = re.search(r"<link>(.*?)</link>", block, re.DOTALL)
        desc_match = re.search(r"<description>(.*?)</description>", block, re.DOTALL)
        if not title_match or not link_match:
            continue

        title = _strip_html(title_match.group(1))
        hn_link = _strip_html(link_match.group(1))
        raw_desc = desc_match.group(1) if desc_match else ""
        description = _strip_html(raw_desc)

        # 从 description HTML 中提取原始文章 URL
        orig_url_match = re.search(r'<a\s+href="(https?://[^"]+)"', raw_desc)
        original_url = orig_url_match.group(1) if orig_url_match else hn_link

        if not _pre_filter(title, description, KEYWORDS_BROAD):
            pre_filtered += 1
            continue

        items.append(RawItem(
            source="hacker_news_rss",
            title=title,
            url=original_url,
            description=description,
            extra={"hn_url": hn_link},
        ))
        if len(items) >= limit:
            break

    logger.info(f"[RSS] 预筛选后保留 {len(items)} 条，丢弃 {pre_filtered} 条")
    return items, len(item_blocks), pre_filtered


# ── Step 1.5: 保存原始数据 ─────────────────────────────────────

def save_raw_data(
    source: str, total: int, pre_filtered: int, items: list[RawItem], date_str: str
) -> None:
    """将采集到的原始数据写入 knowledge/raw/{source}-{date}.json。"""
    raw_dir = Path("knowledge/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    raw_file = RawDataFile(
        source=source,
        fetched_at=datetime.now(timezone.utc).astimezone().isoformat(),
        total=total,
        pre_filtered=pre_filtered,
        items=items,
    )
    path = raw_dir / f"{_file_stem(source)}-{date_str}.json"
    path.write_text(raw_file.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"[{_file_stem(source)}] 原始数据已保存: {path}")


# ── Step 2: 分析 ──────────────────────────────────────────────

def _build_batch_prompt(items: list[RawItem]) -> str:
    """构造批量分析的用户提示词。"""
    lines = [f"请分析以下 {len(items)} 条技术内容：\n"]
    for i, item in enumerate(items, 1):
        extra_info = ""
        if item.source == "github_search":
            lang = item.extra.get("language", "")
            stars = item.extra.get("stargazers_count", 0)
            topics = item.extra.get("topics", [])
            extra_info = f" | 语言: {lang} | Stars: {stars} | Topics: {topics}"
        lines.append(f"--- 条目 {i} ---")
        lines.append(f"标题: {item.title}")
        lines.append(f"链接: {item.url}")
        lines.append(f"描述: {item.description}{extra_info}")
        lines.append("")
    return "\n".join(lines)


def _parse_llm_response(raw_text: str, expected_count: int) -> list[dict[str, Any]]:
    """解析 LLM 返回的 JSON 数组，尽力 salvage。"""
    cleaned = raw_text.strip()
    # 去除 markdown 代码块标记
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试用正则提取 JSON 数组
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("LLM 返回无法解析为 JSON 数组，整批标记 error")
                return []
        else:
            logger.warning("LLM 返回中未找到 JSON 数组，整批标记 error")
            return []

    if not isinstance(parsed, list):
        logger.warning("LLM 返回不是数组，整批标记 error")
        return []

    # 补齐缺失条目
    while len(parsed) < expected_count:
        parsed.append({})
    return parsed[:expected_count]


def analyze_batch(raw_items: list[RawItem]) -> tuple[list[LLMAnalysisResult | None], int]:
    """批量调用 LLM 分析条目，返回 (结果列表, error_count)。"""
    provider = create_provider()
    all_results: list[LLMAnalysisResult | None] = []
    error_count = 0

    try:
        for i in range(0, len(raw_items), LLM_BATCH_SIZE):
            batch = raw_items[i : i + LLM_BATCH_SIZE]
            batch_num = i // LLM_BATCH_SIZE + 1
            logger.info(f"[分析] 批次 {batch_num}: 发送 {len(batch)} 条")

            messages = [
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": _build_batch_prompt(batch)},
            ]
            response = chat_with_retry(
                provider, messages, temperature=0.3, max_tokens=LLM_MAX_TOKENS,
            )
            parsed = _parse_llm_response(response.content, len(batch))

            for j, raw_item in enumerate(batch):
                if j >= len(parsed) or not parsed[j]:
                    all_results.append(None)
                    error_count += 1
                    logger.warning(f"[分析] 条目 {raw_item.title} 解析失败，标记 error")
                    continue
                try:
                    result = LLMAnalysisResult(**parsed[j])
                    all_results.append(result)
                except Exception as exc:
                    all_results.append(None)
                    error_count += 1
                    logger.warning(f"[分析] 条目 {raw_item.title} 校验失败: {exc}")
    finally:
        provider.close()

    return all_results, error_count


# ── Step 3: 整理 ──────────────────────────────────────────────

def _load_historical_urls(date_str: str) -> set[str]:
    """从 knowledge/articles/ 加载所有历史文章的 URL 集合。"""
    articles_dir = Path("knowledge/articles")
    if not articles_dir.exists():
        return set()

    urls: set[str] = set()
    for fpath in articles_dir.glob("summary-*.json"):
        # 跳过当天的文件（in-run dedup 单独处理）
        if date_str in fpath.name:
            continue
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            for art in data.get("articles", []):
                if art.get("source_url"):
                    urls.add(art["source_url"])
        except Exception:
            logger.warning(f"读取历史文件失败: {fpath}")
    logger.info(f"[去重] 历史 URL 集合大小: {len(urls)}")
    return urls


def organize(
    raw_items: list[RawItem],
    analysis_results: list[LLMAnalysisResult | None],
    source: str,
    date_str: str,
    min_score: int,
) -> list[Article]:
    """去重 + 评分阈值 + 组装最终 Article 列表。"""
    historical_urls = _load_historical_urls(date_str)
    seen_urls: set[str] = set()

    articles: list[Article] = []
    stats = {"kept": 0, "discarded": 0, "duplicate": 0, "error": 0}

    for raw_item, analysis in zip(raw_items, analysis_results):
        source_url = raw_item.url

        # 错误：LLM 分析失败
        if analysis is None:
            stats["error"] += 1
            articles.append(Article(
                id=_article_id(source_url),
                title=raw_item.title[:200],
                source=source,
                source_url=source_url,
                relevance_score=1,
                status="error",
                stars=raw_item.extra.get("stargazers_count"),
            ))
            continue

        # 历史去重
        if source_url in historical_urls:
            stats["duplicate"] += 1
            articles.append(Article(
                id=_article_id(source_url),
                title=analysis.title[:200],
                source=source,
                source_url=source_url,
                summary=analysis.summary,
                tags=analysis.tags,
                relevance_score=analysis.relevance_score,
                status="duplicate",
                stars=raw_item.extra.get("stargazers_count"),
            ))
            continue

        # In-run 去重
        if source_url in seen_urls:
            stats["duplicate"] += 1
            articles.append(Article(
                id=_article_id(source_url),
                title=analysis.title[:200],
                source=source,
                source_url=source_url,
                summary=analysis.summary,
                tags=analysis.tags,
                relevance_score=analysis.relevance_score,
                status="duplicate",
                stars=raw_item.extra.get("stargazers_count"),
            ))
            continue

        seen_urls.add(source_url)

        # 评分阈值
        if analysis.relevance_score < min_score:
            status: ArticleStatus = "discarded"
            stats["discarded"] += 1
        else:
            status = "kept"
            stats["kept"] += 1

        articles.append(Article(
            id=_article_id(source_url),
            title=analysis.title[:200],
            source=source,
            source_url=source_url,
            summary=analysis.summary,
            tags=analysis.tags,
            relevance_score=analysis.relevance_score,
            status=status,
            stars=raw_item.extra.get("stargazers_count"),
        ))

    logger.info(
        f"[{_file_stem(source)}] 整理完成: "
        f"kept={stats['kept']}, discarded={stats['discarded']}, "
        f"duplicate={stats['duplicate']}, error={stats['error']}"
    )
    return articles


# ── Step 4: 保存 ──────────────────────────────────────────────

def save_articles(
    source: str,
    articles: list[Article],
    date_str: str,
    raw_items: list[RawItem],
) -> None:
    """将最终文章列表写入 knowledge/articles/summary-{source}-{date}.json。"""
    articles_dir = Path("knowledge/articles")
    articles_dir.mkdir(parents=True, exist_ok=True)

    status_counts = {"kept": 0, "discarded": 0, "duplicate": 0, "error": 0}
    for a in articles:
        status_counts[a.status] = status_counts.get(a.status, 0) + 1

    output = OutputFile(
        source=source,
        total_collected=len(raw_items),
        pre_filtered=0,  # pre-filter count tracked separately, not in raw_items
        llm_error=status_counts.get("error", 0),
        kept=status_counts.get("kept", 0),
        discarded=status_counts.get("discarded", 0),
        duplicate=status_counts.get("duplicate", 0),
        articles=articles,
    )

    path = articles_dir / f"summary-{_file_stem(source)}-{date_str}.json"
    path.write_text(output.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"[{_file_stem(source)}] 文章已保存: {path}")


# ── Dry-run 输出 ──────────────────────────────────────────────

def print_collected(all_items: dict[str, list[RawItem]]) -> None:
    """Dry-run 模式：打印采集结果并退出。"""
    print("\n=== DRY RUN: Collected Items ===\n")
    for source, items in all_items.items():
        print(f"[{source}] {len(items)} items would be sent to LLM:")
        for item in items:
            print(f"  • {item.title}")
            print(f"    {item.url}")
            print(f"    {item.description[:120]}...\n")
    print("=== Dry-run complete (no LLM calls, no files written) ===")


# ── CLI ───────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="四步知识库自动化流水线：采集 → 分析 → 整理 → 保存",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python pipeline.py --sources github,rss --limit 20\n"
               "  python pipeline.py --sources github --limit 5 --dry-run\n"
               "  python pipeline.py --sources rss --limit 10 --verbose",
    )
    parser.add_argument(
        "--sources", required=True,
        help="采集源（逗号分隔）：github, rss",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="每源采集上限（最大 30，默认 20）",
    )
    parser.add_argument(
        "--min-score", type=int, default=4,
        help="最低保留评分（1-10，默认 4）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="干跑模式：仅采集预筛选，不调 LLM，不写文件",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="详细日志：实时打印每条采集结果",
    )
    return parser.parse_args()


def setup_logging(verbose: bool, date_str: str) -> None:
    """配置 loguru：stderr + 文件日志。"""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="<level>{level: <8}</level> | {message}")

    log_dir = Path("knowledge/raw")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / f"pipeline-{date_str}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="1 day",
        retention="30 days",
    )


def main() -> None:
    """入口函数。"""
    args = parse_args()
    today = datetime.now().strftime("%Y-%m-%d")
    setup_logging(args.verbose, today)

    sources = [s.strip() for s in args.sources.split(",")]
    limit = min(args.limit, MAX_LIMIT)

    github_token = os.getenv("GITHUB_TOKEN")

    # ── Step 1: 采集 ──
    all_raw: dict[str, tuple[list[RawItem], int, int]] = {}
    for src in sources:
        logger.info(f"{'='*50}")
        logger.info(f"开始采集: {src}")
        try:
            if src == "github":
                items, total, pre = collect_github(limit, github_token)
            elif src == "rss":
                items, total, pre = collect_rss(limit)
            else:
                logger.warning(f"未知数据源: {src}，已跳过")
                continue
            all_raw[src] = (items, total, pre)
            save_raw_data(
                "github_search" if src == "github" else "hacker_news_rss",
                total, pre, items, today,
            )
            if args.verbose:
                for item in items:
                    logger.info(f"  [COLLECTED] {item.title} — {item.url}")
        except Exception as exc:
            logger.error(f"采集 {src} 失败: {exc}")
            # Graceful degradation: continue with other sources

    if not all_raw:
        logger.error("所有数据源采集失败，管线终止")
        sys.exit(1)

    if args.dry_run:
        print_collected({k: v[0] for k, v in all_raw.items()})
        return

    # ── Step 2-3: 分析 + 整理（逐源处理） ──
    all_articles: dict[str, list[Article]] = {}
    for src, (raw_items, _total, _pre) in all_raw.items():
        source_id = "github_search" if src == "github" else "hacker_news_rss"
        logger.info(f"{'='*50}")
        logger.info(f"开始分析: {src} ({len(raw_items)} 条)")

        if not raw_items:
            logger.info(f"[{src}] 无待分析条目，跳过")
            all_articles[source_id] = []
            continue

        analysis_results, error_count = analyze_batch(raw_items)
        articles = organize(raw_items, analysis_results, source_id, today, args.min_score)
        all_articles[source_id] = articles

    # ── Step 4: 保存 ──
    for src, articles in all_articles.items():
        raw_items = all_raw.get("github" if src == "github_search" else "rss", ([], 0, 0))[0]
        save_articles(src, articles, today, raw_items)

    logger.info("=" * 50)
    logger.info("流水线完成。")


if __name__ == "__main__":
    main()
