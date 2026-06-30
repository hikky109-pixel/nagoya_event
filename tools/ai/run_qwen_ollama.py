#!/usr/bin/env python3
"""Ollama上のQwenで名駅AIコメントを生成する。

既存の送信系との互換性を保つため、出力先は gemma_comment.txt/json のままにする。
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

try:
    from log_utils import log
except ModuleNotFoundError:
    from tools.ai.log_utils import log


DATA_DIR = ROOT / "data"
AI_DIR = DATA_DIR / "ai"
CONTEXT_PATH = AI_DIR / "daily_context.json"
REPORT_PATH = AI_DIR / "gemma_report.txt"
TEXT_OUTPUT_PATH = AI_DIR / "gemma_comment.txt"
JSON_OUTPUT_PATH = AI_DIR / "gemma_comment.json"
CRUISE_CSV_PATH = ROOT / "csv_events" / "cruise.csv"
ASIA_CSV_PATH = ROOT / "csv_events" / "asia.csv"
BUSY_LOG_PATH = DATA_DIR / "signals" / "meieki_busy_log.jsonl"
OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_QWEN_OLLAMA_MODEL = "qwen2.5:7b"
PROMPT_CONTEXT_BYTE_LIMIT = 6144
PROMPT_REPORT_BYTE_LIMIT = 1536
AI_MODEL = getattr(config, "AI_MODEL", "qwen") or "qwen"
MODEL = os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_QWEN_OLLAMA_MODEL

CONTEXT_KEYS = (
    "events",
    "railway",
    "road",
    "weather",
    "cruise",
    "asia_games",
    "busy_reports",
)

OUTPUT_SCHEMA = {
    "headline": "15字から32字の短い見出し。事実ベース。",
    "railway": ["鉄道で利用者に伝えるべき事項。なければ空配列。"],
    "road": ["道路・規制・渋滞で伝えるべき事項。なければ空配列。"],
    "weather": ["天気警報・注意報で伝えるべき事項。なければ空配列。"],
    "events": ["イベント起因の混雑や送迎需要。なければ空配列。"],
    "cruise": ["クルーズ船の入出港による需要。なければ空配列。"],
    "asia_games": ["アジア大会関連の需要。なければ空配列。"],
    "busy_reports": ["名駅繁忙ボタンの現場報告。なければ空配列。"],
    "note": "最後に1文だけ。不要なら空文字。",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_csv_rows(path: Path, limit: int = 80) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []
    today = date.today().isoformat()
    upcoming = [row for row in rows if str(row.get("date", "")) >= today]
    return (upcoming or rows)[:limit]


def read_busy_reports(limit: int = 50) -> list[dict[str, Any]]:
    if not BUSY_LOG_PATH.exists():
        return []
    try:
        lines = BUSY_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("type") == "cancel":
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return list(reversed(rows))


def compact_list(value: Any, limit: int) -> Any:
    if isinstance(value, list):
        return value[:limit]
    return value


def build_input_context() -> dict[str, Any]:
    context = load_json(CONTEXT_PATH)
    road_events = context.get("road") or context.get("road_events") or []

    qwen_context: dict[str, Any] = {
        "events": compact_list(context.get("events", []), 80),
        "railway": context.get("railway", {}),
        "road": compact_list(road_events, 80),
        "weather": context.get("weather", {}),
        "cruise": compact_list(context.get("cruise") or read_csv_rows(CRUISE_CSV_PATH), 80),
        "asia_games": compact_list(context.get("asia_games") or read_csv_rows(ASIA_CSV_PATH), 80),
        "busy_reports": compact_list(context.get("busy_reports") or read_busy_reports(), 50),
    }
    return qwen_context


def utf8_size(text: str) -> int:
    return len(text.encode("utf-8"))


def truncate_utf8(text: str, byte_limit: int) -> str:
    if utf8_size(text) <= byte_limit:
        return text
    marker = "\n... truncated ..."
    marker_bytes = utf8_size(marker)
    body_limit = max(0, byte_limit - marker_bytes)
    return text.encode("utf-8")[:body_limit].decode("utf-8", errors="ignore") + marker


def serialize_input_context(input_context: dict[str, Any]) -> str:
    return json.dumps(input_context, ensure_ascii=False, indent=2, default=str)


def build_prompt(input_context: dict[str, Any], report: str) -> str:
    context_json = truncate_utf8(serialize_input_context(input_context), PROMPT_CONTEXT_BYTE_LIMIT)
    report_text = truncate_utf8(report, PROMPT_REPORT_BYTE_LIMIT)
    return "\n".join(
        [
            "あなたは名駅AIです。名古屋駅周辺の交通・天気・イベント情報を短く実務向けに整理してください。",
            "推測は禁止。入力に無い事実を補わないでください。",
            "送信文はこの後Python側の固定テンプレートへ流し込むため、必ずJSONだけを返してください。",
            "Markdown、前置き、コードフェンスは禁止です。",
            "",
            "JSONスキーマ:",
            json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2),
            "",
            "入力コンテキスト:",
            context_json,
            "",
            "既存レポート:",
            report_text,
        ]
    )


def call_ollama(prompt: str) -> dict[str, Any] | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        log(f"qwen_ollama_error: {exc}")
        return None


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    candidates = [stripped]
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def normalize_items(value: Any, limit: int = 3) -> list[str]:
    if isinstance(value, str):
        values: list[Any] = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []

    items: list[str] = []
    for item in values:
        text = " ".join(str(item or "").split())
        if not text:
            continue
        items.append(text[:120])
        if len(items) >= limit:
            break
    return items


def render_section(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [title, *[f"・{item}" for item in items]]


def render_comment(data: dict[str, Any]) -> str:
    headline = " ".join(str(data.get("headline") or "名駅周辺メモ").split())[:40]
    lines: list[str] = ["名駅AI", headline, ""]

    sections = [
        ("交通", normalize_items(data.get("railway")) + normalize_items(data.get("road"))),
        ("天気", normalize_items(data.get("weather"))),
        ("イベント", normalize_items(data.get("events"))),
        ("港・大会", normalize_items(data.get("cruise"), 2) + normalize_items(data.get("asia_games"), 2)),
        ("現場繁忙", normalize_items(data.get("busy_reports"), 3)),
    ]
    for title, items in sections:
        rendered = render_section(title, items)
        if rendered:
            lines.extend(rendered)
            lines.append("")

    note = " ".join(str(data.get("note") or "").split())[:120]
    if note:
        lines.append(note)

    return "\n".join(lines).strip()


def fallback_comment(input_context: dict[str, Any]) -> str:
    counts = {
        key: len(value) if isinstance(value, list) else int(bool(value))
        for key, value in input_context.items()
    }
    active = [key for key, count in counts.items() if count]
    if not active:
        return ""
    return render_comment(
        {
            "headline": "名駅周辺の入力情報を確認",
            "events": [f"入力あり: {', '.join(active)}"],
            "note": "詳細文の生成に失敗したため、固定テンプレートで概要のみ記録します。",
        }
    )


def write_comment_result(result: dict[str, Any], comment: str) -> None:
    AI_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_OUTPUT_PATH.write_text(comment, encoding="utf-8")
    with JSON_OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")


def main() -> int:
    log(f"ai_model: {AI_MODEL}")
    log(f"ollama_model: {MODEL}")
    input_context = build_input_context()
    context_json = serialize_input_context(input_context)
    log(f"qwen_context_json_bytes: {utf8_size(context_json)}")
    report = load_text(REPORT_PATH)
    prompt = build_prompt(input_context, report)
    log(f"qwen_prompt_bytes: {utf8_size(prompt)}")
    response = call_ollama(prompt)

    if response is None:
        comment = fallback_comment(input_context)
        result = {
            "generated_at": now_iso(),
            "ai_model": AI_MODEL,
            "model": MODEL,
            "comment": comment,
            "done": False,
            "ollama_error": True,
            "input_context_keys": list(CONTEXT_KEYS),
        }
        write_comment_result(result, comment)
        return 0

    raw = str(response.get("response", "")).strip()
    parsed = extract_json_object(raw)
    comment = render_comment(parsed) if parsed else fallback_comment(input_context)
    result = {
        "generated_at": now_iso(),
        "ai_model": AI_MODEL,
        "model": MODEL,
        "comment": comment,
        "done": bool(response.get("done")) and bool(comment),
        "input_context_keys": list(CONTEXT_KEYS),
        "raw_response": raw,
        "template": "qwen_fixed_v1",
    }
    write_comment_result(result, comment)
    log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
    log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
