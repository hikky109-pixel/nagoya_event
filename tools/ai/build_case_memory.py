#!/usr/bin/env python3
"""Discord履歴JSONLからOracle用case_memoryを作る。"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DISCORD_HISTORY_DIR = ROOT / "data" / "ai" / "discord_history"
CASE_MEMORY_DIR = ROOT / "data" / "ai" / "case_memory"
INDEX_PATH = CASE_MEMORY_DIR / "case_memory_index.json"

PROBLEM_KEYWORDS = ("OCR失敗", "読めねー案件", "手動確認", "今北産業", "エラー", "download_failed", "TSV失敗")
SOLUTION_KEYWORDS = ("修正", "対応", "OCR", "TSV", "CSV", "Sheets", "再投稿")
RESULT_KEYWORDS = ("成功", "完了", "解決", "動いた", "生成", "同期")
TRAFFIC_KEYWORDS = ("事故", "通行止", "オービス", "新幹線", "運休")
EVENT_KEYWORDS = ("御園座", "IGアリーナ", "熱田まつり", "ドラゴンズ")
ALL_KEYWORDS = PROBLEM_KEYWORDS + SOLUTION_KEYWORDS + RESULT_KEYWORDS + TRAFFIC_KEYWORDS + EVENT_KEYWORDS

sys.path.insert(0, str(ROOT))
from tools.ai import content_filter  # noqa: E402


def load_index() -> set[str]:
    if not INDEX_PATH.exists():
        return set()
    try:
        with INDEX_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def save_index(keys: set[str]) -> None:
    CASE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        content = str(data.get("content", ""))
        if content_filter.is_filtered(content):
            continue
        rows.append(data)
    return rows


def keyword_hit(content: str) -> bool:
    return any(keyword in content for keyword in ALL_KEYWORDS)


def extract_by_keywords(messages: list[dict[str, Any]], keywords: tuple[str, ...]) -> str:
    parts: list[str] = []
    for message in messages:
        content = str(message.get("content", "")).strip()
        if content and any(keyword in content for keyword in keywords):
            parts.append(content)
    return "\n".join(parts[:3])


def fallback_problem(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        content = str(message.get("content", "")).strip()
        if content:
            return content
    return ""


def case_hash(messages: list[dict[str, Any]]) -> str:
    ids = [str(message.get("message_id", "")) for message in messages if message.get("message_id")]
    raw = "\n".join(ids) if ids else json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def timestamp_for_case(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        timestamp = str(message.get("timestamp", ""))
        if timestamp:
            return timestamp
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def filename_for_case(timestamp: str, digest: str) -> str:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone()
    except ValueError:
        parsed = datetime.now(timezone.utc).astimezone()
    return f"{parsed.strftime('%Y-%m-%d_%H%M%S')}_case_{digest}.json"


def build_case(messages: list[dict[str, Any]]) -> dict[str, Any]:
    timestamp = timestamp_for_case(messages)
    first = messages[0] if messages else {}
    problem = extract_by_keywords(messages, PROBLEM_KEYWORDS + TRAFFIC_KEYWORDS + EVENT_KEYWORDS) or fallback_problem(messages)
    solution = extract_by_keywords(messages, SOLUTION_KEYWORDS)
    result = extract_by_keywords(messages, RESULT_KEYWORDS)
    return {
        "timestamp": timestamp,
        "channel": str(first.get("channel_name", "")),
        "problem": problem,
        "solution": solution,
        "result": result,
        "messages": messages,
    }


def save_case(case: dict[str, Any], digest: str) -> Path:
    CASE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = CASE_MEMORY_DIR / filename_for_case(str(case.get("timestamp", "")), digest)
    with path.open("w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def process_history_file(path: Path, indexed: set[str]) -> tuple[int, int, int]:
    rows = read_jsonl(path)
    detected = 0
    saved = 0
    skipped = 0
    for index, row in enumerate(rows):
        content = str(row.get("content", ""))
        if not keyword_hit(content):
            continue
        start = max(0, index - 5)
        end = min(len(rows), index + 6)
        messages = rows[start:end]
        digest = case_hash(messages)
        detected += 1
        print(f"case_detected: {path.name} index={index} hash={digest}")
        if digest in indexed:
            skipped += 1
            print(f"case_skipped: {digest}")
            continue
        case = build_case(messages)
        saved_path = save_case(case, digest)
        indexed.add(digest)
        saved += 1
        print(f"case_saved: {saved_path.relative_to(ROOT)}")
    return detected, saved, skipped


def iter_history_files() -> list[Path]:
    if not DISCORD_HISTORY_DIR.exists():
        return []
    return sorted(DISCORD_HISTORY_DIR.glob("*.jsonl"))


def main() -> int:
    indexed = load_index()
    total_detected = 0
    total_saved = 0
    total_skipped = 0
    for path in iter_history_files():
        detected, saved, skipped = process_history_file(path, indexed)
        total_detected += detected
        total_saved += saved
        total_skipped += skipped
    save_index(indexed)
    print(f"case_detected_total: {total_detected}")
    print(f"case_saved_total: {total_saved}")
    print(f"case_skipped_total: {total_skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
