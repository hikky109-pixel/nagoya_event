#!/usr/bin/env python3
"""CSVからGoogle Sheetsへオービス秘伝のタレを復旧同期する。"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CSV_PATH = BASE_DIR / "data" / "orbis" / "orbis_mobile.csv"
SHEET_NAME = "オービス_可搬式"
LABEL = "オービス"
ORBIS_COLUMNS = ["category", "city", "road", "direction", "location", "note"]


def _validate_header(csv_path):
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.reader(csv_file)
        header = next(reader, [])

    if header != ORBIS_COLUMNS:
        raise RuntimeError(f"オービスCSVヘッダー不一致: {header}")


def sync_orbis_sheet(csv_path=CSV_PATH):
    from scrapers.utils.google_sheet_events import sync_simple_csv_to_sheet

    _validate_header(csv_path)
    return sync_simple_csv_to_sheet(csv_path, SHEET_NAME, LABEL)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "CSVの内容でGoogle Sheets「オービス_可搬式」を上書きします。"
            "通常運用では tools/orbis/pull_orbis_sheet.py を使ってください。"
        )
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="CSVの内容でGoogle Sheetsを上書きする場合だけ指定する",
    )
    parser.add_argument(
        "--csv-path",
        default=CSV_PATH,
        type=Path,
        help="同期元CSVパス",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.push:
        print(
            "sync_orbis_sheet.py は CSV→Google Sheets の上書き同期です。\n"
            "Google Sheetsを編集した直後に実行すると内容が消えるため、\n"
            "実行する場合は --push を付けてください。\n"
            "通常運用は Google Sheets編集 → pull_orbis_sheet.py → Git commit/push です。"
        )
        return 1

    sync_orbis_sheet(args.csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
