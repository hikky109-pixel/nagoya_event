#!/usr/bin/env python3
"""Sync local PlaceInfo dictionary YAML files to the location dictionary Sheets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config
from tools.location.place_labeler import DEFAULT_OVERRIDES_PATH, load_overrides
from tools.location.road_aliases import DEFAULT_ROAD_ALIASES_PATH, load_road_aliases
from tools.location.sync_placeinfo_review_sheet import default_place_dict_spreadsheet_id


MANUAL_COLUMNS = ["reviewed", "note", "enabled", "updated_by"]
PLACE_AUTO_COLUMNS = ["id", "lat", "lon", "radius_m", "label", "source", "confidence", "priority"]
ROAD_AUTO_COLUMNS = [
    "id",
    "name",
    "direction",
    "aliases",
    "source_url",
    "start",
    "end",
    "road_numbers",
    "intersections",
    "geometry",
    "source_note",
]

SOURCE_TO_SHEET = {
    "seeded_taxi_ops": getattr(config, "SEEDED_TAXI_OPS_SHEET_NAME", "Seeded_Taxi_Ops"),
    "seeded_landmark": getattr(config, "LANDMARKS_SHEET_NAME", "Landmarks"),
    "user_corrected": getattr(config, "PLACE_LABEL_OVERRIDES_SHEET_NAME", "Place_Label_Overrides"),
}
ROAD_ALIASES_SHEET_NAME = getattr(config, "ROAD_ALIASES_SHEET_NAME", "Road_Aliases")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value if _text(item))
    return _text(value)


def _dicts_from_rows(rows: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    if not rows:
        return [], []
    header = [_text(column) for column in rows[0]]
    records: list[dict[str, str]] = []
    for values in rows[1:]:
        if not any(_text(value) for value in values):
            continue
        records.append(
            {
                column: _text(values[index]) if index < len(values) else ""
                for index, column in enumerate(header)
                if column
            }
        )
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


def place_row_key(row: dict[str, str]) -> str:
    row_id = _text(row.get("id"))
    if row_id:
        return f"id:{row_id}"
    return "fallback:place:{source}:{lat}:{lon}:{label}".format(
        source=_text(row.get("source")),
        lat=_text(row.get("lat")),
        lon=_text(row.get("lon")),
        label=_text(row.get("label")),
    )


def road_row_key(row: dict[str, str]) -> str:
    row_id = _text(row.get("id"))
    if row_id:
        return f"id:{row_id}"
    return "fallback:road:{name}:{direction}:{start}:{end}".format(
        name=_text(row.get("name")),
        direction=_text(row.get("direction")),
        start=_text(row.get("start")),
        end=_text(row.get("end")),
    )


def merge_sheet_records(
    local_header: list[str],
    local_records: list[dict[str, str]],
    sheet_header: list[str],
    sheet_records: list[dict[str, str]],
    *,
    key_fn: Callable[[dict[str, str]], str],
    manual_columns: list[str] = MANUAL_COLUMNS,
) -> list[list[str]]:
    header = _deduped_header(local_header, manual_columns, sheet_header)
    merged_records: list[dict[str, str]] = []
    index_by_key: dict[str, int] = {}

    for record in sheet_records:
        key = key_fn(record)
        if key and key in index_by_key:
            existing = merged_records[index_by_key[key]]
            for column in manual_columns:
                if not existing.get(column) and _text(record.get(column)):
                    existing[column] = _text(record.get(column))
            continue
        index_by_key[key or f"sheet-row:{len(merged_records)}"] = len(merged_records)
        merged_records.append({column: _text(record.get(column)) for column in header})

    for record in local_records:
        key = key_fn(record)
        if key and key in index_by_key:
            merged = merged_records[index_by_key[key]]
            for column in local_header:
                if column not in manual_columns and column in header:
                    merged[column] = _text(record.get(column))
            continue

        merged = {column: "" for column in header}
        for column in header:
            merged[column] = _text(record.get(column))
        if key:
            index_by_key[key] = len(merged_records)
        merged_records.append(merged)

    return [header] + [[record.get(column, "") for column in header] for record in merged_records]


def place_override_record(spot: dict[str, Any]) -> dict[str, str]:
    return {column: _text(spot.get(column)) for column in PLACE_AUTO_COLUMNS}


def road_alias_record(road: dict[str, Any]) -> dict[str, str]:
    return {
        "id": _text(road.get("id")),
        "name": _text(road.get("name")),
        "direction": _text(road.get("direction")),
        "aliases": _list_text(road.get("aliases")),
        "source_url": _text(road.get("source_url")),
        "start": _text(road.get("start")),
        "end": _text(road.get("end")),
        "road_numbers": _list_text(road.get("road_numbers")),
        "intersections": _list_text(road.get("intersections")),
        "geometry": _text(road.get("geometry")),
        "source_note": _text(road.get("note")),
    }


def place_override_sheet_records(overrides_path: Path = DEFAULT_OVERRIDES_PATH) -> dict[str, list[dict[str, str]]]:
    grouped = {sheet_name: [] for sheet_name in SOURCE_TO_SHEET.values()}
    for spot in load_overrides(overrides_path):
        source = _text(spot.get("source"))
        sheet_name = SOURCE_TO_SHEET.get(source)
        if not sheet_name:
            continue
        grouped[sheet_name].append(place_override_record(spot))
    return grouped


def road_alias_sheet_records(road_aliases_path: Path = DEFAULT_ROAD_ALIASES_PATH) -> list[dict[str, str]]:
    return [road_alias_record(road) for road in load_road_aliases(road_aliases_path)]


def sync_records_to_sheet(
    service: Any,
    spreadsheet_id: str,
    sheet_name: str,
    local_header: list[str],
    local_records: list[dict[str, str]],
    *,
    key_fn: Callable[[dict[str, str]], str],
) -> int:
    from scrapers.utils.google_sheet_events import _create_sheet, _read_sheet_rows, _sheet_exists

    if not _sheet_exists(service, spreadsheet_id, sheet_name):
        _create_sheet(service, spreadsheet_id, sheet_name)
        print(f"場所辞書Google Sheetsシート作成: {sheet_name}")

    sheet_values = _read_sheet_rows(service, spreadsheet_id, sheet_name)
    sheet_header, sheet_records = _dicts_from_rows(sheet_values)
    values = merge_sheet_records(local_header, local_records, sheet_header, sheet_records, key_fn=key_fn)

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
    return max(len(values) - 1, 0)


def sync_place_dict_sheets(
    *,
    overrides_path: Path = DEFAULT_OVERRIDES_PATH,
    road_aliases_path: Path = DEFAULT_ROAD_ALIASES_PATH,
) -> dict[str, int]:
    from scrapers.utils.google_sheet_events import _sheets_service

    spreadsheet_id = default_place_dict_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError("Google spreadsheet ID is not configured")

    service = _sheets_service()
    results: dict[str, int] = {}

    for sheet_name, records in place_override_sheet_records(overrides_path).items():
        results[sheet_name] = sync_records_to_sheet(
            service,
            spreadsheet_id,
            sheet_name,
            PLACE_AUTO_COLUMNS,
            records,
            key_fn=place_row_key,
        )
        print(f"{sheet_name} 同期完了: {results[sheet_name]}件")

    road_records = road_alias_sheet_records(road_aliases_path)
    results[ROAD_ALIASES_SHEET_NAME] = sync_records_to_sheet(
        service,
        spreadsheet_id,
        ROAD_ALIASES_SHEET_NAME,
        ROAD_AUTO_COLUMNS,
        road_records,
        key_fn=road_row_key,
    )
    print(f"{ROAD_ALIASES_SHEET_NAME} 同期完了: {results[ROAD_ALIASES_SHEET_NAME]}件")
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="名古屋場所辞書DBへローカル場所辞書をsafe upsert同期する。")
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES_PATH, help="place_label_overrides.yml のパス。")
    parser.add_argument("--road-aliases", type=Path, default=DEFAULT_ROAD_ALIASES_PATH, help="road_aliases.yml のパス。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sync_place_dict_sheets(overrides_path=args.overrides, road_aliases_path=args.road_aliases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
