#!/usr/bin/env python3
"""日次日誌を使って「昨日何かあった？」に答える。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DAILY_SUMMARY_DIR = ROOT / "data" / "ai" / "daily_summary"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"


def today() -> date:
    return datetime.now(timezone.utc).astimezone().date()


def dates_for_query(query: str) -> list[date]:
    current = today()
    if "一昨日" in query:
        return [current - timedelta(days=2)]
    if "昨日" in query:
        return [current - timedelta(days=1)]
    if "今日" in query or "本日" in query:
        return [current]
    if "今週" in query:
        start = current - timedelta(days=current.weekday())
        return [start + timedelta(days=offset) for offset in range((current - start).days + 1)]

    explicit = parse_explicit_date(query)
    if explicit is not None:
        return [explicit]
    return [current]


def has_time_reference(query: str) -> bool:
    return any(word in query for word in ("今日", "本日", "昨日", "一昨日", "今週")) or parse_explicit_date(query) is not None


def parse_explicit_date(query: str) -> date | None:
    for token in query.replace("/", "-").split():
        try:
            return date.fromisoformat(token)
        except ValueError:
            continue
    return None


def load_summaries(target_dates: list[date]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for target in target_dates:
        date_key = target.isoformat()
        path = DAILY_SUMMARY_DIR / f"{date_key}.txt"
        if not path.exists():
            continue
        summaries.append(
            {
                "date": date_key,
                "summary": path.read_text(encoding="utf-8").strip(),
            }
        )
    return summaries


def load_recent_summaries(limit: int = 7) -> list[dict[str, str]]:
    paths = sorted(DAILY_SUMMARY_DIR.glob("*.txt"), reverse=True)[:limit]
    summaries: list[dict[str, str]] = []
    for path in paths:
        summaries.append(
            {
                "date": path.stem,
                "summary": path.read_text(encoding="utf-8").strip(),
            }
        )
    return summaries


def build_prompt(query: str, summaries: list[dict[str, str]]) -> str:
    source_json = json.dumps(summaries, ensure_ascii=False, indent=2)
    return f"""あなたはジェンマ課長です。

ユーザーの質問に、日次日誌だけを根拠に3〜7行で返答してください。

ルール:
- 箇条書き中心
- 日誌にないことは断定しない
- 不明なことは未確認と書く
- candidate を利用する
- ツッコミは最大1回
- スギケツバットは毎回出さない
- 本番データを勝手に確定しない
- 運転再開≠復旧

質問:
{query}

日次日誌:
{source_json}
"""


def call_ollama(prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 320},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None

    data = json.loads(response_body)
    if not isinstance(data, dict):
        return ""
    return str(data.get("response", "")).strip()


def normalize_answer(text: str) -> str:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith(("承知", "了解"))
    ]
    if not lines:
        return "・日次日誌から確認できる内容は未確認です。\n"
    if len(lines) < 3:
        lines.extend(["・詳細は未確認です。"] * (3 - len(lines)))
    normalized = [line if line.startswith(("・", "-", "*", "🤖")) else f"・{line}" for line in lines[:7]]
    return "\n".join(normalized).rstrip() + "\n"


def main() -> int:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        query = sys.stdin.read().strip()
    if not query:
        query = "今日何かあった？"

    summaries = load_summaries(dates_for_query(query)) if has_time_reference(query) else load_recent_summaries()
    if not summaries:
        print("日次日誌なし")
        return 0

    answer = call_ollama(build_prompt(query, summaries))
    if answer is None:
        print("Gemma4B未起動")
        return 0

    print(normalize_answer(answer), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
