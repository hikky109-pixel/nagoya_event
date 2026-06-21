#!/usr/bin/env python3
"""gemma_brief.json からDiscord投稿候補の日報を作る。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
BRIEF_PATH = AI_DIR / "gemma_brief.json"
PROFILE_PATH = AI_DIR / "gemma_profile.yml"
OUTPUT_PATH = AI_DIR / "gemma_report.txt"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path.relative_to(ROOT)} is not a JSON object.")
    return data


def load_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return load_simple_yaml(path)

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.relative_to(ROOT)} is not a YAML mapping.")
    return data


def load_simple_yaml(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_list: str | None = None

    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- "):
                if current_list is None:
                    raise ValueError(f"List item without a key in {path.relative_to(ROOT)}.")
                data[current_list].append(stripped[2:])
                continue
            if ":" not in stripped:
                raise ValueError(f"Unsupported YAML line in {path.relative_to(ROOT)}: {stripped}")
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                data[key] = value
                current_list = None
            else:
                data[key] = []
                current_list = key
    return data


def count(counts: dict[str, Any], key: str) -> int:
    value = counts.get(key, 0)
    return value if isinstance(value, int) else 0


def compact_highlights(highlights: list[Any], counts: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    for item in highlights:
        if not isinstance(item, str):
            continue
        if "ドラゴンズ" in item and count(counts, "dragons") == 0:
            continue
        if ("X" in item or "x_summary" in item) and count(counts, "x_summary") == 0:
            continue
        if item == "天気/鉄道情報がdaily_contextに入りました。":
            lines.append("天気情報、鉄道情報があります。")
        else:
            lines.append(item)
        if len(lines) >= 3:
            break

    return lines


def safe_comment(comment: Any, profile: dict[str, Any]) -> str:
    if not isinstance(comment, str):
        return ""
    comment = comment.strip()
    if not comment:
        return ""
    if "スギケツバット" in comment:
        return ""

    catchphrases = profile.get("catchphrases", [])
    if isinstance(catchphrases, list) and "スギケツバット" in catchphrases:
        return comment
    return comment


def render_report(brief: dict[str, Any], profile: dict[str, Any]) -> str:
    counts = brief.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}

    raw_highlights = brief.get("highlights", [])
    highlights = compact_highlights(raw_highlights if isinstance(raw_highlights, list) else [], counts)
    comment = safe_comment(brief.get("comment"), profile)

    lines = [
        "🤖 ジェンマ課長日報",
        "",
        f"・イベント {count(counts, 'events')}件",
        f"・道路情報 {count(counts, 'road_events')}件",
        f"・オービス {count(counts, 'orbis')}件",
    ]

    if highlights:
        lines.extend(["", "注目"])
        lines.extend(f"・{highlight}" for highlight in highlights[:3])

    if comment:
        lines.extend(["", "ひとこと", comment])

    return "\n".join(lines) + "\n"


def main() -> int:
    brief = load_json(BRIEF_PATH)
    profile = load_profile(PROFILE_PATH)
    report = render_report(brief, profile)

    AI_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report, encoding="utf-8")
    print(f"wrote: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
