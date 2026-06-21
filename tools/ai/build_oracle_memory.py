#!/usr/bin/env python3
"""case_memoryからOracle用の成功/失敗/注意点メモリを作る。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
CASE_MEMORY_DIR = AI_DIR / "case_memory"
ORACLE_MEMORY_PATH = AI_DIR / "oracle_memory.json"

SUCCESS_WORDS = ("成功", "完了", "解決", "動いた", "生成", "同期", "取得しました", "候補を生成")
FAILURE_WORDS = ("OCR失敗", "読めねー案件", "エラー", "download_failed", "TSV失敗", "失敗", "空", "未実行")
CAUTION_RULES = {
    "ocr": ("OCR", "読めねー案件", "画像", "PDF", "文字認識"),
    "tsv": ("TSV", "candidate", "候補", "手動確認"),
    "road": ("交通規制", "通行止", "事故", "道路", "オービス"),
    "railway": ("新幹線", "運休", "運転再開", "遅延"),
    "event": ("御園座", "IGアリーナ", "熱田まつり", "ドラゴンズ", "イベント"),
    "sync": ("CSV", "Sheets", "同期"),
}

sys.path.insert(0, str(ROOT))
from tools.ai import content_filter  # noqa: E402


def load_case(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def case_text(case: dict[str, Any]) -> str:
    parts = [
        str(case.get("problem", "")),
        str(case.get("solution", "")),
        str(case.get("result", "")),
    ]
    for message in case.get("messages", []):
        if isinstance(message, dict):
            parts.append(str(message.get("content", "")))
    return "\n".join(part for part in parts if part)


def summarize_text(text: str, max_len: int = 120) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not content_filter.is_filtered(line)]
    summary = " / ".join(lines[:2])
    if len(summary) > max_len:
        summary = summary[: max_len - 1].rstrip() + "…"
    return summary


def source_file(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def classify_topics(text: str) -> list[str]:
    topics: list[str] = []
    for topic, words in CAUTION_RULES.items():
        if any(word in text for word in words):
            topics.append(topic)
    return topics or ["general"]


def lesson_for_success(text: str) -> str:
    if "OCR" in text and "TSV" in text:
        return "画像/PDF案件はローカル保存、OCR、TSV候補生成の順で処理すると成功しやすい。"
    if "Sheets" in text or "同期" in text:
        return "Sheets/CSV反映は候補確認後に同期する。"
    if "Discord" in text or "メンション" in text:
        return "Bot起動はメンションまたは既存コマンドを入口にする。"
    return "成功事例として、同種案件では過去手順を優先して確認する。"


def lesson_for_failure(text: str) -> str:
    if "download_failed" in text:
        return "Discord添付はURLよりlocal_pathを優先し、保存失敗時は再投稿を促す。"
    if "OCR" in text or "読めねー案件" in text:
        return "OCR結果は誤認識を含むため、空文字や低信頼なら手動確認に回す。"
    if "TSV" in text:
        return "TSV候補はdate/start_time/end_time/venue/titleの欠損を確認する。"
    return "失敗事例として、断定せずcandidate扱いで人手確認へ回す。"


def build_case_item(path: Path, case: dict[str, Any], kind: str) -> dict[str, Any]:
    text = case_text(case)
    lesson = lesson_for_success(text) if kind == "success" else lesson_for_failure(text)
    return {
        "timestamp": str(case.get("timestamp", "")),
        "channel": str(case.get("channel", "")),
        "summary": summarize_text(text),
        "lesson": lesson,
        "topics": classify_topics(text),
        "source": source_file(path),
    }


def build_cautions(cases: list[tuple[Path, dict[str, Any]]]) -> list[dict[str, Any]]:
    topic_counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for path, case in cases:
        text = case_text(case)
        summary = summarize_text(text, max_len=80)
        for topic in classify_topics(text):
            topic_counts[topic] += 1
            examples.setdefault(topic, [])
            if len(examples[topic]) < 3:
                examples[topic].append(summary or source_file(path))

    notes = {
        "ocr": "OCRは誤認識や空文字を含むため、確定情報にせず候補として扱う。",
        "tsv": "TSV候補は人手確認前提。欠損があれば採用しない。",
        "road": "交通規制PDFではイベント時刻と規制時間を混同しない。",
        "railway": "運転再開は復旧ではない。影響継続の可能性を残す。",
        "event": "イベント/需要情報は現場ログと公式情報を分けて扱う。",
        "sync": "CSV/Sheets同期は自動確定せず、候補確認後に進める。",
        "general": "不明点は未確認またはcandidateとして扱う。",
    }
    cautions = []
    for topic, count in topic_counts.most_common():
        cautions.append(
            {
                "topic": topic,
                "note": notes.get(topic, notes["general"]),
                "count": count,
                "examples": examples.get(topic, []),
            }
        )
    return cautions


def iter_case_files() -> list[Path]:
    if not CASE_MEMORY_DIR.exists():
        return []
    return [
        path
        for path in sorted(CASE_MEMORY_DIR.glob("*.json"), reverse=True)
        if path.name != "case_memory_index.json"
    ]


def build_oracle_memory() -> dict[str, Any]:
    success_cases: list[dict[str, Any]] = []
    failure_cases: list[dict[str, Any]] = []
    all_cases: list[tuple[Path, dict[str, Any]]] = []

    for path in iter_case_files():
        case = load_case(path)
        if case is None:
            continue
        text = case_text(case)
        if content_filter.is_filtered(text):
            continue
        all_cases.append((path, case))
        has_success = any(word in text for word in SUCCESS_WORDS) or bool(str(case.get("result", "")).strip())
        has_failure = any(word in text for word in FAILURE_WORDS) or not has_success
        if has_success:
            success_cases.append(build_case_item(path, case, "success"))
        if has_failure:
            failure_cases.append(build_case_item(path, case, "failure"))

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": {
            "case_memory_dir": source_file(CASE_MEMORY_DIR),
            "case_memory_count": len(all_cases),
        },
        "success_cases": success_cases[:40],
        "failure_cases": failure_cases[:40],
        "cautions": build_cautions(all_cases)[:20],
        "notes": [
            "Oracle記憶は判断補助です。本番データを勝手に確定しない。",
            "候補はcandidateとして扱う。",
            "不明点は未確認とする。",
        ],
    }


def save_oracle_memory(memory: dict[str, Any]) -> None:
    AI_DIR.mkdir(parents=True, exist_ok=True)
    with ORACLE_MEMORY_PATH.open("w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    memory = build_oracle_memory()
    save_oracle_memory(memory)
    print(f"case_memory: {memory['source']['case_memory_count']}")
    print(f"success_cases: {len(memory['success_cases'])}")
    print(f"failure_cases: {len(memory['failure_cases'])}")
    print(f"cautions: {len(memory['cautions'])}")
    print(f"saved: {source_file(ORACLE_MEMORY_PATH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
