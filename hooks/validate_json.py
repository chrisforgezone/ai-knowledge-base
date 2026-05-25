#!/usr/bin/env python3
"""校验知识管线输出 JSON 文件是否符合设计规范。

Usage:
    python hooks/validate_json.py knowledge/raw/github-trending-2026-05-24.json
    python hooks/validate_json.py --dir knowledge/raw/
    python hooks/validate_json.py knowledge/raw/*.json

支持的文件：
    github-trending-yyyy-MM-dd.json
    tech_summary-yyyy-MM-dd.json

Exit code:
    0 — 全部通过
    1 — 存在校验失败的文件
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# 字段定义：(字段名, 类型, 必要性, 值校验函数, 错误描述)
# ---------------------------------------------------------------------------

Rule = tuple[str, type | tuple[type, ...], bool, Optional[Callable[[Any], bool]], str]

GITHUB_TRENDING_SCHEMA: list[Rule] = [
    ("source", str, True, lambda v: v == "github_trending", "必须为 'github_trending'"),
    ("fetched_at", str, True, None, ""),
    ("count", int, True, lambda v: v >= 0, "必须 >= 0"),
    ("filtered_out", int, True, lambda v: v >= 0, "必须 >= 0"),
    ("items", list, True, lambda v: len(v) > 0, "不能为空"),
]

GITHUB_TRENDING_ITEM_SCHEMA: list[Rule] = [
    ("rank", int, True, lambda v: v >= 1, "必须 >= 1"),
    ("owner", str, True, lambda v: len(v) > 0, "不能为空"),
    ("repo", str, True, lambda v: len(v) > 0, "不能为空"),
    ("description", str, True, None, ""),
    ("url", str, True, lambda v: v.startswith("https://github.com/"), "必须以 https://github.com/ 开头"),
    ("language", (str, type(None)), True, None, ""),
    ("stars_today", (int, type(None)), True, lambda v: v is None or v >= 0, "为 null 或 >= 0"),
    ("stars_total", int, True, lambda v: v >= 0, "必须 >= 0"),
    ("scraped_at", str, True, None, ""),
    ("filter_reason", (str, type(None)), True, None, ""),
]

TECH_SUMMARY_SCHEMA: list[Rule] = [
    ("analyzed_at", str, True, None, ""),
    ("sources", dict, True, None, ""),
    ("total_items", int, True, lambda v: v >= 0, "必须 >= 0"),
    ("analyzed_items", int, True, lambda v: v >= 0, "必须 >= 0"),
    ("discarded_items", int, True, lambda v: v >= 0, "必须 >= 0"),
    ("results", list, True, None, ""),
    ("trends", dict, True, None, ""),
]

TECH_SUMMARY_RESULT_SCHEMA: list[Rule] = [
    ("rank", int, True, lambda v: v >= 1, "必须 >= 1"),
    ("source", str, True, lambda v: v in ("github_trending", "hacker_news"), "必须为 github_trending 或 hacker_news"),
    ("source_url", str, True, lambda v: len(v) > 0, "不能为空"),
    ("raw_title", str, True, lambda v: len(v) > 0, "不能为空"),
    ("summary", str, True, lambda v: 0 < len(v) <= 50, "长度 1-50 字符"),
    ("highlights", list, True, None, ""),
    ("score", int, True, lambda v: 1 <= v <= 10, "必须在 1-10 区间"),
    ("score_reason", str, True, lambda v: len(v) > 0, "不能为空"),
    ("tags", list, True, lambda v: len(v) <= 5, "最多 5 个标签"),
    ("status", str, True, lambda v: v in ("completed", "discarded", "error"), "必须为 completed/discarded/error"),
]

TREND_THEME_SCHEMA: list[Rule] = [
    ("theme", str, True, lambda v: len(v) > 0, "不能为空"),
    ("count", int, True, lambda v: v >= 1, "必须 >= 1"),
    ("strength", str, True, lambda v: v in ("高", "中", "低"), "必须为 高/中/低"),
    ("example_urls", list, True, lambda v: len(v) > 0, "不能为空"),
]

NEW_CONCEPT_SCHEMA: list[Rule] = [
    ("concept", str, True, lambda v: len(v) > 0, "不能为空"),
    ("description", str, True, lambda v: len(v) > 0, "不能为空"),
    ("first_seen_at", str, True, lambda v: len(v) > 0, "不能为空"),
]


# ---------------------------------------------------------------------------
# 文件名匹配
# ---------------------------------------------------------------------------

FILE_PATTERNS = {
    "github-trending": re.compile(r"^github-trending-\d{4}-\d{2}-\d{2}\.json$"),
    "tech_summary": re.compile(r"^tech_summary-\d{4}-\d{2}-\d{2}\.json$"),
}


def detect_file_type(filename: str) -> Optional[str]:
    for ftype, pattern in FILE_PATTERNS.items():
        if pattern.match(filename):
            return ftype
    return None


def detect_type_from_content(data: dict) -> Optional[str]:
    """根据 JSON 内容推断文件类型（文件名不匹配时的回退策略）。"""
    if "source" in data and "items" in data:
        return "github-trending"
    if "analyzed_at" in data and "results" in data and "trends" in data:
        return "tech_summary"
    return None


# ---------------------------------------------------------------------------
# 校验工具函数
# ---------------------------------------------------------------------------

def _is_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def validate_field(
    data: dict,
    field_name: str,
    expected_type: type | tuple[type, ...],
    required: bool,
    check: Optional[Callable[[Any], bool]],
    error_desc: str,
    path: str,
) -> list[str]:
    """校验单个字段，返回错误列表。"""
    errors: list[str] = []
    full_path = f"{path}.{field_name}" if path else field_name

    if field_name not in data:
        if required:
            errors.append(f"{full_path}: 缺少必填字段")
        return errors

    value = data[field_name]

    if not isinstance(value, expected_type):
        type_name = getattr(expected_type, "__name__", str(expected_type))
        errors.append(f"{full_path}: 类型应为 {type_name}，实际为 {type(value).__name__}")
        return errors

    if check is not None and error_desc:
        try:
            if not check(value):
                errors.append(f"{full_path}: {error_desc}，实际值: {value!r}")
        except Exception:
            errors.append(f"{full_path}: 校验异常，实际值: {value!r}")

    return errors


def validate_schema(data: dict, schema: list[Rule], path: str = "") -> list[str]:
    errors: list[str] = []
    for field_name, expected_type, required, check, error_desc in schema:
        errors.extend(
            validate_field(data, field_name, expected_type, required, check, error_desc, path)
        )
    return errors


# ---------------------------------------------------------------------------
# 文件级校验
# ---------------------------------------------------------------------------

def validate_github_trending(filepath: Path, data: Optional[dict] = None) -> list[str]:
    errors: list[str] = []
    if data is None:
        data = json.loads(filepath.read_text(encoding="utf-8"))

    errors.extend(validate_schema(data, GITHUB_TRENDING_SCHEMA))

    if "count" in data and isinstance(data["count"], int):
        items = data.get("items")
        if isinstance(items, list) and data["count"] != len(items):
            errors.append(f"count ({data['count']}) != items 实际长度 ({len(items)})")

    if "fetched_at" in data and isinstance(data["fetched_at"], str) and not _is_iso8601(data["fetched_at"]):
        errors.append(f"fetched_at: 非 ISO 8601 格式: {data['fetched_at']!r}")

    items = data.get("items")
    if isinstance(items, list):
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"items[{i}]: 不是字典类型")
                continue
            prefix = f"items[{i}]"
            errors.extend(validate_schema(item, GITHUB_TRENDING_ITEM_SCHEMA, prefix))

            if "scraped_at" in item and isinstance(item["scraped_at"], str) and not _is_iso8601(item["scraped_at"]):
                errors.append(f"{prefix}.scraped_at: 非 ISO 8601 格式: {item['scraped_at']!r}")

            rank = item.get("rank")
            if isinstance(rank, int) and rank != i + 1:
                errors.append(f"{prefix}.rank: 期望 {i + 1}，实际 {rank}")

    return errors


def validate_tech_summary(filepath: Path, data: Optional[dict] = None) -> list[str]:
    errors: list[str] = []
    if data is None:
        data = json.loads(filepath.read_text(encoding="utf-8"))

    errors.extend(validate_schema(data, TECH_SUMMARY_SCHEMA))

    if "analyzed_at" in data and isinstance(data["analyzed_at"], str) and not _is_iso8601(data["analyzed_at"]):
        errors.append(f"analyzed_at: 非 ISO 8601 格式: {data['analyzed_at']!r}")

    sources = data.get("sources")
    if isinstance(sources, dict) and "github_trending" not in sources:
        errors.append("sources: 缺少 github_trending 字段")

    total = data.get("total_items")
    results = data.get("results")
    if isinstance(total, int) and isinstance(results, list) and total != len(results):
        errors.append(f"total_items ({total}) != results 实际长度 ({len(results)})")

    discarded_count = data.get("discarded_items")
    if isinstance(results, list) and isinstance(discarded_count, int):
        actual_discarded = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "discarded")
        if discarded_count != actual_discarded:
            errors.append(f"discarded_items ({discarded_count}) != 实际 discarded 数量 ({actual_discarded})")

    if isinstance(results, list):
        for i, item in enumerate(results):
            if not isinstance(item, dict):
                errors.append(f"results[{i}]: 不是字典类型")
                continue
            prefix = f"results[{i}]"
            errors.extend(validate_schema(item, TECH_SUMMARY_RESULT_SCHEMA, prefix))

    trends = data.get("trends")
    if isinstance(trends, dict):
        for i, theme in enumerate(trends.get("common_themes", [])):
            if not isinstance(theme, dict):
                errors.append(f"trends.common_themes[{i}]: 不是字典类型")
                continue
            errors.extend(validate_schema(theme, TREND_THEME_SCHEMA, f"trends.common_themes[{i}]"))

        for i, concept in enumerate(trends.get("new_concepts", [])):
            if not isinstance(concept, dict):
                errors.append(f"trends.new_concepts[{i}]: 不是字典类型")
                continue
            errors.extend(validate_schema(concept, NEW_CONCEPT_SCHEMA, f"trends.new_concepts[{i}]"))

    return errors


VALIDATORS = {
    "github-trending": validate_github_trending,
    "tech_summary": validate_tech_summary,
}


def validate_file(filepath: Path) -> tuple[Optional[str], list[str]]:
    ftype = detect_file_type(filepath.name)

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ftype, [f"{filepath}: 非合法 JSON — {exc}"]
    except Exception as exc:
        return ftype, [f"{filepath}: 读取失败 — {exc}"]

    if ftype is None and isinstance(data, dict):
        ftype = detect_type_from_content(data)

    if ftype is None:
        return None, []

    try:
        validator = VALIDATORS[ftype]
        errors = validator(filepath, data)
    except json.JSONDecodeError as exc:
        return ftype, [f"{filepath}: 非合法 JSON — {exc}"]
    except Exception as exc:
        return ftype, [f"{filepath}: 校验异常 — {exc}"]

    return ftype, errors


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def collect_files(paths: list[str], root_dir: Path) -> list[Path]:
    result: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            result.append(p.resolve())
        elif p.is_dir():
            result.extend(sorted(p.rglob("*.json")))
        else:
            expanded = sorted(p.parent.glob(p.name)) if p.parent.is_dir() else []
            result.extend(expanded)
    return sorted(set(result)) if result else sorted(root_dir.rglob("*.json"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="校验知识管线输出 JSON 文件是否符合设计规范",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="JSON 文件路径或目录（留空则使用 --dir 默认目录）",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("knowledge/raw"),
        help="目标目录，仅在未指定 files 时生效（默认: knowledge/raw）",
    )
    args = parser.parse_args()

    json_files = collect_files(args.files, args.dir)
    if not json_files:
        print(f"未找到 JSON 文件: {args.files or args.dir}", file=sys.stderr)
        return 2

    total = 0
    failed = 0
    errors_by_file: dict[str, list[str]] = {}
    skipped = 0

    for filepath in json_files:
        ftype, errors = validate_file(filepath)
        if ftype is None:
            skipped += 1
            print(f"  ⚠ {filepath.name}: 文件名不匹配预期模式，已跳过")
            continue

        total += 1
        if errors:
            failed += 1
            errors_by_file[str(filepath)] = errors

    # --- 输出 ---
    label = "目录" if not args.files else "文件"
    print(f"校验{label}: {args.files or args.dir}")
    print(f"匹配文件: {total}  跳过: {skipped}  通过: {total - failed}  失败: {failed}")
    print("-" * 60)

    if errors_by_file:
        for filepath, errs in errors_by_file.items():
            print(f"\n[FAIL] {filepath}")
            for err in errs:
                print(f"  - {err}")
        print(f"\n共 {failed} 个文件校验未通过")
        return 1

    print("全部文件校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
