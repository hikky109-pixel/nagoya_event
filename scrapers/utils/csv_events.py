import csv
from pathlib import Path
from datetime import datetime, date


BASE_DIR = Path(__file__).resolve().parents[2]
CSV_DIR = BASE_DIR / "csv_events"
LOG_DIR = BASE_DIR / "logs"


COMMON_COLUMNS = [
    "date",
    "time",
    "end_time",
    "venue",
    "title",
    "source",
    "status",
    "note",
    "url",
]


def ensure_dirs():
    CSV_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)


def load_csv_events(filename, default_source):
    ensure_dirs()

    path = CSV_DIR / filename
    events = []

    if not path.exists():
        return events

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            status = row.get("status", "").strip()

            if status in ("skip", "inactive"):
                continue

            event = {
                "date": row.get("date", "").strip(),
                "time": row.get("time", "").strip(),
                "end_time": row.get("end_time", "").strip(),
                "venue": row.get("venue", "").strip(),
                "title": row.get("title", "").strip(),
                "source": row.get("source", "").strip() or default_source,
                "status": status or "manual",
                "note": row.get("note", "").strip(),
                "url": row.get("url", "").strip(),
            }

            if not event["time"] and not event["end_time"]:
                event["time"] = "未定"

            if event["date"] and event["title"]:
                events.append(event)

    return events


def save_csv_events(filename, events):
    ensure_dirs()

    path = CSV_DIR / filename

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COMMON_COLUMNS)
        writer.writeheader()

        for event in events:
            writer.writerow({
                "date": event.get("date", ""),
                "time": event.get("time", ""),
                "end_time": event.get("end_time", ""),
                "venue": event.get("venue", ""),
                "title": event.get("title", ""),
                "source": event.get("source", ""),
                "status": event.get("status", ""),
                "note": event.get("note", ""),
                "url": event.get("url", ""),
            })


def load_all_manual_csv_events():
    events = []

    events += load_csv_events("misonoza.csv", "misonoza")
    events += load_csv_events("shiki.csv", "shiki")
    events += load_csv_events("spot.csv", "spot")
    events += load_csv_events("ajipara.csv", "ajipara")

    return events


def filter_events_by_date(events, target_date):
    if isinstance(target_date, datetime):
        target_date = target_date.date()

    if isinstance(target_date, date):
        target_strings = {
            target_date.strftime("%Y/%m/%d"),
            target_date.strftime("%Y-%m-%d"),
        }
    else:
        target_text = str(target_date)
        target_strings = {
            target_text,
            target_text.replace("/", "-"),
            target_text.replace("-", "/"),
        }

    return [
        event for event in events
        if event.get("date") in target_strings
    ]


def save_daily_debug_log(events, target_date=None):
    if target_date is None:
        target_date = datetime.now()

    ensure_dirs()

    if isinstance(target_date, datetime):
        target_date = target_date.date()

    today_path = LOG_DIR / "today.csv"
    yesterday_path = LOG_DIR / "yesterday.csv"

    if today_path.exists():
        if yesterday_path.exists():
            yesterday_path.unlink()
        today_path.rename(yesterday_path)

    with open(today_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COMMON_COLUMNS)
        writer.writeheader()

        for event in events:
            writer.writerow({
                "date": event.get("date", ""),
                "time": event.get("time", ""),
                "end_time": event.get("end_time", ""),
                "venue": event.get("venue", ""),
                "title": event.get("title", ""),
                "source": event.get("source", ""),
                "status": event.get("status", ""),
                "note": event.get("note", ""),
                "url": event.get("url", ""),
            })