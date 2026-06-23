#!/usr/bin/env python3
"""GemmaのTSV出力を保存前にPython側で最終補正する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from tools.ai.output_guard import extract_times, normalize_token


@dataclass(frozen=True)
class NormalizeResult:
    text: str
    rows_in: int
    rows_out: int
    dropped: int


def _is_null(value: str) -> bool:
    return value.strip().lower() in {"", "null", "none"}


def _null_value(value: str) -> str:
    return "null" if _is_null(value) else value.strip()


def _source_time_set(source_text: str, source_times: Iterable[str] | None) -> set[str]:
    if source_times is not None:
        return {normalize_token(time.strip()) for time in source_times if time.strip()}
    return extract_times(source_text)


def _row_parts(line: str) -> list[str] | None:
    clean_line = line.strip().strip("`")
    if not clean_line:
        return None
    if clean_line.lower().startswith(("date\t", "```", "tsv")):
        return None

    parts = [part.strip() for part in clean_line.split("\t")]
    if len(parts) < 5:
        return None
    while len(parts) < 6:
        parts.append("candidate")
    return parts[:6]


def normalize_tsv_with_stats(
    text: str,
    *,
    source_text: str = "",
    source_times: Iterable[str] | None = None,
    venue: str = "",
) -> NormalizeResult:
    allowed_times = _source_time_set(source_text, source_times)
    enforce_source_times = source_times is not None or bool(source_text)
    rows_in = 0
    rows: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    for raw_line in text.splitlines():
        parts = _row_parts(raw_line)
        if parts is None:
            continue
        rows_in += 1

        event_date, start_time, _end_time, row_venue, title, status = parts
        start_time = _null_value(normalize_token(start_time))
        end_time = "null"
        row_venue = venue or row_venue
        title = _null_value(title)
        status = "candidate"

        if title == "休演日":
            start_time = "null"
            end_time = "null"
        elif title == "貸切":
            start_time = "貸切"
        elif start_time in {"-", "null"}:
            continue
        elif enforce_source_times and normalize_token(start_time) not in allowed_times:
            continue

        key = (event_date, start_time, title)
        if key in seen:
            continue
        seen.add(key)

        rows.append("\t".join([event_date, start_time, end_time, row_venue, title, status]))

    result_text = "\n".join(rows)
    return NormalizeResult(
        text=result_text,
        rows_in=rows_in,
        rows_out=len(rows),
        dropped=rows_in - len(rows),
    )


def normalize_tsv(
    text: str,
    *,
    source_text: str = "",
    source_times: Iterable[str] | None = None,
    venue: str = "",
) -> str:
    return normalize_tsv_with_stats(
        text,
        source_text=source_text,
        source_times=source_times,
        venue=venue,
    ).text


def log_normalize_result(result: NormalizeResult) -> None:
    print(
        f"tsv_normalizer: rows_in={result.rows_in} "
        f"rows_out={result.rows_out} dropped={result.dropped}"
    )
