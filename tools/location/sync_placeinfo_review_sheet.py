#!/usr/bin/env python3
"""Sync PlaceInfo review TSV to Google Sheets."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config


DEFAULT_TSV = ROOT / "data" / "location" / "placeinfo_review.tsv"
SHEET_NAME = getattr(config, "PLACEINFO_REVIEW_SHEET_NAME", "PlaceInfo_Review")
AUTO_UPDATE_COLUMNS = [
    "timestamp",
    "message_id",
    "lat",
    "lon",
    "address",
    "current_guess",
    "candidate1",
    "candidate2",
    "candidate3",
    "candidate4",
    "candidate5",
    "google_maps_url",
]
MANUAL_REVIEW_COLUMNS = [
    "my_comment",
    "expected",
    "judge",
    "fix_policy",
    "fixed_at",
    "retest_result",
    "reviewed",
    "correct_address",
    "correct_road",
    "correct_intersection",
    "correct_landmark",
    "correct_label",
    "note",
]
REQUIRED_COLUMNS = AUTO_UPDATE_COLUMNS + MANUAL_REVIEW_COLUMNS


def read_tsv_rows(path: Path) -> list[list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"TSV not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f, delimiter="\t"))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _dicts_from_rows(rows: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    if not rows:
        return [], []
    header = [_text(column) for column in rows[0]]
    records: list[dict[str, str]] = []
    for values in rows[1:]:
        if not any(_text(value) for value in values):
            continue
        record = {
            column: _text(values[index]) if index < len(values) else ""
            for index, column in enumerate(header)
            if column
        }
        records.append(record)
    return header, records


def _deduped_header(*headers: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for header in headers:
        for column in header:
            column = _text(column)
            if not column or column in seen:
                continue
            result.append(column)
            seen.add(column)
    return result


def _column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters or "A"


def review_row_key(row: dict[str, str]) -> str:
    message_id = _text(row.get("message_id"))
    if message_id:
        return f"message_id:{message_id}"
    lat = _text(row.get("lat"))
    lon = _text(row.get("lon"))
    timestamp = _text(row.get("timestamp"))
    if lat or lon or timestamp:
        return f"fallback:{lat}:{lon}:{timestamp}"
    return ""


def merge_review_records(
    tsv_header: list[str],
    tsv_records: list[dict[str, str]],
    sheet_header: list[str],
    sheet_records: list[dict[str, str]],
) -> list[list[str]]:
    header = _deduped_header(tsv_header, REQUIRED_COLUMNS, sheet_header)
    merged_records: list[dict[str, str]] = []
    index_by_key: dict[str, int] = {}

    for record in sheet_records:
        key = review_row_key(record)
        if key and key in index_by_key:
            continue
        index_by_key[key or f"sheet-row:{len(merged_records)}"] = len(merged_records)
        merged_records.append({column: _text(record.get(column)) for column in header})

    for record in tsv_records:
        key = review_row_key(record)
        if key and key in index_by_key:
            merged = merged_records[index_by_key[key]]
            for column in AUTO_UPDATE_COLUMNS:
                if column in header:
                    merged[column] = _text(record.get(column))
            for column in tsv_header:
                if column not in MANUAL_REVIEW_COLUMNS and column in header:
                    merged[column] = _text(record.get(column))
            continue

        merged = {column: "" for column in header}
        for column in header:
            merged[column] = _text(record.get(column))
        if key:
            index_by_key[key] = len(merged_records)
        merged_records.append(merged)

    return [header] + [[record.get(column, "") for column in header] for record in merged_records]


def default_place_dict_spreadsheet_id() -> str:
    """Return the Google Sheets ID for the location dictionary DB.

    PlaceInfo_Review now belongs to the location dictionary DB.  When that
    database is not configured yet, keep the previous event DB behavior.
    """

    for attr in ("PLACE_DICT_SHEET_ID", "LOCATION_SHEET_ID", "EVENT_SHEET_ID"):
        value = str(getattr(config, attr, "") or "").strip()
        if value:
            return value

    from scrapers.utils.google_sheet_events import _default_spreadsheet_id

    return _default_spreadsheet_id()


def sync_placeinfo_review_sheet(tsv_path: Path = DEFAULT_TSV, sheet_name: str = SHEET_NAME) -> bool:
    tsv_values = read_tsv_rows(tsv_path)
    if not tsv_values:
        print(f"PlaceInfoレビューTSV空: {tsv_path}")
        return False
    if len(tsv_values) <= 1:
        print(f"PlaceInfoレビューTSV 0件のためGoogle Sheets同期をスキップ: {tsv_path}")
        return False

    from scrapers.utils.google_sheet_events import (
        _create_sheet,
        _read_sheet_rows,
        _sheet_exists,
        _sheets_service,
    )

    spreadsheet_id = default_place_dict_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError("Google spreadsheet ID is not configured")

    service = _sheets_service()
    if not _sheet_exists(service, spreadsheet_id, sheet_name):
        _create_sheet(service, spreadsheet_id, sheet_name)
        print(f"PlaceInfoレビューGoogle Sheetsシート作成: {sheet_name}")

    tsv_header, tsv_records = _dicts_from_rows(tsv_values)
    sheet_values = _read_sheet_rows(service, spreadsheet_id, sheet_name)
    sheet_header, sheet_records = _dicts_from_rows(sheet_values)
    values = merge_review_records(tsv_header, tsv_records, sheet_header, sheet_records)

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
    if len(sheet_values) > len(values):
        last_column = _column_letter(max(len(values[0]), len(sheet_values[0]) if sheet_values else 1))
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A{len(values) + 1}:{last_column}",
            body={},
        ).execute()

    print(f"PlaceInfoレビューGoogle Sheets同期完了: {max(len(values) - 1, 0)}件")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PlaceInfoレビューTSVをGoogle Sheetsへ同期する。")
    parser.add_argument("--tsv", type=Path, default=DEFAULT_TSV, help="同期するTSVパス。")
    parser.add_argument("--sheet-name", default=SHEET_NAME, help="Google Sheetsのシート名。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sync_placeinfo_review_sheet(args.tsv, args.sheet_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
