#!/usr/bin/env python3
"""GemmaのOCR整形出力に、OCR本文にない危険な値が混じっていないか検査する。"""

from __future__ import annotations

import re
from typing import Any


BLOCK_WORDS = {
    "Shibuya",
    "Tokyo",
    "MISONOZA",
    "LIVE",
}

ALLOWED_TSV_WORDS = {
    "candidate",
    "date",
    "start_time",
    "end_time",
    "venue",
    "title",
    "status",
}

TIME_RE = re.compile(r"(?<!\d)(\d{1,2}[:：]\d{2})(?!\d)")
TOKEN_RE = re.compile(
    r"\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}[:：]\d{2}"
    r"|[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*"
    r"|[\u3040-\u30ff\u3400-\u9fff々〆〤ヶ]+[A-Za-z0-9]*"
)


def normalize_token(token: str) -> str:
    token = token.replace("：", ":")
    if TIME_RE.fullmatch(token):
        hour, minute = token.split(":", 1)
        return f"{int(hour)}:{minute}"
    return token


def tokenize(text: str) -> set[str]:
    """英数字・日本語を、OCR照合用の粗い単語単位に分割する。"""
    return {normalize_token(match.group(0)) for match in TOKEN_RE.finditer(text)}


def extract_times(text: str) -> set[str]:
    return {normalize_token(match.group(1)) for match in TIME_RE.finditer(text)}


def validate_output(
    source_text: str,
    gemma_output: str,
) -> tuple[bool, list[str]]:
    source_tokens = tokenize(source_text)
    output_tokens = tokenize(gemma_output)
    extra_tokens = output_tokens - source_tokens - ALLOWED_TSV_WORDS

    source_times = extract_times(source_text)
    errors: list[str] = []
    seen: set[str] = set()
    for match in TOKEN_RE.finditer(gemma_output):
        token = normalize_token(match.group(0))
        is_unknown_token = token in extra_tokens
        is_blocked_word = token in BLOCK_WORDS
        is_unknown_time = bool(TIME_RE.fullmatch(token)) and token not in source_times
        if (is_unknown_token or is_blocked_word or is_unknown_time) and token not in seen:
            errors.append(token)
            seen.add(token)

    return (not errors, errors)


def _is_null(value: str) -> bool:
    return value.strip().lower() in {"", "null", "none"}


def _row_values(line: str) -> list[str]:
    values = [part.strip() for part in line.strip().strip("`").split("\t")]
    while len(values) < 6:
        values.append("")
    return values[:6]


def _allowed_times(records: list[dict[str, Any]]) -> set[str]:
    times = {"null", "貸切"}
    for record in records:
        for key in ("day", "night"):
            value = normalize_token(str(record.get(key, "")).strip())
            if not value or value == "-":
                continue
            if value == "貸切" or TIME_RE.fullmatch(value):
                times.add(value)
    return times


def _max_candidate_rows(records: list[dict[str, Any]]) -> int:
    count = 0
    for record in records:
        if str(record.get("status", "")).strip() == "休演日":
            count += 1
            continue
        for key in ("day", "night"):
            value = str(record.get(key, "")).strip()
            if value and value != "-":
                count += 1
    return count


def validate_structured_tsv_output(
    records: list[dict[str, Any]],
    gemma_output: str,
    *,
    venue: str,
    title: str,
    max_rows: int | None = None,
) -> tuple[bool, list[str]]:
    """Python構造化済みスポットイベントJSONからのTSV整形結果だけを検査する。"""
    allowed_dates = {str(record.get("date", "")).strip() for record in records if record.get("date")}
    allowed_times = _allowed_times(records)
    allowed_titles = {title, "休演日", "貸切"}
    row_limit = _max_candidate_rows(records) if max_rows is None else max_rows

    errors: list[str] = []
    rows = [
        _row_values(raw_line)
        for raw_line in gemma_output.splitlines()
        if raw_line.strip() and not raw_line.lower().startswith(("date\t", "```", "tsv"))
    ]

    if len(rows) > row_limit:
        errors.append(f"rows>{row_limit}")

    for index, row in enumerate(rows, start=1):
        event_date, start_time, end_time, row_venue, row_title, status = row
        start_time = normalize_token(start_time)

        if event_date not in allowed_dates:
            errors.append(f"row{index}:date:{event_date}")
        if start_time not in allowed_times:
            errors.append(f"row{index}:time:{start_time}")
        if not _is_null(end_time):
            errors.append(f"row{index}:end_time:{end_time}")
        if row_venue != venue:
            errors.append(f"row{index}:venue:{row_venue}")
        if row_title not in allowed_titles:
            errors.append(f"row{index}:title:{row_title}")
        if status != "candidate":
            errors.append(f"row{index}:status:{status}")

    return (not errors, errors)
