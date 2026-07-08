#!/usr/bin/env python3
"""Sync PlaceInfo review TSV to Google Sheets."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config


DEFAULT_TSV = ROOT / "data" / "location" / "placeinfo_review.tsv"
SHEET_NAME = getattr(config, "PLACEINFO_REVIEW_SHEET_NAME", "PlaceInfo_Review")


def read_tsv_rows(path: Path) -> list[list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"TSV not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f, delimiter="\t"))


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
    values = read_tsv_rows(tsv_path)
    if not values:
        print(f"PlaceInfoレビューTSV空: {tsv_path}")
        return False
    if len(values) <= 1:
        print(f"PlaceInfoレビューTSV 0件のためGoogle Sheets同期をスキップ: {tsv_path}")
        return False

    from scrapers.utils.google_sheet_events import (
        _create_sheet,
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

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=sheet_name,
        body={},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body={"values": values},
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
