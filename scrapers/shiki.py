from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup


URL = "https://www.shiki.jp/stage_schedule/?aj=0&rid=0019&ggc=0977"
TITLE = "オペラ座の怪人"
VENUE = "ＭＴＧ名古屋四季劇場"
CATEGORY = "ミュージカル"
SOURCE = "劇団四季"
DURATION_MINUTES = 160
DEFAULT_CSV_PATH = Path(__file__).resolve().parents[1] / "csv_events" / "shiki.csv"

SHIKI_CSV_COLUMNS = [
    "date",
    "time",
    "end_time",
    "venue",
    "title",
    "source",
    "status",
    "note",
    "url",
    "category",
    "duration_minutes",
    "availability_mark",
]


def _target_date(today) -> date:
    if today is None:
        return datetime.now().date()
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    return datetime.strptime(str(today), "%Y-%m-%d").date()


def _start_time_from_text(text: str) -> str:
    match = re.search(r"\d{1,2}:\d{2}", text)
    return match.group(0) if match else ""


def _end_time(start_time: str) -> str:
    start = datetime.strptime(start_time, "%H:%M")
    return (start + timedelta(minutes=DURATION_MINUTES)).strftime("%H:%M")


def _month_fragment(month: str | None) -> str:
    if not month:
        return ""

    month = month.replace("-", "")
    if not re.fullmatch(r"\d{6}", month):
        raise ValueError("month must be YYYYMM or YYYY-MM")

    return f"#{month}"


def _date_prefix(month: str | None) -> str:
    if not month:
        return ""

    month = month.replace("-", "")
    return f"{month[:4]}-{month[4:6]}"


def _event_key(event: dict) -> tuple:
    return (
        event.get("source", ""),
        event.get("venue", ""),
        event.get("title", ""),
        event.get("date", ""),
        event.get("time", ""),
    )


def _make_event(event_date: str, start_time: str, availability_mark: str, month: str | None) -> dict:
    return {
        "date": event_date,
        "time": start_time,
        "end_time": _end_time(start_time),
        "venue": VENUE,
        "title": TITLE,
        "source": SOURCE,
        "status": "confirmed",
        "note": "",
        "url": URL + _month_fragment(month),
        "category": CATEGORY,
        "duration_minutes": str(DURATION_MINUTES),
        "availability_mark": availability_mark,
    }


def dedupe_events(events: list[dict]) -> list[dict]:
    unique_events = []
    seen = {}

    for event in events:
        key = _event_key(event)
        if key in seen:
            existing = seen[key]
            for field, value in event.items():
                if value and not existing.get(field):
                    existing[field] = value
            continue

        seen[key] = event
        unique_events.append(event)

    return unique_events


def _year_by_month_from_ids(soup: BeautifulSoup) -> dict[int, int]:
    years = {}

    for tag in soup.select("[id]"):
        id_match = re.fullmatch(r"(mor|aft|eve)(\d{8})", tag.get("id", ""))
        if not id_match:
            continue

        ymd = id_match.group(2)
        years[int(ymd[4:6])] = int(ymd[:4])

    return years


def _year_for_month(month_number: int, today: date, month: str | None, years_by_month: dict[int, int]) -> int:
    if month:
        return int(month.replace("-", "")[:4])

    if month_number in years_by_month:
        return years_by_month[month_number]

    if month_number < today.month:
        return today.year + 1

    return today.year


def _events_from_calendar_tables(
    soup: BeautifulSoup,
    today: date,
    month: str | None,
    month_prefix: str,
) -> list[dict]:
    events = []
    years_by_month = _year_by_month_from_ids(soup)

    for table in soup.select("table"):
        period_month = table.select_one("tr.period th .number")
        if not period_month:
            continue

        month_text = period_month.get_text("", strip=True)
        if not month_text.isdigit():
            continue

        month_number = int(month_text)
        year = _year_for_month(month_number, today, month, years_by_month)

        for row in table.select("tbody tr"):
            day_tag = row.select_one("th .day")
            if not day_tag:
                continue

            day_text = day_tag.get_text("", strip=True)
            if not day_text.isdigit():
                continue

            event_date = f"{year:04d}-{month_number:02d}-{int(day_text):02d}"
            event_day = datetime.strptime(event_date, "%Y-%m-%d").date()

            if event_day < today:
                continue
            if month_prefix and not event_date.startswith(month_prefix):
                continue

            for cell in row.select("td"):
                time_tag = cell.select_one(".cal-time")
                if not time_tag:
                    continue

                start_time = _start_time_from_text(time_tag.get_text(" ", strip=True))
                if not start_time:
                    continue

                mark_tag = cell.select_one(".cal-mark span")
                availability_mark = mark_tag.get_text("", strip=True) if mark_tag else ""
                events.append(_make_event(event_date, start_time, availability_mark, month))

    return events


def parse_shiki_events(html: str, today=None, month: str | None = None) -> list[dict]:
    target = _target_date(today)
    month_prefix = _date_prefix(month)
    soup = BeautifulSoup(html, "html.parser")
    events = []

    for tag in soup.select("[id]"):
        id_match = re.fullmatch(r"(mor|aft|eve)(\d{8})", tag.get("id", ""))
        if not id_match:
            continue

        ymd = id_match.group(2)
        event_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
        event_day = datetime.strptime(event_date, "%Y-%m-%d").date()

        if event_day < target:
            continue
        if month_prefix and not event_date.startswith(month_prefix):
            continue

        time_tag = tag.select_one(".cal-time, .time")
        if not time_tag:
            continue

        start_time = _start_time_from_text(time_tag.get_text(" ", strip=True))
        if not start_time:
            continue

        mark_tag = tag.select_one(".cal-mark, .mark")
        availability_mark = mark_tag.get_text("", strip=True) if mark_tag else ""

        events.append(_make_event(event_date, start_time, availability_mark, month))

    events += _events_from_calendar_tables(soup, target, month, month_prefix)
    return dedupe_events(events)


def scrape_shiki(page, today=None, month: str | None = None) -> list[dict]:
    page.goto(URL + _month_fragment(month), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("[id^='mor'], [id^='aft'], [id^='eve'], .cal-time", state="attached", timeout=60000)
    page.wait_for_timeout(1000)
    return parse_shiki_events(page.content(), today=today, month=month)


def _load_existing_csv(output_file: Path) -> list[dict]:
    if not output_file.exists():
        return []

    with output_file.open(newline="", encoding="utf-8-sig") as csv_file:
        return [dict(row) for row in csv.DictReader(csv_file)]


def _normalize_csv_row(event: dict) -> dict:
    return {column: event.get(column, "") for column in SHIKI_CSV_COLUMNS}


def _is_shiki_auto_row(row: dict) -> bool:
    return (
        row.get("source", "") == SOURCE
        and row.get("venue", "") == VENUE
        and row.get("title", "") == TITLE
        and row.get("status", "") != "manual"
    )


def merge_existing_rows(scraped_events: list[dict], existing_rows: list[dict], today=None) -> list[dict]:
    target = _target_date(today)
    merged = [_normalize_csv_row(event) for event in dedupe_events(scraped_events)]
    by_key = {_event_key(event): event for event in merged}

    for row in existing_rows:
        normalized = _normalize_csv_row(row)
        key = _event_key(normalized)

        if key in by_key:
            if row.get("note") and not by_key[key].get("note"):
                by_key[key]["note"] = row["note"]
            continue

        if not _is_shiki_auto_row(row):
            merged.append(normalized)
            continue

        row_date = row.get("date", "")
        try:
            row_day = datetime.strptime(row_date, "%Y-%m-%d").date()
        except ValueError:
            row_day = None

        if row_day and row_day >= target:
            normalized["status"] = "inactive"
            merged.append(normalized)
        elif row_day:
            merged.append(normalized)

    return sorted(dedupe_events(merged), key=lambda event: (event.get("date", ""), event.get("time", "")))


def write_shiki_csv(events: list[dict], output_path=DEFAULT_CSV_PATH, today=None) -> None:
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    existing_rows = _load_existing_csv(output_file)
    merged_events = merge_existing_rows(events, existing_rows, today=today)

    with output_file.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=SHIKI_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(merged_events)
