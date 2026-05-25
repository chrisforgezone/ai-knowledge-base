#!/usr/bin/env python3
"""知识条目 5 维度质量评分工具。

Usage:
    python hooks/check_quality.py article.json
    python hooks/check_quality.py knowledge/raw/tech_summary-*.json

维度及权重：
    摘要质量 (25)  技术深度 (25)  格式规范 (20)  标签精度 (15)  空洞词检测 (15)

等级：
    A >= 80  B >= 60  C < 60

Exit code:
    0 — 全部 A/B
    1 — 存在 C 级
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------

ZH_BUZZWORDS = [
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "对齐", "拉通", "沉淀", "强大的",
]

EN_BUZZWORDS = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "disruptive", "paradigm-shifting", "state-of-the-art", "unparalleled",
    "unprecedented", "best-in-class", "next-generation", "world-class",
]

TECH_KEYWORDS = [
    "AI", "LLM", "Agent", "GPT", "模型", "开源", "API", "RAG",
    "推理", "训练", "部署", "benchmark", "framework", "Transformer",
    "neural", "deep learning", "embedding", "fine-tune", "inference",
    "prompt", "copilot", "multimodal", "架构", "参数", "预训练",
]

STANDARD_TAGS = {
    "AI", "LLM", "Agent", "GPT", "Claude", "Transformer", "RAG",
    "embedding", "fine-tune", "inference", "prompt", "copilot",
    "open-source", "framework", "benchmark", "security", "multimodal",
    "vision", "speech", "NLP", "CV", "ML", "DL",
    "deployment", "optimization", "AI-Agent", "AI-Coding", "Small-LLM",
    "AI文本", "AI创作", "小模型", "新架构", "预训练", "代码生成",
    "编码助手", "开源模型", "模型训练", "模型推理", "自动化",
    "检测绕过", "漏洞发现", "多人协作", "自托管", "学术写作",
    "教程", "学习资源", "中文", "安全", "供应链", "画布", "工具",
    "Go", "Python", "TypeScript", "JavaScript", "Perplexity",
    "Codex", "HRM", "论文", "Framework", "Microsoft", "开源",
}

DIMENSION_NAMES = [
    ("摘要质量", 25),
    ("技术深度", 25),
    ("格式规范", 20),
    ("标签精度", 15),
    ("空洞词检测", 15),
]

BAR_WIDTH = 30


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    name: str
    score: int
    max_score: int
    details: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    filepath: Path
    dimensions: list[DimensionScore] = field(default_factory=list)
    total_score: int = 0
    grade: str = ""




# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _is_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _is_valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _is_uuid_v4(value: str) -> bool:
    try:
        u = uuid.UUID(value)
        return u.version == 4
    except (ValueError, AttributeError):
        return False


def _find_buzzwords(text: str, buzzwords: list[str]) -> list[str]:
    found: list[str] = []
    lower = text.lower()
    for word in buzzwords:
        if word.lower() in lower:
            found.append(word)
    return found


def _count_tech_keywords(text: str) -> int:
    lower = text.lower()
    return sum(1 for kw in TECH_KEYWORDS if kw.lower() in lower)


# ---------------------------------------------------------------------------
# 5 维度评分
# ---------------------------------------------------------------------------

def score_summary(data: dict) -> DimensionScore:
    summary = data.get("summary", "") or ""
    details: list[str] = []
    length = len(summary)

    if length >= 50:
        base = 20
    elif length >= 20:
        base = 12
    else:
        base = max(0, int((length / 50) * 20))

    tech_count = _count_tech_keywords(summary)
    bonus = min(5, tech_count)
    score = min(25, base + bonus)

    details.append(f"长度: {length} 字符  (基础 {base} 分)")
    if tech_count > 0:
        details.append(f"技术关键词: +{bonus} 分  ({tech_count} 处命中)")
    elif length >= 50:
        pass
    else:
        details.append(f"建议: 摘要宜 ≥50 字符，当前 {length}")

    return DimensionScore("摘要质量", score, 25, details)


def score_depth(data: dict) -> DimensionScore:
    score_field = data.get("score")
    relevance = data.get("relevance_score")

    if isinstance(score_field, (int, float)) and 1 <= score_field <= 10:
        raw = float(score_field)
        score = int(raw / 10 * 25)
        details = [f"score = {score_field}  →  {score}/25"]
    elif isinstance(relevance, (int, float)) and 0 <= relevance <= 1:
        raw = float(relevance)
        score = int(raw * 25)
        details = [f"relevance_score = {relevance:.2f}  →  {score}/25"]
    else:
        score = 0
        details = ["缺少 score 或 relevance_score 字段"]

    return DimensionScore("技术深度", score, 25, details)


def score_format(data: dict) -> DimensionScore:
    details: list[str] = []
    checks = 0

    if _is_uuid_v4(data.get("id", "")):
        checks += 1
        details.append("id: ✅ UUID v4")
    elif "id" in data:
        details.append(f"id: ❌ 非 UUID v4 ({data['id']})")
    else:
        details.append("id: — 不存在")

    title = data.get("title") or data.get("raw_title") or ""
    if title:
        checks += 1
        details.append(f"title: ✅ ({title[:30]}...)")
    else:
        details.append("title: ❌ 缺失")

    source_url = data.get("source_url", "")
    if _is_valid_url(source_url):
        checks += 1
        details.append("source_url: ✅")
    else:
        details.append(f"source_url: ❌ ({source_url[:40]})")

    status = data.get("status", "")
    if status in ("new", "reviewed", "published", "archived", "completed", "discarded", "error"):
        checks += 1
        details.append(f"status: ✅ ({status})")
    elif status:
        details.append(f"status: ❌ 无效值 ({status})")
    else:
        details.append("status: ❌ 缺失")

    # ts_fields = [
    #     data.get("published_at"),
    #     data.get("created_at"),
    #     data.get("updated_at"),
    #     data.get("analyzed_at"),
    #     data.get("scraped_at"),
    #     data.get("fetched_at"),
    # ]
    # if any(isinstance(ts, str) and _is_iso8601(ts) for ts in ts_fields):
    #     checks += 1
    #     details.append("时间戳: ✅ ISO 8601")
    # else:
    #     details.append("时间戳: ❌ 缺失或格式错误")

    score = checks * 4
    return DimensionScore("格式规范", score, 20, details)


def score_tags(data: dict) -> DimensionScore:
    tags: list[str] = data.get("tags") or []
    tag_count = len(tags)
    details: list[str] = []

    if tag_count == 0:
        details.append("无标签")
        return DimensionScore("标签精度", 0, 15, details)

    if tag_count <= 3:
        base = 15
    elif tag_count <= 5:
        base = 10
    else:
        base = 5

    matched = sum(1 for t in tags if t in STANDARD_TAGS)
    bonus = min(3, matched)
    score = min(15, base + bonus)

    details.append(f"{tag_count} 个标签  (基础 {base} 分)")
    if matched > 0:
        details.append(f"标准标签命中: {matched}/{tag_count}  (+{bonus} 分)")
    else:
        details.append("无标准标签命中")
    details.append(f"标签: {', '.join(tags)}")

    return DimensionScore("标签精度", score, 15, details)


def score_buzzwords(data: dict) -> DimensionScore:
    text_fields = [
        data.get("summary", ""),
        data.get("description", ""),
        data.get("title", ""),
        data.get("raw_title", ""),
    ]
    combined = " ".join(str(f) for f in text_fields if f)
    details: list[str] = []
    penalty = 0

    zh_hits = _find_buzzwords(combined, ZH_BUZZWORDS)
    for word in zh_hits:
        penalty += 5
        details.append(f"中文空洞词: 「{word}」  -5")

    en_hits = _find_buzzwords(combined, EN_BUZZWORDS)
    for word in en_hits:
        penalty += 3
        details.append(f"英文空洞词: 「{word}」  -3")

    score = max(0, 15 - penalty)

    if not details:
        details.append("未检测到空洞词")

    return DimensionScore("空洞词检测", score, 15, details)


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def _render_bar(score: int, max_score: int, width: int = BAR_WIDTH) -> str:
    filled = int(score / max_score * width)
    empty = width - filled
    return "█" * filled + "░" * empty


def _compute_grade(total: int) -> str:
    if total >= 80:
        return "A"
    if total >= 60:
        return "B"
    return "C"


def analyze_file(filepath: Path) -> QualityReport:
    data = json.loads(filepath.read_text(encoding="utf-8"))
    results = data.get("results") if isinstance(data, dict) else []

    if results and isinstance(results, list):
        entries = [e for e in results if isinstance(e, dict)]
    else:
        entries = [data] if isinstance(data, dict) else []

    if not entries:
        report = QualityReport(filepath=filepath)
        report.dimensions = [
            DimensionScore(name, 0, max_s, ["文件中无可评分条目"])
            for name, max_s in DIMENSION_NAMES
        ]
        report.grade = "C"
        return report

    accumulated: dict[str, int] = {name: 0 for name, _ in DIMENSION_NAMES}

    for entry in entries:
        dims = [
            score_summary(entry),
            score_depth(entry),
            score_format(entry),
            score_tags(entry),
            score_buzzwords(entry),
        ]
        for d in dims:
            accumulated[d.name] += d.score

    entry_count = len(entries)
    ref_dims = [
        score_summary(entries[0]),
        score_depth(entries[0]),
        score_format(entries[0]),
        score_tags(entries[0]),
        score_buzzwords(entries[0]),
    ]
    ref_by_name = {d.name: d for d in ref_dims}

    dimensions: list[DimensionScore] = []
    for name, max_s in DIMENSION_NAMES:
        avg = int(round(accumulated[name] / entry_count))
        ref = ref_by_name[name]
        prefix = [f"({entry_count} 条平均)"] if entry_count > 1 else []
        dimensions.append(DimensionScore(name, avg, max_s, prefix + ref.details))

    total_score = sum(d.score for d in dimensions)
    report = QualityReport(
        filepath=filepath,
        dimensions=dimensions,
        total_score=total_score,
        grade=_compute_grade(total_score),
    )
    return report


def print_report(report: QualityReport) -> None:
    filename = report.filepath.name
    print(f"\n{'─' * 60}")
    print(f"  📄 {filename}")
    for dim in report.dimensions:
        bar = _render_bar(dim.score, dim.max_score)
        print(f"  {dim.name:<6}  {bar}  {dim.score:>2}/{dim.max_score}")
        for line in dim.details:
            print(f"           {line}")
    print(f"  {'─' * 50}")
    print(f"  总分: {report.total_score}/100  等级: {report.grade}")


def collect_files(paths: list[str]) -> list[Path]:
    result: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            result.append(p.resolve())
        elif p.is_dir():
            result.extend(
                sorted(f for f in p.rglob("*.json") if not f.name == "index.json")
            )
        else:
            result.extend(
                sorted(p.parent.glob(p.name)) if p.parent.is_dir() else []
            )
    return sorted(set(result))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="知识条目 5 维度质量评分",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="JSON 文件路径或 glob 模式（如 '*.json'）",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        default=False,
        help="仅输出汇总统计，不逐文件打印",
    )
    args = parser.parse_args()

    filepaths = collect_files(args.files)
    if not filepaths:
        print("未找到匹配的 JSON 文件", file=sys.stderr)
        return 2

    reports: list[QualityReport] = []
    errors: list[tuple[str, str]] = []

    file_count = len(filepaths)
    for idx, fp in enumerate(filepaths, start=1):
        try:
            report = analyze_file(fp)
            reports.append(report)
        except json.JSONDecodeError as exc:
            errors.append((fp.name, f"非合法 JSON — {exc}"))
        except Exception as exc:
            errors.append((fp.name, f"解析异常 — {exc}"))

        pct = int(idx / file_count * 40)
        bar = "█" * pct + "░" * (40 - pct)
        print(f"\r  [{bar}] {idx}/{file_count}", end="", flush=True)

    print()

    if not args.summary:
        for report in reports:
            print_report(report)

    for fname, err in errors:
        print(f"\n  ❌ {fname}: {err}")

    grade_counts = {"A": 0, "B": 0, "C": 0}
    total_scores: list[int] = []
    for r in reports:
        grade_counts[r.grade] += 1
        total_scores.append(r.total_score)

    avg = sum(total_scores) / len(total_scores) if total_scores else 0
    print(f"\n{'═' * 60}")
    print(f"  总计: {len(reports)} 文件  |  A: {grade_counts['A']}  B: {grade_counts['B']}  C: {grade_counts['C']}  |  平均: {avg:.1f}")
    if errors:
        print(f"  解析失败: {len(errors)} 文件")
    print(f"{'═' * 60}")

    if grade_counts["C"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
