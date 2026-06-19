import csv
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scrapers.utils.google_sheet_events import sync_simple_csv_to_sheet


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
    _validate_header(csv_path)
    return sync_simple_csv_to_sheet(csv_path, SHEET_NAME, LABEL)


if __name__ == "__main__":
    sync_orbis_sheet()
