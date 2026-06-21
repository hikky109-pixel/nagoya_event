#!/usr/bin/env python3
"""過去の日誌・記憶を横断検索して自然言語で回答する。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
DAILY_SUMMARY_DIR = AI_DIR / "daily_summary"
DAILY_MEMORY_DIR = AI_DIR / "daily_memory"
HOURLY_SUMMARY_DIR = AI_DIR / "hourly_summary"
CHAT_MEMORY_DIR = AI_DIR / "chat_memory"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"
MAX_ITEMS = 18

sys.path.insert(0, str(ROOT))
from tools.ai import content_filter  # noqa: E402
from tools.ai.entity_dictionary import classify_by_dictionary  # noqa: E402
from tools.ai.entity_resolver import entity_system_prompt  # noqa: E402


def today() -> date:
    return datetime.now(timezone.utc).astimezone().date()


def parse_explicit_date(query: str) -> date | None:
    for token in query.replace("/", "-").split():
        try:
            return date.fromisoformat(token)
        except ValueError:
            continue
    return None


def query_dates(query: str) -> list[date] | None:
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
    if "今月" in query:
        start = current.replace(day=1)
        return [start + timedelta(days=offset) for offset in range((current - start).days + 1)]
    explicit = parse_explicit_date(query)
    if explicit is not None:
        return [explicit]
    return None


def load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def add_daily_summary(items: list[dict[str, str]], target_dates: list[date] | None) -> None:
    paths = sorted(DAILY_SUMMARY_DIR.glob("*.txt"), reverse=True)
    allowed = {target.isoformat() for target in target_dates} if target_dates is not None else None
    for path in paths:
        if allowed is not None and path.stem not in allowed:
            continue
        text = load_text(path)
        if text:
            items.append({"priority": "1_daily_summary", "date": path.stem, "source": str(path.relative_to(ROOT)), "text": text})


def add_daily_memory(items: list[dict[str, str]], target_dates: list[date] | None) -> None:
    paths = sorted(DAILY_MEMORY_DIR.glob("*.json"), reverse=True)
    allowed = {target.isoformat() for target in target_dates} if target_dates is not None else None
    for path in paths:
        if allowed is not None and path.stem not in allowed:
            continue
        data = load_json(path)
        if data is not None:
            items.append(
                {
                    "priority": "2_daily_memory",
                    "date": path.stem,
                    "source": str(path.relative_to(ROOT)),
                    "text": json.dumps(data, ensure_ascii=False),
                }
            )


def add_hourly_summary(items: list[dict[str, str]], target_dates: list[date] | None) -> None:
    paths = sorted(HOURLY_SUMMARY_DIR.glob("*.json"), reverse=True)
    allowed = {target.isoformat() for target in target_dates} if target_dates is not None else None
    for path in paths:
        date_key = path.stem[:10]
        if allowed is not None and date_key not in allowed:
            continue
        data = load_json(path)
        if data is not None:
            items.append(
                {
                    "priority": "3_hourly_summary",
                    "date": date_key,
                    "source": str(path.relative_to(ROOT)),
                    "text": json.dumps(data, ensure_ascii=False),
                }
            )


def add_chat_memory(items: list[dict[str, str]], target_dates: list[date] | None) -> None:
    allowed = {target.isoformat() for target in target_dates} if target_dates is not None else None
    for path in sorted(CHAT_MEMORY_DIR.glob("*.json"), reverse=True):
        data = load_json(path)
        if not isinstance(data, list):
            continue
        filtered_messages = []
        for item in reversed(data):
            if not isinstance(item, dict):
                continue
            message = str(item.get("message", ""))
            timestamp = str(item.get("timestamp", ""))
            date_key = timestamp[:10]
            if allowed is not None and date_key not in allowed:
                continue
            if content_filter.is_filtered(message):
                continue
            filtered_messages.append(item)
            if len(filtered_messages) >= 8:
                break
        if filtered_messages:
            items.append(
                {
                    "priority": "4_chat_memory",
                    "date": filtered_messages[0].get("timestamp", "")[:10],
                    "source": str(path.relative_to(ROOT)),
                    "text": json.dumps(list(reversed(filtered_messages)), ensure_ascii=False),
                }
            )


def collect_history(query: str) -> list[dict[str, str]]:
    dates = query_dates(query)
    items: list[dict[str, str]] = []
    add_daily_summary(items, dates)
    add_daily_memory(items, dates)
    add_hourly_summary(items, dates)
    add_chat_memory(items, dates)
    topic = classify_by_dictionary(query)
    if topic is not None:
        items = rank_topic_items(items, query)
    return items[:MAX_ITEMS]


def rank_topic_items(items: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    words = [word for word in query.replace("？", " ").replace("?", " ").split() if word]

    def score(item: dict[str, str]) -> tuple[int, str]:
        text = item["text"]
        hits = sum(1 for word in words if word in text)
        return hits, item["priority"]

    return sorted(items, key=score, reverse=True)


def build_prompt(query: str, items: list[dict[str, str]]) -> str:
    source_json = json.dumps(items, ensure_ascii=False, indent=2)
    dictionary_category = classify_by_dictionary(query) or "none"
    entity_prompt = entity_system_prompt(query)
    return f"""あなたはジェンマ課長です。

過去の日誌・記憶を根拠に、ユーザーへ3〜7行で回答してください。

{entity_prompt}

ルール:
- 不明なら「未確認」
- candidate を利用
- 勝手な断定禁止
- ツッコミ最大1回
- スギケツバットは毎回出さない
- 本番データを勝手に確定しない
- 運転再開≠復旧

辞書分類: {dictionary_category}
質問: {query}

検索結果:
{source_json}
"""


def call_ollama(prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 360},
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
    blocked_phrases = ("特筆すべき", "異常な兆候")
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not line.startswith(("承知", "了解"))
        and not any(phrase in line for phrase in blocked_phrases)
    ]
    if not lines:
        return "・過去の日誌から確認できる内容は未確認です。\n"
    if len(lines) < 3:
        lines.extend(["・詳細は未確認です。"] * (3 - len(lines)))
    normalized = [line if line.startswith(("・", "-", "*", "🤖")) else f"・{line}" for line in lines[:7]]
    return "\n".join(normalized).rstrip() + "\n"


def answer_query(query: str) -> str:
    items = collect_history(query)
    if not items:
        return "日誌記憶なし"
    answer = call_ollama(build_prompt(query, items))
    if answer is None:
        return "Gemma4B未起動"
    return normalize_answer(answer).rstrip()


def main() -> int:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        query = sys.stdin.read().strip()
    if not query:
        query = "今日何あった？"
    print(answer_query(query))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
