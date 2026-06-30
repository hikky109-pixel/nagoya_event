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
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config import AI_MODEL as CONFIG_AI_MODEL  # noqa: E402
from config import OLLAMA_MODEL  # noqa: E402

try:
    from log_utils import log
except ModuleNotFoundError:
    from tools.ai.log_utils import log

try:
    from tools.weather.weather_normalizer import get_all_weather_snapshot
except ModuleNotFoundError:
    try:
        from weather_normalizer import get_all_weather_snapshot
    except ModuleNotFoundError:
        get_all_weather_snapshot = None  # type: ignore[assignment]


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
OLLAMA_TIMEOUT_SECONDS = 240
CONTEXT_BYTE_LIMIT = 4000
PROMPT_CONTEXT_BYTE_LIMIT = 3800
PROMPT_REPORT_BYTE_LIMIT = 512
MAX_COMMENT_LINES = 5
MAX_LINE_CHARS = 40
MAX_COMMENT_CHARS = 200
AI_MODEL = CONFIG_AI_MODEL or "qwen"
LIST_LIMITS = {
    "events": 20,
    "road": 20,
    "cruise": 5,
    "asia_games": 10,
    "busy_reports": 5,
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
INTERNAL_MESSAGE_PATTERNS = (
    "入力あり:",
    "入力あり：",
)
FALLBACK_LABELS = {
    "events": "イベント情報を確認中",
    "railway": "鉄道情報を確認中",
    "road": "道路情報を確認中",
    "weather": "天気情報を確認中",
    "cruise": "クルーズ情報を確認中",
    "asia_games": "試合情報を確認中",
    "busy_reports": "混雑報告を確認中",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def resolve_ollama_model() -> tuple[str, str, str]:
    env_model = os.getenv("OLLAMA_MODEL", "").strip()
    config_model = str(OLLAMA_MODEL or "").strip()
    return env_model, config_model, config_model


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


def read_csv_rows(path: Path, limit: int = 20, *, today_only: bool = False) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []
    today = date.today().isoformat()
    if today_only:
        return [row for row in rows if str(row.get("date", "")) == today][:limit]
    upcoming = [row for row in rows if str(row.get("date", "")) >= today]
    return (upcoming or rows)[:limit]


def read_busy_reports(limit: int = 5) -> list[dict[str, Any]]:
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


def compact_value(value: Any, max_chars: int = 60) -> Any:
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


def today_records(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    today = date.today().isoformat()
    return [row for row in value if isinstance(row, dict) and str(row.get("date", "")) == today]


def compact_records(value: Any, key: str) -> Any:
    limit = LIST_LIMITS.get(key, 10)
    if not isinstance(value, list):
        return value
    rows = value[-limit:] if key == "busy_reports" else value[:limit]
    return [compact_mapping(row) for row in rows]


def qwen_weather_context(source_weather: Any) -> dict[str, Any]:
    weather = source_weather if isinstance(source_weather, dict) else {}
    result: dict[str, Any] = dict(weather)
    if get_all_weather_snapshot is None:
        return result
    try:
        snapshot = get_all_weather_snapshot()
    except Exception as exc:  # noqa: BLE001
        log(f"qwen_weather_snapshot_error: {type(exc).__name__}")
        return result

    sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), dict) else {}
    jma = sources.get("JMA") if isinstance(sources.get("JMA"), dict) else {}
    yahoo = sources.get("YahooWeather") if isinstance(sources.get("YahooWeather"), dict) else {}
    jma_alerts = jma.get("alerts") if isinstance(jma.get("alerts"), list) else []
    result["jma_alerts"] = jma_alerts
    if yahoo and not yahoo.get("error"):
        result["rain_now"] = bool(yahoo.get("rain_now"))
        result["heavy_rain"] = bool(yahoo.get("heavy_rain"))
        result["max_precip_mm"] = yahoo.get("max_precip_mm")
    else:
        result["rain_now"] = None
        result["heavy_rain"] = None
        result["max_precip_mm"] = None
    result["source"] = snapshot.get("source", [])
    return result


def build_input_context() -> dict[str, Any]:
    context = load_json(CONTEXT_PATH)
    road_events = context.get("road") or context.get("road_events") or []

    qwen_context: dict[str, Any] = {
        "events": compact_records(context.get("events", []), "events"),
        "railway": context.get("railway", {}),
        "road": compact_records(road_events, "road"),
        "weather": qwen_weather_context(context.get("weather", {})),
        "cruise": compact_records(
            today_records(context.get("cruise")) or read_csv_rows(CRUISE_CSV_PATH, limit=5, today_only=True),
            "cruise",
        ),
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
    return json.dumps(input_context, ensure_ascii=False, separators=(",", ":"), default=str)


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
            "入力JSONだけで名駅向け短文を作る。入力外知識と未記載固有名詞は禁止。",
            "推測は文頭を「推測:」にする。不明なら「判断材料不足」。",
            "出力はJSONのみ: {\"comment_lines\":[\"・...\"]}",
            "制限: 最大5行、各行1〜40文字、合計200文字以内。前置きや補足は禁止。",
            "禁止語: 名古屋城/中華街/Uber/外国人観光客/観光シーズン/過去年データ",
            "入力:",
            context_json,
            "",
            "レポート:",
            report_text,
        ]
    )


def call_ollama(prompt: str, model: str) -> dict[str, Any] | None:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 8192,
            "num_predict": 120,
            "top_p": 0.8,
            "repeat_penalty": 1.1,
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
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as res:
            return json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        log(f"qwen_ollama_error: {exc}")
        return None


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def extract_json_object(text: str) -> tuple[dict[str, Any], str]:
    stripped = strip_json_fence(text)
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, (list, str)):
        return {}, f"raw_response_type_{type(loaded).__name__}"
    if isinstance(loaded, dict):
        return loaded, ""

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
            return data, ""
        if isinstance(data, (list, str)):
            return {}, f"raw_response_type_{type(data).__name__}"
    return {}, "raw_response_not_json_object"


def context_counts(input_context: dict[str, Any]) -> dict[str, int]:
    return {
        key: len(value) if isinstance(value, list) else int(bool(value))
        for key, value in input_context.items()
    }


def has_input_data(input_context: dict[str, Any]) -> bool:
    return any(context_counts(input_context).values())


def normalize_comment_lines(value: Any, input_context: dict[str, Any]) -> tuple[list[str], str]:
    if not isinstance(value, list):
        return [], "comment_lines_not_list"

    lines: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return [], "comment_line_not_string"
        text = " ".join(item.split())
        text = text.lstrip("-・* ").strip()
        if not text:
            return [], "comment_line_empty"
        if any(pattern in text for pattern in INTERNAL_MESSAGE_PATTERNS):
            return [], "internal_message"
        if "判断材料不足" in text and has_input_data(input_context):
            return [], "insufficient_material_with_data"
        if not text.startswith("・"):
            text = f"・{text}"
        terms = forbidden_terms_in(text)
        if terms:
            return [], f"forbidden_terms={','.join(terms)}"
        if len(text) > MAX_LINE_CHARS:
            return [], f"comment_line_too_long chars={len(text)}"
        lines.append(text)
        if len(lines) >= MAX_COMMENT_LINES:
            break
    if not lines:
        return [], "comment_lines_empty"
    return lines, ""


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


def render_comment(data: dict[str, Any], input_context: dict[str, Any]) -> tuple[str, str]:
    if "comment_lines" not in data:
        return "", "comment_lines_missing"
    lines, reason = normalize_comment_lines(data.get("comment_lines"), input_context)
    if reason:
        return "", reason
    comment = "\n".join(lines)
    if len(comment) > MAX_COMMENT_CHARS:
        return "", f"comment_too_long chars={len(comment)}"
    guarded = guard_comment(comment)
    if guarded:
        return guarded, ""
    return "", "output_policy_rejected"


def fallback_comment(input_context: dict[str, Any]) -> str:
    counts = context_counts(input_context)
    active = [key for key, count in counts.items() if count]
    if not active:
        return "・判断材料不足"
    lines = [f"・{FALLBACK_LABELS.get(key, 'データを確認中')}" for key in active[:MAX_COMMENT_LINES]]
    return guard_comment("\n".join(lines))


def log_fallback(reason: str) -> None:
    log(f"qwen_fallback_reason: {reason}")


def log_output_lines(comment: str) -> None:
    lines = comment.splitlines() if comment else []
    log(f"qwen_output_lines: count={len(lines)} lines={json.dumps(lines, ensure_ascii=False)}")


def write_comment_result(result: dict[str, Any], comment: str) -> None:
    AI_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_OUTPUT_PATH.write_text(comment, encoding="utf-8")
    with JSON_OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")


def main() -> int:
    env_ollama_model, config_ollama_model, effective_ollama_model = resolve_ollama_model()
    log(f"ai_model: {AI_MODEL}")
    log(f"env_ollama_model: {env_ollama_model or '(unset)'}")
    log(f"config_ollama_model: {config_ollama_model or '(unset)'}")
    log(f"effective_ollama_model: {effective_ollama_model}")
    raw_input_context = build_input_context()
    raw_context_json = serialize_input_context(raw_input_context)
    log(f"qwen_context_json_raw_bytes: {utf8_size(raw_context_json)}")
    input_context = fit_context_to_limit(raw_input_context)
    context_json = serialize_input_context(input_context)
    log(f"qwen_context_json_bytes: {utf8_size(context_json)}")
    report = load_text(REPORT_PATH)
    prompt = build_prompt(input_context, report)
    log(f"qwen_prompt_bytes: {utf8_size(prompt)}")
    started_at = time.monotonic()
    response = call_ollama(prompt, effective_ollama_model)
    elapsed_seconds = time.monotonic() - started_at
    log(f"qwen_elapsed_seconds: {elapsed_seconds:.3f}")

    if response is None:
        log("qwen_response_bytes: 0")
        comment = fallback_comment(input_context)
        log_fallback("ollama_error")
        log_output_lines(comment)
        result = {
            "generated_at": now_iso(),
            "ai_model": AI_MODEL,
            "model": effective_ollama_model,
            "comment": comment,
            "done": False,
            "ollama_error": True,
            "input_context_keys": list(CONTEXT_KEYS),
        }
        write_comment_result(result, comment)
        return 0

    raw = str(response.get("response", "")).strip()
    log(f"qwen_response_bytes: {utf8_size(raw)}")
    parsed, invalid_reason = extract_json_object(raw)
    comment = ""
    if parsed:
        comment, invalid_reason = render_comment(parsed, input_context)
    if invalid_reason:
        log(f"qwen_schema_invalid: {invalid_reason}")
    if not comment:
        log_fallback(invalid_reason or "empty_output")
        comment = fallback_comment(input_context)
    log_output_lines(comment)
    result = {
        "generated_at": now_iso(),
        "ai_model": AI_MODEL,
        "model": effective_ollama_model,
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
