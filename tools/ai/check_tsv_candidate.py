#!/usr/bin/env python3
"""TSV候補の欠損・複合案件・道路候補をチェックする。"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TSV_CANDIDATE_DIR = ROOT / "data" / "ai" / "tsv_candidate"
TSV_QUALITY_DIR = ROOT / "data" / "ai" / "tsv_quality"
ROAD_CANDIDATE_DIR = ROOT / "data" / "ai" / "road_candidate"

REQUIRED_COLUMNS = ["date", "start_time", "end_time", "venue", "title"]
ROAD_WORDS = ("交通規制", "通行止", "車両通行止", "規制時間", "迂回")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def read_tsv(path: Path) -> list[list[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[list[str]] = []
    for line in lines:
        if line.strip():
            rows.append(line.split("\t"))
    return rows


def row_warnings(row: list[str]) -> list[str]:
    warnings: list[str] = []
    padded = row + [""] * max(0, 6 - len(row))
    values = {
        "date": padded[0].strip(),
        "start_time": padded[1].strip(),
        "end_time": padded[2].strip(),
        "venue": padded[3].strip(),
        "title": padded[4].strip(),
    }
    for key in REQUIRED_COLUMNS:
        if not values[key]:
            warnings.append(f"missing_{key}")
    return warnings


def confidence_for(warnings: list[str]) -> str:
    if not warnings:
        return "high"
    if len(warnings) <= 2:
        return "medium"
    return "low"


def source_text_for(meta_path: Path) -> str:
    meta = load_json(meta_path)
    if not isinstance(meta, dict):
        return ""
    source = meta.get("source")
    if not isinstance(source, str):
        return ""
    ocr_case = load_json(ROOT / source)
    if not isinstance(ocr_case, dict):
        return ""
    return str(ocr_case.get("ocr_text", ""))


def detect_case_type(source_text: str, rows: list[list[str]]) -> str:
    has_event = bool(rows)
    has_road = any(word in source_text for word in ROAD_WORDS)
    if has_event and has_road:
        return "event+road"
    if has_road:
        return "road"
    if has_event:
        return "event"
    return "unknown"


def extract_road_candidate(source_text: str, first_row: list[str]) -> dict[str, Any] | None:
    if not any(word in source_text for word in ROAD_WORDS):
        return None
    start_time = extract_time_after(source_text, ("規制", "通行止", "交通規制")) or (first_row[1] if len(first_row) > 1 else "")
    end_time = extract_end_time(source_text) or (first_row[2] if len(first_row) > 2 else "")
    title = first_row[4] if len(first_row) > 4 and first_row[4] else "交通規制"
    return {
        "name": f"{title}交通規制",
        "start_time": start_time,
        "end_time": end_time,
        "status": "candidate",
        "timestamp": now_iso(),
    }


def extract_time_after(text: str, markers: tuple[str, ...]) -> str:
    for marker in markers:
        index = text.find(marker)
        if index == -1:
            continue
        match = re.search(r"(\d{1,2}[:：]\d{2})", text[index:index + 80])
        if match:
            return match.group(1).replace("：", ":")
    return ""


def extract_end_time(text: str) -> str:
    times = [match.group(1).replace("：", ":") for match in re.finditer(r"(\d{1,2}[:：]\d{2})", text)]
    return times[-1] if len(times) >= 2 else ""


def save_quality(tsv_path: Path, quality: dict[str, Any]) -> Path:
    TSV_QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    path = TSV_QUALITY_DIR / f"{tsv_path.stem}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(quality, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def save_road_candidate(tsv_path: Path, road_candidate: dict[str, Any]) -> Path:
    ROAD_CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    path = ROAD_CANDIDATE_DIR / f"{tsv_path.stem}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(road_candidate, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def check_tsv_candidate(tsv_path: Path) -> dict[str, Any] | None:
    rows = read_tsv(tsv_path)
    meta_path = tsv_path.with_suffix(".json")
    source_text = source_text_for(meta_path)
    warnings: list[str] = []
    for row in rows:
        warnings.extend(row_warnings(row))
    case_type = detect_case_type(source_text, rows)
    confidence = confidence_for(warnings)
    quality = {
        "source": str(tsv_path.relative_to(ROOT)),
        "case_type": case_type,
        "confidence": confidence,
        "warnings": sorted(set(warnings)),
        "rows": len(rows),
        "timestamp": now_iso(),
    }
    save_quality(tsv_path, quality)
    if rows:
        road_candidate = extract_road_candidate(source_text, rows[0])
        if road_candidate is not None:
            road_path = save_road_candidate(tsv_path, road_candidate)
            quality["road_candidate"] = str(road_path.relative_to(ROOT))
            save_quality(tsv_path, quality)
    return quality


def iter_tsv_paths() -> list[Path]:
    if not TSV_CANDIDATE_DIR.exists():
        return []
    return sorted(TSV_CANDIDATE_DIR.glob("*.tsv"))


def main() -> int:
    checked = 0
    for path in iter_tsv_paths():
        quality = check_tsv_candidate(path)
        if quality is None:
            continue
        checked += 1
        print(f"checked: {path.relative_to(ROOT)} confidence={quality['confidence']} case_type={quality['case_type']}")
    print(f"tsv_quality_checked: {checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
