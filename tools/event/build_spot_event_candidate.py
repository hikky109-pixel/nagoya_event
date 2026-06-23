#!/usr/bin/env python3
"""スポットイベントOCRをPythonで構造化し、GemmaにはTSV整形だけを任せる。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

sys.path.insert(0, str(ROOT))
from tools.ai import tsv_memory  # noqa: E402
from tools.ai.normalize_tsv import log_normalize_result, normalize_tsv_with_stats  # noqa: E402
from tools.ai.output_guard import validate_structured_tsv_output  # noqa: E402


TIME_RE = re.compile(r"\d{1,2}[:：]\d{2}")
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})(?:日)?(?:\s*[（(][月火水木金土日][）)])?")
MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})月\s*(\d{1,2})日?")
ISO_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
YEAR_MONTH_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月")
REIWA_MONTH_RE = re.compile(r"令和\s*(\d{1,2})年\s*(\d{1,2})月")
MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})月")


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def normalize_text(text: str) -> str:
    return text.replace("：", ":").replace("−", "-").replace("―", "-").replace("ー", "-")


def detect_year_month(text: str, year: int | None = None, month: int | None = None) -> tuple[int | None, int | None]:
    if year is not None and month is not None:
        return year, month

    normalized = normalize_text(text)
    if year is None or month is None:
        match = YEAR_MONTH_RE.search(normalized)
        if match:
            year = year or int(match.group(1))
            month = month or int(match.group(2))

    if year is None or month is None:
        match = REIWA_MONTH_RE.search(normalized)
        if match:
            year = year or 2018 + int(match.group(1))
            month = month or int(match.group(2))

    if month is None:
        match = MONTH_RE.search(normalized)
        if match:
            month = int(match.group(1))

    return year, month


def _date_text(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _text_after_date(line: str) -> tuple[int | None, str]:
    iso_match = ISO_DATE_RE.search(line)
    if iso_match:
        return int(iso_match.group(3)), line[iso_match.end():]

    month_day_match = MONTH_DAY_RE.match(line.strip())
    if month_day_match:
        return int(month_day_match.group(2)), line.strip()[month_day_match.end():]

    match = DATE_RE.match(line.strip())
    if not match:
        return None, ""
    day = int(match.group(1))
    return day, line.strip()[match.end():]


def _clean_value(value: str) -> str:
    value = value.strip()
    if value in {"休", "休み"}:
        return "休演日"
    if value in {"-", "－", "—", "なし", "無し"}:
        return "-"
    if "貸切" in value:
        return "貸切"
    match = TIME_RE.search(value)
    if match:
        return match.group(0).replace("：", ":")
    return ""


def _line_values(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"\d{1,2}:\d{2}|貸切|休演日|[-－—]", text):
        value = _clean_value(match.group(0))
        if value:
            values.append(value)
    return values


def _looks_like_schedule_rest(text: str) -> bool:
    return bool(re.match(r"\s*(?:\d{1,2}:\d{2}|貸切|休演日|[-－—])(?:\s|/|$)", text))


def structure_spot_events(
    ocr_text: str,
    *,
    year: int | None = None,
    month: int | None = None,
) -> list[dict[str, str]]:
    """OCR本文から日付ごとの独立構造を作る。補完や推測はしない。"""
    detected_year, detected_month = detect_year_month(ocr_text, year, month)
    if detected_year is None or detected_month is None:
        return []

    records: list[dict[str, str]] = []
    seen_dates: set[str] = set()
    for raw_line in normalize_text(ocr_text).splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue

        day, rest = _text_after_date(line)
        if day is None:
            continue
        if not _looks_like_schedule_rest(rest):
            continue

        event_date = _date_text(detected_year, detected_month, day)
        if not event_date or event_date in seen_dates:
            continue

        values = _line_values(rest)
        record: dict[str, str] = {"date": event_date}
        if "休演日" in values or "休演日" in line:
            record["status"] = "休演日"
        else:
            play_values = [value for value in values if value != "-"]
            if play_values:
                record["day"] = play_values[0]
            if len(play_values) >= 2:
                record["night"] = play_values[1]

        if len(record) > 1:
            records.append(record)
            seen_dates.add(event_date)

    return records


def build_prompt(records: list[dict[str, str]], *, venue: str, title: str) -> str:
    payload = {
        "venue": venue,
        "title": title,
        "events": records,
    }
    source_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""このJSONをTSVへ変換してください。

ルール
* day と night は別行
* "-" は出力しない
* 貸切は TIME=貸切 TITLE=貸切
* 休演日は TIME=null TITLE=休演日
* END_TIME は全行 null
* VENUE は JSON の venue を使用
* TITLE は JSON の title を使用
* status は candidate 固定
* 説明禁止
* TSVのみ

列:
date
start_time
end_time
venue
title
status

JSON:
{source_json}
"""


def call_ollama(prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 500},
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


def _record_times(records: list[dict[str, str]]) -> set[str]:
    times: set[str] = set()
    for record in records:
        for key in ("day", "night"):
            value = record.get(key, "")
            if value and value not in {"-", "貸切"}:
                times.add(value)
    return times


def process_ocr_case(
    path: Path,
    *,
    venue: str,
    title: str,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any] | None:
    ocr_case = load_json(path)
    if not isinstance(ocr_case, dict):
        return None
    ocr_text = str(ocr_case.get("ocr_text", "")).strip()
    if not ocr_text or ocr_text.startswith("OCR失敗"):
        return None

    records = structure_spot_events(ocr_text, year=year, month=month)
    if not records:
        return None

    response = call_ollama(build_prompt(records, venue=venue, title=title))
    if response is None:
        return {"error": "Gemma4B未起動", "structured_rows": len(records)}

    ok, errors = validate_structured_tsv_output(records, response, venue=venue, title=title)
    if ok:
        print("gemma_output_guard: ok")
    else:
        print("gemma_output_guard:")
        print(errors)
        response = ""

    normalized = normalize_tsv_with_stats(response, source_times=_record_times(records), venue=venue)
    log_normalize_result(normalized)
    tsv_text = normalized.text
    tsv_path, json_path, meta = tsv_memory.save_tsv_candidate(str(path.relative_to(ROOT)), tsv_text)
    return {
        "tsv_path": str(tsv_path.relative_to(ROOT)),
        "json_path": str(json_path.relative_to(ROOT)),
        "rows": meta["rows"],
        "structured_rows": len(records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="スポットイベントOCRを構造化してTSV候補を生成する。")
    parser.add_argument("ocr_case", type=Path)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int)
    args = parser.parse_args()

    result = process_ocr_case(
        args.ocr_case,
        venue=args.venue,
        title=args.title,
        year=args.year,
        month=args.month,
    )
    if result is None:
        print("spot_event_candidates: 0")
        return 0
    if result.get("error") == "Gemma4B未起動":
        print("Gemma4B未起動")
        return 0
    print(f"wrote: {result['tsv_path']}")
    print(f"wrote: {result['json_path']}")
    print(f"rows: {result['rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
