#!/usr/bin/env python3
"""daily_context.json から人間確認用の短いジェンマ課長ブリーフを作る。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
CONTEXT_PATH = AI_DIR / "daily_context.json"
PROFILE_PATH = AI_DIR / "gemma_profile.yml"
TEXT_OUTPUT_PATH = AI_DIR / "gemma_brief.txt"
JSON_OUTPUT_PATH = AI_DIR / "gemma_brief.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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


def count_list(context: dict[str, Any], key: str) -> int:
    value = context.get(key, [])
    return len(value) if isinstance(value, list) else 0


def count_object(context: dict[str, Any], key: str) -> int:
    value = context.get(key, {})
    return 1 if isinstance(value, dict) and bool(value) else 0


def count_x_summary(context: dict[str, Any]) -> int:
    value = context.get("x_summary", {})
    if not isinstance(value, dict) or not value:
        return 0
    if value.get("status") == "not_started":
        return 0
    summary = value.get("summary")
    if isinstance(summary, list) and not summary:
        return 0
    return 1


def build_counts(context: dict[str, Any]) -> dict[str, int]:
    return {
        "events": count_list(context, "events"),
        "road_events": count_list(context, "road_events"),
        "orbis": count_list(context, "orbis"),
        "incidents": count_list(context, "incidents"),
        "weather": count_object(context, "weather"),
        "railway": count_object(context, "railway"),
        "x_summary": count_x_summary(context),
        "dragons": count_object(context, "dragons"),
    }


def build_highlights(context: dict[str, Any], counts: dict[str, int]) -> list[str]:
    highlights: list[str] = []

    incidents = context.get("incidents", [])
    if counts["incidents"] and isinstance(incidents, list):
        has_shinkansen = any("shinkansen" in json.dumps(item, ensure_ascii=False).lower() for item in incidents)
        if has_shinkansen:
            highlights.append("新幹線インシデントログがあります。")
        else:
            highlights.append("インシデントログがあります。")

    if counts["weather"] and counts["railway"]:
        highlights.append("天気/鉄道情報がdaily_contextに入りました。")
    elif counts["weather"]:
        highlights.append("天気情報がdaily_contextに入りました。")
    elif counts["railway"]:
        highlights.append("鉄道情報がdaily_contextに入りました。")

    if counts["dragons"]:
        highlights.append("ドラゴンズ関連ログがあります。")

    if context.get("notes"):
        highlights.append("daily_context生成時のnotesがあります。")

    return highlights[:4]


def build_comment(profile: dict[str, Any], counts: dict[str, int]) -> str:
    catchphrases = profile.get("catchphrases", [])
    if counts["incidents"] and isinstance(catchphrases, list) and "運転再開≠復旧" in catchphrases:
        return "運転再開≠復旧です😇"
    if counts["weather"] or counts["railway"]:
        return "未確認情報はcandidate扱いで見ます。"
    return ""


def build_text(profile: dict[str, Any], counts: dict[str, int], highlights: list[str], comment: str) -> str:
    name = profile.get("name") if isinstance(profile.get("name"), str) else "ジェンマ課長"
    lines = [
        f"🤖 {name}ブリーフ",
        "",
        f"・イベント件数: {counts['events']}件",
        f"・道路情報件数: {counts['road_events']}件",
        f"・オービス秘伝のタレ: {counts['orbis']}件",
        f"・インシデントログ: {counts['incidents']}件",
        f"・天気情報: {'あり' if counts['weather'] else 'なし'}",
        f"・鉄道情報: {'あり' if counts['railway'] else 'なし'}",
        "",
        "注目:",
    ]

    if highlights:
        lines.extend(f"・{highlight}" for highlight in highlights)
    else:
        lines.append("・大きな変化は未確認です。")

    if comment:
        lines.extend(["", "ひとこと:", comment])

    return "\n".join(lines) + "\n"


def main() -> int:
    context = load_json(CONTEXT_PATH)
    profile = load_profile(PROFILE_PATH)
    counts = build_counts(context)
    highlights = build_highlights(context, counts)
    comment = build_comment(profile, counts)

    brief = {
        "generated_at": now_iso(),
        "counts": counts,
        "highlights": highlights,
        "comment": comment,
    }
    text = build_text(profile, counts, highlights, comment)

    AI_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_OUTPUT_PATH.write_text(text, encoding="utf-8")
    with JSON_OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
    print(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
    for key, value in counts.items():
        print(f"{key}: {value}")
    print(f"highlights: {len(highlights)}")
    print(f"comment: {1 if comment else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
