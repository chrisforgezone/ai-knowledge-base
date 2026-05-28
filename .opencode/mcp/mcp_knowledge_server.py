#!/usr/bin/env python3
"""MCP Server for AI Knowledge Base.

Provides tools to search and analyze the local knowledge base
stored in knowledge/raw/tech_summary-*.json files.

Protocol: JSON-RPC 2.0 over stdio.
No third-party dependencies — standard library only.

Usage:
    python mcp_knowledge_server.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logging (writes to stderr so it never interferes with stdio JSON-RPC)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_knowledge")

# ---------------------------------------------------------------------------
# Path resolution – always relative to *this file's* location in the repo
# ---------------------------------------------------------------------------
RAW_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge" / "raw"


# ===================================================================
# Knowledge-base loader
# ===================================================================

def load_articles() -> list[dict[str, Any]]:
    """Load all completed articles from every tech_summary-*.json in raw/.

    Returns:
        List of article dicts where status == "completed", sorted by
        score descending.
    """
    articles: list[dict[str, Any]] = []

    if not RAW_DIR.is_dir():
        logger.warning("Raw directory not found: %s", RAW_DIR)
        return articles

    for filepath in sorted(RAW_DIR.glob("tech_summary-*.json")):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            completed = [
                item
                for item in data.get("results", [])
                if item.get("status") == "completed"
            ]
            articles.extend(completed)
            logger.info(
                "Loaded %d completed articles from %s",
                len(completed),
                filepath.name,
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load %s: %s", filepath, exc)

    articles.sort(key=lambda a: a.get("score", 0) or 0, reverse=True)
    logger.info("Total loaded articles: %d", len(articles))
    return articles


# ===================================================================
# Tool implementations
# ===================================================================

def search_articles(
    articles: list[dict[str, Any]],
    keyword: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Search articles by keyword in title and summary.

    Args:
        articles: The full pre-loaded article list.
        keyword: Case-insensitive search term.
        limit: Maximum results to return.

    Returns:
        Dict with total_matches, returned count, keyword, and results.
    """
    if not keyword.strip():
        return {"total_matches": 0, "returned": 0, "keyword": "", "results": []}

    kw = keyword.lower().strip()
    matches: list[dict[str, Any]] = []

    for item in articles:
        title = (item.get("raw_title") or "").lower()
        summary = (item.get("summary") or "").lower()
        if kw in title or kw in summary:
            matches.append({
                "title": item.get("raw_title"),
                "source": item.get("source"),
                "url": item.get("source_url"),
                "summary": item.get("summary"),
                "score": item.get("score"),
                "tags": item.get("tags", []),
            })

    total = len(matches)
    matches = matches[:limit]

    return {
        "total_matches": total,
        "returned": len(matches),
        "keyword": keyword,
        "results": matches,
    }


def knowledge_stats(articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics of the knowledge base.

    Args:
        articles: The full pre-loaded article list.

    Returns:
        Dict with total count, source distribution, top tags, and
        score statistics.
    """
    source_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    scores: list[int] = []

    for item in articles:
        source = item.get("source", "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1

        for tag in item.get("tags", []):
            if tag not in ("无关", "低质量"):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        score = item.get("score")
        if isinstance(score, (int, float)):
            scores.append(score)

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total_articles": len(articles),
        "sources": source_counts,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "max_score": max(scores) if scores else 0,
        "min_score": min(scores) if scores else 0,
    }


# ===================================================================
# JSON-RPC dispatcher
# ===================================================================

def dispatch(
    method: str,
    params: dict[str, Any] | None,
    articles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Dispatch a JSON-RPC method to the appropriate handler.

    Args:
        method: The JSON-RPC method name (e.g. "initialize", "tools/list",
                "tools/call").
        params: Method parameters, may be None.
        articles: Pre-loaded article list.

    Returns:
        The result payload to be embedded under "result" in the JSON-RPC
        response.

    Raises:
        ValueError: If the method is unknown.
    """
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "ai-knowledge-base",
                "version": "1.0.0",
            },
            "capabilities": {
                "tools": {},
            },
        }

    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "search_articles",
                    "description": (
                        "在AI知识库中按关键词搜索文章。"
                        "在文章标题(raw_title)和摘要(summary)中进行不区分大小写的匹配，"
                        "返回按AI相关性评分(score)降序排列的结果。"
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": (
                                    "搜索关键词。匹配文章的标题和摘要字段。"
                                ),
                            },
                            "limit": {
                                "type": "integer",
                                "description": "返回的最大结果数，默认为 5。",
                                "default": 5,
                            },
                        },
                        "required": ["keyword"],
                    },
                },
                {
                    "name": "knowledge_stats",
                    "description": (
                        "获取知识库的整体统计信息，包括文章总数、来源分布、"
                        "热门标签 Top 10、以及评分统计（均值/最高/最低）。"
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                    },
                },
            ],
        }

    if method == "tools/call":
        if not params:
            raise ValueError("Missing params for tools/call")

        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "search_articles":
            keyword = str(arguments.get("keyword", ""))
            limit = int(arguments.get("limit", 5))
            result = search_articles(articles, keyword, limit)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2),
                    }
                ],
            }

        if tool_name == "knowledge_stats":
            result = knowledge_stats(articles)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2),
                    }
                ],
            }

        return {
            "content": [
                {"type": "text", "text": f"Unknown tool: {tool_name}"}
            ],
            "isError": True,
        }

    # -- Notifications (no id) – silently ignore ---------------------------
    if method.startswith("notifications/"):
        return {}

    raise ValueError(f"Unknown method: {method}")


# ===================================================================
# Main loop
# ===================================================================

def main() -> None:
    """Run the MCP server: load knowledge base, then process JSON-RPC
    requests line-by-line over stdin/stdout."""
    logger.info("ai-knowledge-base MCP server starting ...")
    articles = load_articles()
    logger.info("Server ready, waiting for JSON-RPC requests on stdin.")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON on stdin: %s", exc)
            continue

        rpc_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params")

        try:
            result = dispatch(method, params, articles)
        except Exception as exc:
            logger.exception("Error dispatching method %r", method)
            error_response = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": -32000,
                    "message": str(exc),
                },
            }
            sys.stdout.write(
                json.dumps(error_response, ensure_ascii=False) + "\n"
            )
            sys.stdout.flush()
            continue

        # Notifications have no id → no response
        if rpc_id is None:
            continue

        response: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": result,
        }
        sys.stdout.write(
            json.dumps(response, ensure_ascii=False) + "\n"
        )
        sys.stdout.flush()


if __name__ == "__main__":
    main()
