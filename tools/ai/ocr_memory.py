#!/usr/bin/env python3
"""OCR結果を data/ai/ocr_case に保存する。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OCR_CASE_DIR = ROOT / "data" / "ai" / "ocr_case"


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def ocr_path(image_case_path: str, timestamp: str = "") -> Path:
    stem = Path(image_case_path).stem or "unknown"
    if not timestamp:
        timestamp = now_local().isoformat(timespec="minutes")
    safe_timestamp = timestamp.replace(":", "").replace("-", "").replace("+", "_")
    return OCR_CASE_DIR / f"{safe_timestamp}_{stem}.json"


def save_ocr_case(ocr_case: dict[str, Any]) -> Path:
    OCR_CASE_DIR.mkdir(parents=True, exist_ok=True)
    path = ocr_path(
        str(ocr_case.get("image_case", "")),
        str(ocr_case.get("timestamp", "")),
    )
    with path.open("w", encoding="utf-8") as f:
        json.dump(ocr_case, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def output_exists_for(image_case_path: str) -> bool:
    if not OCR_CASE_DIR.exists():
        return False
    stem = Path(image_case_path).stem
    return any(path.stem.endswith(stem) for path in OCR_CASE_DIR.glob("*.json"))
