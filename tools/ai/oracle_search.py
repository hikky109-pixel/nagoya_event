#!/usr/bin/env python3
"""oracle_memory.jsonから質問に近い過去事例だけを検索する。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ORACLE_MEMORY_PATH = ROOT / "data" / "ai" / "oracle_memory.json"
MAX_RESULTS = 5
SHINKANSEN_PRIORITY_WORDS = (
    "東海道新幹線",
    "名古屋駅",
    "名駅",
    "桜通口",
    "太閤通口",
    "椿町",
    "JR東海",
    "遅延",
    "運休",
    "終電",
    "列車ホテル",
)
SHINKANSEN_PLUS_THREE_WORDS = ("名古屋", "名駅", "東海道", "JR東海")
SHINKANSEN_PLUS_TWO_WORDS = ("終電", "列車ホテル", "桜通口", "太閤通口", "椿町")

KNOWN_TERMS = (
    "御園座",
    "熱田まつり",
    "新幹線",
    "東海道新幹線",
    "北陸新幹線",
    "名古屋駅",
    "名駅",
    "桜通口",
    "太閤通口",
    "椿町",
    "JR東海",
    "遅延",
    "運休",
    "終電",
    "列車ホテル",
    "オービス",
    "CSV",
    "Sheets",
    "同期",
    "OCR",
    "PDF",
    "TSV",
    "交通規制",
    "通行止",
    "事故",
    "画像",
    "イベント",
    "ドラゴンズ",
    "IGアリーナ",
    "道路",
    "公共交通",
    "運転再開",
    "復旧",
)


def load_oracle_memory() -> dict[str, Any]:
    if not ORACLE_MEMORY_PATH.exists():
        return {}
    try:
        with ORACLE_MEMORY_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    stripped = query.strip()
    if stripped:
        terms.append(stripped)
    terms.extend(term for term in KNOWN_TERMS if term in query)
    terms.extend(re.findall(r"[A-Za-z0-9_]+|[一-龥ぁ-んァ-ヶー]{2,}", query))
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term and term not in seen:
            unique.append(term)
            seen.add(term)
    return unique


def normalize_query(query: str) -> str:
    return query.strip().replace("　", " ")


def iter_items(memory: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, item_type in (
        ("success_cases", "success"),
        ("failure_cases", "failure"),
        ("cautions", "caution"),
    ):
        for item in memory.get(key, []):
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized["type"] = item_type
            if "title" not in normalized:
                normalized["title"] = title_from_item(normalized, item_type)
            if "summary" not in normalized and "note" in normalized:
                normalized["summary"] = str(normalized.get("note", ""))
            if "lesson" not in normalized and "note" in normalized:
                normalized["lesson"] = str(normalized.get("note", ""))
            items.append(normalized)
    return items


def title_from_item(item: dict[str, Any], item_type: str) -> str:
    text = json.dumps(item, ensure_ascii=False)
    if "熱田まつり" in text:
        return "熱田まつりPDF案件"
    if "御園座" in text:
        return "御園座OCR案件"
    if "新幹線" in text:
        return "新幹線インシデント"
    if "オービス" in text:
        return "オービス道路情報"
    if "CSV" in text or "Sheets" in text:
        return "CSV/Sheets同期案件"
    topic = str(item.get("topic", "") or item_type)
    return f"{topic}記憶"


def score_item(item: dict[str, Any], terms: list[str]) -> int:
    title = str(item.get("title", ""))
    summary = str(item.get("summary", ""))
    lesson = str(item.get("lesson", ""))
    score = 0
    for term in terms:
        if term in title:
            score += 3
        if term in summary:
            score += 2
        if term in lesson:
            score += 1
    return score


def shinkansen_adjustment(item: dict[str, Any], query: str) -> tuple[int, list[str]]:
    if "新幹線" not in query:
        return 0, []
    if "北陸" in query:
        return 0, []

    title = str(item.get("title", ""))
    summary = str(item.get("summary", ""))
    lesson = str(item.get("lesson", ""))
    text = f"{title}\n{summary}\n{lesson}"
    summary_lesson = f"{summary}\n{lesson}"
    adjustment = 0
    detail: list[str] = []

    if "北陸" not in query and "北陸新幹線" in summary_lesson:
        adjustment -= 5
        detail.append("北陸新幹線:-5")

    for word in SHINKANSEN_PLUS_THREE_WORDS:
        if word in text:
            adjustment += 3
            detail.append(f"{word}:+3")
            break

    for word in SHINKANSEN_PLUS_TWO_WORDS:
        if word in text:
            adjustment += 2
            detail.append(f"{word}:+2")
            break

    return adjustment, detail


def confidence_for_score(score: int) -> str:
    if score >= 5:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def search_oracle(query: str, limit: int = MAX_RESULTS) -> list[dict[str, str]]:
    memory = load_oracle_memory()
    if not memory:
        return []
    raw_query = query
    normalized_query = normalize_query(query)
    terms = query_terms(normalized_query)
    if not terms:
        return []

    scored: list[tuple[int, dict[str, Any], list[str]]] = []
    for item in iter_items(memory):
        base_score = score_item(item, terms)
        adjustment, adjustment_detail = shinkansen_adjustment(item, normalized_query)
        score = base_score + adjustment
        if score > 0:
            detail = [f"base:{base_score}"] + adjustment_detail + [f"total:{score}"]
            scored.append((score, item, detail))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    score_detail = [
        f"{item.get('title', '')}:{score}({','.join(detail)})"
        for score, item, detail in scored[:limit]
    ]
    oracle_titles = ",".join(str(item.get("title", "")) for score, item, detail in scored[:limit])
    print(f"raw_query={raw_query}", file=sys.stderr)
    print(f"normalized_query={normalized_query}", file=sys.stderr)
    print(f"score_detail={score_detail}", file=sys.stderr)
    print(f"oracle_titles={oracle_titles}", file=sys.stderr)

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for score, item, detail in scored:
        result = {
            "type": str(item.get("type", "")),
            "title": str(item.get("title", "")),
            "summary": str(item.get("summary", "")),
            "lesson": str(item.get("lesson", "")),
            "confidence": confidence_for_score(score),
        }
        dedupe_key = json.dumps(
            {key: result[key] for key in ("title", "summary", "lesson")},
            ensure_ascii=False,
            sort_keys=True,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        results.append(result)
        if len(results) >= limit:
            break
    return results


def main() -> int:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        query = sys.stdin.read().strip()
    results = search_oracle(query)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
