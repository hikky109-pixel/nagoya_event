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
CONTEXT_BYTE_LIMIT = 8192
PROMPT_CONTEXT_BYTE_LIMIT = 6144
PROMPT_REPORT_BYTE_LIMIT = 1536
MAX_COMMENT_LINES = 5
MAX_LINE_CHARS = 40
MAX_COMMENT_CHARS = 200
AI_MODEL = getattr(config, "AI_MODEL", "qwen") or "qwen"
MODEL = os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_QWEN_OLLAMA_MODEL
LIST_LIMITS = {
    "events": 20,
    "road": 20,
    "cruise": 10,
    "asia_games": 10,
    "busy_reports": 20,
}
COMPACT_FIELDS = (
    "date",
    "time",
    "end_time",
    "venue",
    "title",
    "source",
    "status",
    "note",
    "url",
    "line",
    "name",
    "place",
    "label",
    "ts",
    "timestamp",
)

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
    "comment_lines": [
        "入力JSONだけに基づく箇条書き。最大5行、1行40文字以内。"
    ],
}
FORBIDDEN_TERMS = (
    "名古屋城",
    "中華街",
    "Uber",
    "外国人観光客",
    "観光シーズン",
    "2024年現在",
    "2023年データ",
)


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


def read_csv_rows(path: Path, limit: int = 20) -> list[dict[str, str]]:
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


def read_busy_reports(limit: int = 20) -> list[dict[str, Any]]:
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


def compact_value(value: Any, max_chars: int = 100) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = " ".join(str(value).split())
    if not text:
        return ""
    return text[:max_chars]


def compact_mapping(row: Any) -> Any:
    if not isinstance(row, dict):
        return compact_value(row)
    compacted = {
        key: compact_value(row.get(key))
        for key in COMPACT_FIELDS
        if compact_value(row.get(key)) not in {"", None}
    }
    return compacted or {
        key: compact_value(value)
        for key, value in list(row.items())[:6]
        if compact_value(value) not in {"", None}
    }


def compact_records(value: Any, key: str) -> Any:
    limit = LIST_LIMITS.get(key, 10)
    if not isinstance(value, list):
        return value
    return [compact_mapping(row) for row in value[:limit]]


def build_input_context() -> dict[str, Any]:
    context = load_json(CONTEXT_PATH)
    road_events = context.get("road") or context.get("road_events") or []

    qwen_context: dict[str, Any] = {
        "events": compact_records(context.get("events", []), "events"),
        "railway": context.get("railway", {}),
        "road": compact_records(road_events, "road"),
        "weather": context.get("weather", {}),
        "cruise": compact_records(context.get("cruise") or read_csv_rows(CRUISE_CSV_PATH), "cruise"),
        "asia_games": compact_records(context.get("asia_games") or read_csv_rows(ASIA_CSV_PATH), "asia_games"),
        "busy_reports": compact_records(context.get("busy_reports") or read_busy_reports(), "busy_reports"),
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


def fit_context_to_limit(input_context: dict[str, Any], byte_limit: int = CONTEXT_BYTE_LIMIT) -> dict[str, Any]:
    fitted = dict(input_context)
    for key in ("events", "road", "busy_reports", "cruise", "asia_games"):
        value = fitted.get(key)
        if isinstance(value, list):
            fitted[key] = list(value)
    while utf8_size(serialize_input_context(fitted)) > byte_limit:
        longest_key = ""
        longest_len = 0
        for key, value in fitted.items():
            if isinstance(value, list) and len(value) > longest_len:
                longest_key = key
                longest_len = len(value)
        if not longest_key or longest_len <= 1:
            break
        fitted[longest_key] = fitted[longest_key][: max(1, longest_len // 2)]
    return fitted


def build_prompt(input_context: dict[str, Any], report: str) -> str:
    context_json = truncate_utf8(serialize_input_context(input_context), PROMPT_CONTEXT_BYTE_LIMIT)
    report_text = truncate_utf8(report, PROMPT_REPORT_BYTE_LIMIT)
    return "\n".join(
        [
            "【絶対ルール】",
            "・あなたは入力JSONだけを使う分析エンジンである",
            "・事前知識を使ってはいけない",
            "・入力に存在しない固有名詞を出してはいけない",
            "・名古屋城、観光地、Uber、外国人観光客等は禁止",
            "・推測する場合は必ず文頭に「推測:」を付ける",
            "・不明な場合は「判断材料不足」と出力する",
            "・嘘をつくくらいなら無回答を選ぶこと",
            "",
            "【出力制限】",
            "・最大5行",
            "・1行40文字以内",
            "・最大200文字",
            "・箇条書きのみ",
            "・絵文字は最大3個",
            "・前置き、まとめ、補足、免責は禁止",
            "・JSON以外の出力は禁止",
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


def normalize_comment_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates: list[Any] = value.splitlines()
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []

    lines: list[str] = []
    for item in candidates:
        text = " ".join(str(item or "").split())
        text = text.lstrip("-・* ").strip()
        if not text:
            continue
        if not text.startswith("・"):
            text = f"・{text}"
        lines.append(text[:MAX_LINE_CHARS])
        if len(lines) >= MAX_COMMENT_LINES:
            break
    return lines


def forbidden_terms_in(text: str) -> list[str]:
    return [term for term in FORBIDDEN_TERMS if term in text]


def guard_comment(comment: str) -> str:
    if not comment.strip():
        return ""
    terms = forbidden_terms_in(comment)
    if terms:
        log(f"qwen_output_policy_warning: forbidden_terms={','.join(terms)}")
        return ""
    if len(comment) > MAX_COMMENT_CHARS:
        log(f"qwen_output_policy_warning: too_long chars={len(comment)}")
        return ""
    return comment


def render_comment(data: dict[str, Any]) -> str:
    lines = normalize_comment_lines(data.get("comment_lines"))
    comment = "\n".join(lines)
    guarded = guard_comment(comment)
    if guarded:
        return guarded
    return ""


def fallback_comment(input_context: dict[str, Any]) -> str:
    counts = {
        key: len(value) if isinstance(value, list) else int(bool(value))
        for key, value in input_context.items()
    }
    active = [key for key, count in counts.items() if count]
    if not active:
        return ""
    active_text = ", ".join(active[:3])
    if len(active) > 3:
        active_text = f"{active_text} 他{len(active) - 3}件"
    lines = [
        f"・入力あり: {active_text}",
        "・判断材料不足",
    ]
    return guard_comment("\n".join(line[:MAX_LINE_CHARS] for line in lines))


def write_comment_result(result: dict[str, Any], comment: str) -> None:
    AI_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_OUTPUT_PATH.write_text(comment, encoding="utf-8")
    with JSON_OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")


def main() -> int:
    log(f"ai_model: {AI_MODEL}")
    log(f"ollama_model: {MODEL}")
    raw_input_context = build_input_context()
    raw_context_json = serialize_input_context(raw_input_context)
    log(f"qwen_context_json_raw_bytes: {utf8_size(raw_context_json)}")
    input_context = fit_context_to_limit(raw_input_context)
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
    comment = render_comment(parsed) if parsed else ""
    if not comment:
        comment = fallback_comment(input_context)
    result = {
        "generated_at": now_iso(),
        "ai_model": AI_MODEL,
        "model": MODEL,
        "comment": comment,
        "done": bool(response.get("done")) and bool(comment),
        "input_context_keys": list(CONTEXT_KEYS),
        "raw_response": raw,
        "template": "qwen_comment_lines_v1",
    }
    write_comment_result(result, comment)
    log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
    log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
