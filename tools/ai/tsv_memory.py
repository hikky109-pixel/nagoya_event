#!/usr/bin/env python3
"""TSV候補とメタ情報を保存する。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TSV_CANDIDATE_DIR = ROOT / "data" / "ai" / "tsv_candidate"


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def timestamp_key() -> str:
    return now_local().strftime("%Y-%m-%d_%H%M")


def count_tsv_rows(tsv_text: str) -> int:
    return len([line for line in tsv_text.splitlines() if line.strip()])


def save_tsv_candidate(source: str, tsv_text: str) -> tuple[Path, Path, dict[str, Any]]:
    TSV_CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    key = timestamp_key()
    tsv_path = TSV_CANDIDATE_DIR / f"{key}.tsv"
    json_path = TSV_CANDIDATE_DIR / f"{key}.json"
    if tsv_path.exists():
        suffix = now_local().strftime("%S")
        tsv_path = TSV_CANDIDATE_DIR / f"{key}_{suffix}.tsv"
        json_path = TSV_CANDIDATE_DIR / f"{key}_{suffix}.json"

    clean_text = tsv_text.strip()
    if clean_text:
        clean_text += "\n"
    tsv_path.write_text(clean_text, encoding="utf-8")

    meta = {
        "source": source,
        "rows": count_tsv_rows(clean_text),
        "timestamp": now_local().isoformat(timespec="seconds"),
    }
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return tsv_path, json_path, meta
