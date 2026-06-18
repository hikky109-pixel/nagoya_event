import csv
import io
import os
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests


COMMON_COLUMNS = ["date", "time", "end_time", "venue", "title", "source", "status", "note", "url"]
ROAD_SHEET_NAME = "道路情報"
ROAD_HISTORY_SHEET_NAME = "【過去】道路情報"
CRUISE_SHEET_NAME = "クルーズ船"
ASIA_SHEET_NAME = "アジア大会"
ROAD_EXTRA_COLUMNS = [
    "actual_date",
    "actual_time",
    "actual_place",
    "direction",
    "result",
    "source_detail",
    "memo",
]
ROAD_COLUMNS = COMMON_COLUMNS + ROAD_EXTRA_COLUMNS
ROAD_KEY_COLUMNS = ["date", "venue", "title", "note", "source", "url"]
SHEET_URLS = {
    'misonoza': 'https://docs.google.com/spreadsheets/d/12MNpRn0Krk3WVRFoj37bST2fXBGnomeQ-DQ4N9VA-7c/gviz/tq?tqx=out:csv&sheet=%E5%BE%A1%E5%9C%92%E5%BA%A7',
    'spot': 'https://docs.google.com/spreadsheets/d/12MNpRn0Krk3WVRFoj37bST2fXBGnomeQ-DQ4N9VA-7c/gviz/tq?tqx=out:csv&sheet=%E3%82%B9%E3%83%9D%E3%83%83%E3%83%88',
    'ajipara': 'https://docs.google.com/spreadsheets/d/12MNpRn0Krk3WVRFoj37bST2fXBGnomeQ-DQ4N9VA-7c/gviz/tq?tqx=out:csv&sheet=%E3%82%A2%E3%82%B8%E3%83%91%E3%83%A9',
    'road': 'https://docs.google.com/spreadsheets/d/12MNpRn0Krk3WVRFoj37bST2fXBGnomeQ-DQ4N9VA-7c/gviz/tq?tqx=out:csv&sheet=%E9%81%93%E8%B7%AF%E6%83%85%E5%A0%B1',
}
EVENT_SHEET_SOURCES = [source for source in SHEET_URLS if source != "road"]


def load_google_sheet_csv(url, default_source):
    events = []

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    response.encoding = "utf-8-sig"

    reader = csv.DictReader(io.StringIO(response.text))

    for row in reader:
        event = {field: (row.get(field) or "").strip() for field in COMMON_COLUMNS}

        if event["status"] == "skip":
            continue

        if not event["title"]:
            continue

        if not event["time"] and not event["end_time"]:
            event["time"] = "未定"

        if not event["source"]:
            event["source"] = default_source

        events.append(event)

    return events


def load_all_google_sheet_events():
    events = []

    for source in EVENT_SHEET_SOURCES:
        url = SHEET_URLS.get(source)
        if not url:
            continue

        events += load_google_sheet_csv(url, source)

    return events

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _spreadsheet_id_from_url(url):
    path = urlparse(url).path
    if "/d/" not in path:
        return ""

    return path.split("/d/", 1)[1].split("/", 1)[0]


def _default_spreadsheet_id():
    return os.environ.get("GOOGLE_SHEET_ID") or _spreadsheet_id_from_url(SHEET_URLS["misonoza"])


def _read_csv_rows(csv_path):
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.reader(csv_file))


def _rows_to_event_dicts(rows):
    if not rows:
        return []

    header = rows[0]
    indexes = {name: index for index, name in enumerate(header)}
    events = []

    for values in rows[1:]:
        if not any(values):
            continue

        event = {}
        for column in COMMON_COLUMNS:
            index = indexes.get(column)
            event[column] = values[index].strip() if index is not None and index < len(values) else ""

        events.append(event)

    return events


def _rows_to_dicts(rows, columns):
    if not rows:
        return []

    header = rows[0]
    indexes = {name: index for index, name in enumerate(header)}
    records = []

    for values in rows[1:]:
        if not any(values):
            continue

        record = {}
        for column in columns:
            index = indexes.get(column)
            record[column] = values[index].strip() if index is not None and index < len(values) else ""

        records.append(record)

    return records


def _road_key(record):
    return tuple(record.get(column, "") for column in ROAD_KEY_COLUMNS)


def _event_key(event):
    return (
        event.get("date", ""),
        event.get("time", ""),
        event.get("venue", ""),
        event.get("title", ""),
        event.get("url", ""),
    )


def _is_manual_sheet_row(event):
    return event.get("status", "") == "manual" or "手動補完" in event.get("note", "")


def _merge_sheet_manual_rows(csv_events, sheet_events):
    merged_events = list(csv_events)
    by_key = {_event_key(event): event for event in merged_events}

    for sheet_event in sheet_events:
        if not _is_manual_sheet_row(sheet_event):
            continue

        key = _event_key(sheet_event)
        csv_event = by_key.get(key)
        if csv_event is None:
            merged_events.append(sheet_event)
            by_key[key] = sheet_event
            continue

        if "手動補完" in sheet_event.get("note", ""):
            csv_event["note"] = sheet_event["note"]

    return merged_events


def _event_dicts_to_rows(events):
    return [COMMON_COLUMNS] + [
        [event.get(column, "") for column in COMMON_COLUMNS]
        for event in events
    ]


def _write_csv_rows(csv_path, rows):
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerows(rows)


def _read_sheet_rows(service, spreadsheet_id, sheet_name):
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=sheet_name,
    ).execute()
    return result.get("values", [])


def _sheets_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Sheets sync requires google-api-python-client and google-auth"
        ) from exc

    base_dir = Path(__file__).resolve().parents[2]
    credentials_path = base_dir / "credentials" / "credentials.json"
    token_path = base_dir / "credentials" / "token.json"

    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SHEETS_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise RuntimeError(f"OAuth credentials not found: {credentials_path}")

            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),
                SHEETS_SCOPES,
            )
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("sheets", "v4", credentials=creds)

def _sheet_exists(service, spreadsheet_id, sheet_name):
    result = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties.title",
    ).execute()
    sheet_names = {
        sheet.get("properties", {}).get("title", "")
        for sheet in result.get("sheets", [])
    }
    return sheet_name in sheet_names


def _create_sheet(service, spreadsheet_id, sheet_name):
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": sheet_name,
                        }
                    }
                }
            ]
        },
    ).execute()


def _road_records_to_rows(csv_records, sheet_records):
    previous_by_key = {_road_key(record): record for record in sheet_records}
    values = [ROAD_COLUMNS]

    for csv_record in csv_records:
        merged = {column: csv_record.get(column, "") for column in ROAD_COLUMNS}
        previous = previous_by_key.get(_road_key(merged))

        if previous:
            for column in ROAD_EXTRA_COLUMNS:
                merged[column] = previous.get(column, "")

        values.append([merged.get(column, "") for column in ROAD_COLUMNS])

    return values


def _road_records_to_values(records):
    return [ROAD_COLUMNS] + [
        [record.get(column, "") for column in ROAD_COLUMNS]
        for record in records
    ]


def _parse_road_date(value):
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return None


def _ensure_road_sheet_header(service, spreadsheet_id, sheet_name, rows):
    if rows and rows[0] == ROAD_COLUMNS:
        return

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body={"values": [ROAD_COLUMNS]},
    ).execute()


def archive_old_road_rows(target_date=None, csv_path="csv_events/road.csv"):
    if not Path(csv_path).exists():
        print(f"道路情報CSVなし: {csv_path}")
        return {"archived": 0, "duplicate_skipped": 0, "deleted": 0}

    if target_date is None:
        target_date = date.today()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    spreadsheet_id = _default_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError("Google spreadsheet ID is not configured")

    service = _sheets_service()

    for sheet_name in (ROAD_SHEET_NAME, ROAD_HISTORY_SHEET_NAME):
        if not _sheet_exists(service, spreadsheet_id, sheet_name):
            raise RuntimeError(f"Google sheet not found: {sheet_name}")

    current_rows = _read_sheet_rows(service, spreadsheet_id, ROAD_SHEET_NAME)
    history_rows = _read_sheet_rows(service, spreadsheet_id, ROAD_HISTORY_SHEET_NAME)

    _ensure_road_sheet_header(service, spreadsheet_id, ROAD_SHEET_NAME, current_rows)
    _ensure_road_sheet_header(service, spreadsheet_id, ROAD_HISTORY_SHEET_NAME, history_rows)

    current_records = _rows_to_dicts(current_rows, ROAD_COLUMNS)
    history_records = _rows_to_dicts(history_rows, ROAD_COLUMNS)
    history_keys = {_road_key(record) for record in history_records}

    remaining_records = []
    append_records = []
    old_count = 0
    duplicate_count = 0

    for record in current_records:
        row_date = _parse_road_date(record.get("date"))

        if row_date is None or row_date >= target_date:
            remaining_records.append(record)
            continue

        old_count += 1
        key = _road_key(record)
        if key in history_keys:
            duplicate_count += 1
            continue

        append_records.append(record)
        history_keys.add(key)

    if append_records:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=ROAD_HISTORY_SHEET_NAME,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={
                "values": [
                    [record.get(column, "") for column in ROAD_COLUMNS]
                    for record in append_records
                ]
            },
        ).execute()

    if old_count:
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=ROAD_SHEET_NAME,
            body={},
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{ROAD_SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": _road_records_to_values(remaining_records)},
        ).execute()

    print(f"道路情報過去ログ移動: {len(append_records)}件")
    print(f"重複スキップ: {duplicate_count}件")
    print(f"道路情報シート削除: {old_count}件")

    return {
        "archived": len(append_records),
        "duplicate_skipped": duplicate_count,
        "deleted": old_count,
    }


def sync_road_csv_to_sheet(csv_path="csv_events/road.csv"):
    path = Path(csv_path)
    if not path.exists():
        print(f"道路情報CSVなし: {path}")
        return False

    rows = _read_csv_rows(path)
    csv_records = _rows_to_dicts(rows, ROAD_COLUMNS)
    spreadsheet_id = _default_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError("Google spreadsheet ID is not configured")

    service = _sheets_service()

    if not _sheet_exists(service, spreadsheet_id, ROAD_SHEET_NAME):
        raise RuntimeError(f"Google sheet not found: {ROAD_SHEET_NAME}")

    if not _sheet_exists(service, spreadsheet_id, ROAD_HISTORY_SHEET_NAME):
        print(f"道路情報過去シートなし: {ROAD_HISTORY_SHEET_NAME}")

    sheet_rows = _read_sheet_rows(service, spreadsheet_id, ROAD_SHEET_NAME)
    sheet_records = _rows_to_dicts(sheet_rows, ROAD_COLUMNS)
    values = _road_records_to_rows(csv_records, sheet_records)

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=ROAD_SHEET_NAME,
        body={},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{ROAD_SHEET_NAME}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    print(f"道路情報Google Sheets同期完了: {len(csv_records)}件")
    return True


def sync_csv_to_sheet(csv_path: str, sheet_name: str) -> None:
    rows = _read_csv_rows(csv_path)
    spreadsheet_id = _default_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError("Google spreadsheet ID is not configured")

    service = _sheets_service()
    sheet_rows = _read_sheet_rows(service, spreadsheet_id, sheet_name)
    csv_events = _rows_to_event_dicts(rows)
    sheet_events = _rows_to_event_dicts(sheet_rows)
    merged_events = _merge_sheet_manual_rows(csv_events, sheet_events)
    values = _event_dicts_to_rows(merged_events)
    _write_csv_rows(csv_path, values)
    range_name = f"{sheet_name}!A1"

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=sheet_name,
        body={},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def sync_simple_csv_to_sheet(csv_path, sheet_name, label=None):
    path = Path(csv_path)
    label = label or sheet_name

    if not path.exists():
        print(f"{label}CSVなし: {path}")
        return False

    values = _read_csv_rows(path)
    if not values:
        print(f"{label}CSV空: {path}")
        return False

    spreadsheet_id = _default_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError("Google spreadsheet ID is not configured")

    service = _sheets_service()

    if not _sheet_exists(service, spreadsheet_id, sheet_name):
        _create_sheet(service, spreadsheet_id, sheet_name)
        print(f"{label}Google Sheetsシート作成: {sheet_name}")

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

    print(f"{label}Google Sheets同期完了: {max(len(values) - 1, 0)}件")
    return True


def sync_cruise_csv_to_sheet(csv_path="csv_events/cruise.csv"):
    return sync_simple_csv_to_sheet(csv_path, CRUISE_SHEET_NAME, "クルーズ船")


def sync_asia_csv_to_sheet(csv_path="csv_events/asia.csv"):
    return sync_simple_csv_to_sheet(csv_path, ASIA_SHEET_NAME, "アジア大会")

def _rows_to_values_with_header(header, records):
    return [header] + records


def cleanup_old_simple_sheet_rows(sheet_name, label, target_date=None):
    if target_date is None:
        target_date = date.today()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    spreadsheet_id = _default_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError("Google spreadsheet ID is not configured")

    service = _sheets_service()

    if not _sheet_exists(service, spreadsheet_id, sheet_name):
        print(f"{label}シートなし: {sheet_name}")
        return {"deleted": 0}

    rows = _read_sheet_rows(service, spreadsheet_id, sheet_name)
    if not rows:
        print(f"{label}シート削除: 0件")
        return {"deleted": 0}

    header = rows[0]
    try:
        date_index = header.index("date")
    except ValueError:
        print(f"{label}シート削除: 0件")
        return {"deleted": 0}

    remaining = []
    deleted = 0

    for values in rows[1:]:
        row_date = _parse_road_date(values[date_index] if date_index < len(values) else "")
        if row_date is not None and row_date < target_date:
            deleted += 1
            continue

        remaining.append(values)

    if deleted:
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=sheet_name,
            body={},
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": _rows_to_values_with_header(header, remaining)},
        ).execute()

    print(f"{label}シート削除: {deleted}件")
    return {"deleted": deleted}


def cleanup_old_cruise_rows(target_date=None):
    return cleanup_old_simple_sheet_rows(CRUISE_SHEET_NAME, "クルーズ船", target_date)


def cleanup_old_asia_rows(target_date=None):
    return cleanup_old_simple_sheet_rows(ASIA_SHEET_NAME, "アジア大会", target_date)

