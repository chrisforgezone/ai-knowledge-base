"""Pydantic data models for the knowledge pipeline.

Defines schemas for raw collected data, LLM analysis results,
and final knowledge articles output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Raw Collection ──────────────────────────────────────────────

class RawItem(BaseModel):
    """Normalized raw item from any source before analysis."""

    source: Literal["github_search", "hacker_news_rss"] = Field(
        description="Data source identifier"
    )
    title: str = Field(description="Raw title from source")
    url: str = Field(description="Source URL (original article or repo)")
    description: str = Field(default="", description="Snippet or description")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific metadata (stars, topics, hn_url, etc.)",
    )


class RawDataFile(BaseModel):
    """Structure written to knowledge/raw/{source}-{date}.json."""

    source: Literal["github_search", "hacker_news_rss"]
    fetched_at: str = Field(description="ISO 8601 timestamp")
    total: int = Field(description="Total items collected (before pre-filter)")
    pre_filtered: int = Field(description="Items removed by keyword pre-filter")
    items: list[RawItem] = Field(description="Remaining items for analysis")


# ── LLM Analysis Result ────────────────────────────────────────

class LLMAnalysisResult(BaseModel):
    """Single item analysis returned by the LLM in a batch."""

    title: str = Field(description="Improved Chinese title", max_length=200)
    summary: str = Field(description="Chinese summary", max_length=500)
    relevance_score: int = Field(description="Relevance score 1-10", ge=1, le=10)
    tags: list[str] = Field(description="Relevant tags", max_length=8)
    score_reason: str = Field(
        default="", description="Brief explanation for the score", max_length=100
    )


# ── Final Article ──────────────────────────────────────────────

ArticleStatus = Literal["kept", "discarded", "duplicate", "error"]


class Article(BaseModel):
    """Final knowledge article saved to knowledge/articles/."""

    id: str = Field(description="Deterministic ID (SHA256 of URL, 8 hex chars)")
    title: str = Field(max_length=200)
    source: Literal["github_search", "hacker_news_rss"]
    source_url: str = Field(description="Canonical URL for dedup")
    summary: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=8)
    relevance_score: int = Field(ge=1, le=10)
    status: ArticleStatus = "kept"
    stars: int | None = Field(default=None, description="GitHub stars (null for RSS)")
    created_at: str = Field(
        default_factory=lambda: datetime.now().astimezone().isoformat(),
        description="ISO 8601 creation timestamp",
    )


class OutputFile(BaseModel):
    """Wrapper structure for summary-{source}-{date}.json."""

    generated_at: str = Field(
        default_factory=lambda: datetime.now().astimezone().isoformat()
    )
    source: str
    total_collected: int = 0
    pre_filtered: int = 0
    llm_error: int = 0
    kept: int = 0
    discarded: int = 0
    duplicate: int = 0
    articles: list[Article] = Field(default_factory=list)
