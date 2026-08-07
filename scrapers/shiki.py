from __future__ import annotations

import csv
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
import requests

from tools.common.scraper_health import (
    build_admin_warning_message,
    check_count,
    check_structure_hash,
    has_major_warning,
    load_health_state,
    save_health_state,
)


URL = "https://www.shiki.jp/stage_schedule/?aj=0&rid=0019&ggc=0977"
API_BASE_URL = "https://www.shiki.jp/api_stage_schedule"
MONTHS_API_URL = f"{API_BASE_URL}/stageYmList"
CALENDAR_API_URL = f"{API_BASE_URL}/calendar"
API_PARAMS = {"repertoire_id": "0019", "geki_grp_code": "0977"}
TITLE = "オペラ座の怪人"
VENUE = "ＭＴＧ名古屋四季劇場"
CATEGORY = "ミュージカル"
SOURCE = "劇団四季"
DURATION_MINUTES = 160
DEFAULT_CSV_PATH = Path(__file__).resolve().parents[1] / "csv_events" / "shiki.csv"
DEBUG_DIR = Path(__file__).resolve().parents[1] / "data" / "debug" / "scrapers" / "shiki"
MIN_VALID_EVENTS = 2
MAX_DROP_RATIO = 0.5
MAX_FETCH_ATTEMPTS = 2
SEAT_MARKS = {
    "sufficient": "◎",
    "seat": "○",
    "unsoldSeat": "△",
    "justRest": "▽",
    "soldOut": "×",
}
_HTTP_SESSION = requests.Session()

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


def _make_event(
    event_date: str,
    start_time: str,
    availability_mark: str,
    month: str | None,
    *,
    note: str = "",
    title: str = TITLE,
    venue: str = VENUE,
) -> dict:
    return {
        "date": event_date,
        "time": start_time,
        "end_time": _end_time(start_time) if start_time else "",
        "venue": venue,
        "title": title,
        "source": SOURCE,
        "status": "confirmed",
        "note": note,
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


def _api_event_candidates(
    calendars: list[tuple[str, dict]],
    *,
    today: date,
    requested_month: str | None,
    title: str,
    venue: str,
) -> tuple[list[dict], dict[str, int], list[dict]]:
    events: list[dict] = []
    skips: list[dict] = []
    raw_candidates = 0
    parsed_events = 0
    month_prefix = _date_prefix(requested_month)

    for year_month, payload in calendars:
        results = payload.get("results") if isinstance(payload, dict) else None
        days = results.get("calendar") if isinstance(results, dict) else None
        if not isinstance(days, list):
            skips.append({"reason": "calendar_missing", "month": year_month})
            continue

        for day in days:
            if not isinstance(day, dict):
                skips.append({"reason": "invalid_day", "month": year_month})
                continue
            ymd = str(day.get("koen_day") or day.get("id") or "")
            # The API includes leading/trailing days from adjacent calendar grids.
            if not re.fullmatch(r"\d{8}", ymd) or not ymd.startswith(year_month):
                continue
            event_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
            try:
                event_day = datetime.strptime(event_date, "%Y-%m-%d").date()
            except ValueError:
                skips.append({"reason": "date_parse_failed", "value": ymd})
                continue
            if event_day < today:
                continue
            if month_prefix and not event_date.startswith(month_prefix):
                continue

            daily_note = str(day.get("daily_disp_str") or "").strip()
            if str(day.get("daily_disp_flg") or "") == "1" and daily_note:
                raw_candidates += 1
                if "貸切" in daily_note:
                    events.append(
                        _make_event(
                            event_date,
                            "",
                            "",
                            requested_month or year_month,
                            note=daily_note,
                            title=title,
                            venue=venue,
                        )
                    )
                    parsed_events += 1
                else:
                    skips.append(
                        {
                            "reason": "daily_display_without_time",
                            "date": event_date,
                            "value": daily_note,
                        }
                    )
                continue

            for period in ("mor", "aft"):
                slot = day.get(period)
                if not isinstance(slot, dict):
                    continue
                start_time = _start_time_from_text(str(slot.get("time") or ""))
                note = str(slot.get("dispstr") or "").strip()
                if not start_time and not note:
                    continue
                raw_candidates += 1
                if not start_time and "貸切" not in note:
                    skips.append(
                        {
                            "reason": "time_missing",
                            "date": event_date,
                            "period": period,
                            "value": note,
                        }
                    )
                    continue
                events.append(
                    _make_event(
                        event_date,
                        start_time,
                        SEAT_MARKS.get(str(slot.get("seat_rest") or ""), ""),
                        requested_month or year_month,
                        note=note if "貸切" in note else "",
                        title=title,
                        venue=venue,
                    )
                )
                parsed_events += 1

    nagoya_events = events if venue == VENUE else []
    if venue != VENUE and events:
        skips.append(
            {
                "reason": "venue_not_nagoya",
                "venue": venue,
                "count": len(events),
            }
        )
    deduped = dedupe_events(nagoya_events)
    metrics = {
        "raw_candidates": raw_candidates,
        "detail_urls": 0,
        "detail_success": 0,
        "parsed_events": parsed_events,
        "nagoya_events": len(nagoya_events),
        "filtered_events": len(deduped),
    }
    return deduped, metrics, skips


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


def _canonical_api_structure(calendars: list[tuple[str, dict]]) -> str:
    day_keys: set[str] = set()
    slot_keys: set[str] = set()
    result_keys: set[str] = set()
    for _month, payload in calendars:
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, dict):
            continue
        result_keys.update(str(key) for key in results)
        days = results.get("calendar")
        if not isinstance(days, list):
            continue
        for day in days:
            if not isinstance(day, dict):
                continue
            day_keys.update(str(key) for key in day)
            for period in ("mor", "aft"):
                slot = day.get(period)
                if isinstance(slot, dict):
                    slot_keys.update(str(key) for key in slot)
    return json.dumps(
        {
            "result_keys": sorted(result_keys),
            "day_keys": sorted(day_keys),
            "slot_keys": sorted(slot_keys),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _shiki_health_messages(
    events: list[dict], calendars: list[tuple[str, dict]]
) -> list[str]:
    # Remove the legacy rendered-DOM selector so the dashboard reads the API
    # event count from the counts section instead of a stale selector count.
    state = load_health_state("shiki")
    state.pop("selectors", None)
    save_health_state("shiki", state)
    messages: list[str] = []
    messages.extend(
        check_count(
            "shiki",
            "events",
            "events",
            len(events),
            min_count=1,
            drop_ratio=MAX_DROP_RATIO,
        )
    )
    messages.extend(
        check_structure_hash(
            "shiki",
            _canonical_api_structure(calendars),
            "schedule_api",
        )
    )
    if has_major_warning(messages, "shiki"):
        messages.append(
            build_admin_warning_message(
                "劇団四季",
                {"イベント": len(events)},
            )
        )
    return messages


def _fetch(url: str, *, params: dict | None = None):
    last_response = None
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            response = _HTTP_SESSION.get(
                url,
                params=params,
                headers={
                    "User-Agent": "nagoya-event-shiki/1.0",
                    "Referer": URL,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            logging.error(
                "shiki_http_status endpoint=%s attempt=%s status=error error=%s",
                url,
                attempt,
                exc,
            )
            if attempt < MAX_FETCH_ATTEMPTS:
                time.sleep(0.2)
            continue
        last_response = response
        logging.info(
            "shiki_http_status endpoint=%s attempt=%s status=%s",
            url,
            attempt,
            response.status_code,
        )
        logging.info("shiki_final_url endpoint=%s url=%s", url, response.url)
        logging.info(
            "shiki_html_length endpoint=%s bytes=%s", url, len(response.content)
        )
        logging.info(
            "shiki_redirect_count endpoint=%s count=%s", url, len(response.history)
        )
        if response.status_code == 200:
            return response
        if attempt < MAX_FETCH_ATTEMPTS:
            time.sleep(0.2)
    return last_response


def _save_debug(html: str, diagnostics: dict) -> tuple[Path, Path]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    html_path = DEBUG_DIR / f"shiki_{timestamp}.html"
    json_path = DEBUG_DIR / f"shiki_{timestamp}.json"
    html_path.write_text(html or "", encoding="utf-8")
    payload = dict(diagnostics)
    payload["saved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    payload["html_path"] = str(html_path)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return html_path, json_path


def _json_response(response, endpoint: str, diagnostics: dict):
    if response is None or response.status_code != 200:
        diagnostics.setdefault("failures", []).append(
            {
                "endpoint": endpoint,
                "reason": "http_error",
                "status": getattr(response, "status_code", None),
            }
        )
        return None
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        diagnostics.setdefault("failures", []).append(
            {"endpoint": endpoint, "reason": "invalid_json"}
        )
        return None
    return payload if isinstance(payload, dict) else None


def scrape_shiki_with_health(
    page, today=None, month: str | None = None
) -> tuple[list[dict], list[str]]:
    del page  # The official JSON API is primary; browser rendering is unnecessary.
    target = _target_date(today)
    diagnostics: dict = {
        "source_url": URL,
        "months_api_url": MONTHS_API_URL,
        "calendar_api_url": CALENDAR_API_URL,
        "target_date": target.isoformat(),
        "requested_month": month or "",
        "failures": [],
    }

    page_response = _fetch(URL)
    html = page_response.text if page_response is not None else ""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one("h1.stageTitle")
    venue_tag = soup.select_one("p.stageInfo strong")
    title = (title_tag.get_text(" ", strip=True) if title_tag else TITLE).replace(
        "　名古屋", ""
    )
    venue = venue_tag.get_text(" ", strip=True) if venue_tag else ""
    diagnostics["page"] = {
        "status": getattr(page_response, "status_code", None),
        "final_url": getattr(page_response, "url", ""),
        "html_length": len(html.encode("utf-8")),
        "redirect_count": len(getattr(page_response, "history", [])),
        "title": title,
        "venue": venue,
        "legacy_selector_count": len(
            soup.select(
                "[id^='mor'], [id^='aft'], [id^='eve'], "
                "table tbody tr td .cal-time"
            )
        ),
    }

    months_response = _fetch(MONTHS_API_URL, params=API_PARAMS)
    months_payload = _json_response(months_response, "stageYmList", diagnostics)
    month_records = months_payload.get("results") if months_payload else None
    if not isinstance(month_records, list):
        month_records = []

    requested_ym = month.replace("-", "") if month else ""
    months = []
    for record in month_records:
        if not isinstance(record, dict):
            continue
        year_month = str(record.get("id") or "")
        if not re.fullmatch(r"\d{6}", year_month):
            continue
        if requested_ym and year_month != requested_ym:
            continue
        if not requested_ym and str(record.get("past") or "") == "1":
            continue
        months.append(year_month)
    if requested_ym and requested_ym not in months:
        months.append(requested_ym)

    calendars: list[tuple[str, dict]] = []
    for year_month in months:
        params = dict(API_PARAMS)
        params["target_ym"] = year_month
        response = _fetch(CALENDAR_API_URL, params=params)
        payload = _json_response(response, f"calendar:{year_month}", diagnostics)
        if payload is not None:
            calendars.append((year_month, payload))

    events, metrics, skips = _api_event_candidates(
        calendars,
        today=target,
        requested_month=month,
        title=title or TITLE,
        venue=venue,
    )
    diagnostics.update(metrics)
    diagnostics["months"] = months
    diagnostics["calendar_success"] = len(calendars)
    diagnostics["skip_reasons"] = skips
    for key in (
        "raw_candidates",
        "detail_urls",
        "detail_success",
        "parsed_events",
        "nagoya_events",
        "filtered_events",
    ):
        logging.info("shiki_%s=%s", key, metrics[key])
    for skip in skips:
        logging.info("shiki_skip_reason %s", json.dumps(skip, ensure_ascii=False))
    if not skips:
        logging.info("shiki_skip_reason count=0")

    invalid_reasons = []
    if page_response is None or page_response.status_code != 200:
        invalid_reasons.append("source_page_fetch_failed")
    if venue != VENUE:
        invalid_reasons.append("nagoya_venue_not_confirmed")
    if diagnostics["failures"]:
        invalid_reasons.append("api_fetch_or_parse_failed")
    if len(events) < MIN_VALID_EVENTS:
        invalid_reasons.append("extremely_low_event_count")

    messages = _shiki_health_messages(events, calendars)
    if invalid_reasons:
        diagnostics["invalid_reasons"] = invalid_reasons
        html_path, json_path = _save_debug(html, diagnostics)
        logging.warning(
            "shiki_skip_reason reason=invalid_result reasons=%s saved_html=%s saved_json=%s",
            ",".join(invalid_reasons),
            html_path,
            json_path,
        )
        messages.append(
            "scraper_health_warning: shiki invalid result "
            f"reasons={','.join(invalid_reasons)} saved_html={html_path} "
            f"saved_json={json_path}"
        )
        if not has_major_warning(messages, "shiki"):
            messages.append(
                build_admin_warning_message(
                    "劇団四季",
                    {"イベント": len(events)},
                    detail="取得異常のため既存CSVを保持します。",
                )
            )
        return [], messages

    return events, messages


def scrape_shiki(page, today=None, month: str | None = None) -> list[dict]:
    events, _messages = scrape_shiki_with_health(page, today=today, month=month)
    return events


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


def _future_auto_count(rows: list[dict], today=None) -> int:
    target = _target_date(today)
    count = 0
    for row in rows:
        if not _is_shiki_auto_row(row) or row.get("status") == "inactive":
            continue
        try:
            row_day = datetime.strptime(row.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if row_day >= target:
            count += 1
    return count


def write_shiki_csv(
    events: list[dict], output_path=DEFAULT_CSV_PATH, today=None
) -> bool:
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    existing_rows = _load_existing_csv(output_file)
    previous_count = _future_auto_count(existing_rows, today=today)
    current_count = len(dedupe_events(events))
    invalid_reasons = []
    if current_count < MIN_VALID_EVENTS:
        invalid_reasons.append("extremely_low_event_count")
    if previous_count > 0 and current_count <= previous_count * MAX_DROP_RATIO:
        invalid_reasons.append("event_count_dropped_50_percent_or_more")
    if invalid_reasons:
        logging.warning(
            "shiki_skip_reason reason=csv_write_blocked previous=%s current=%s reasons=%s",
            previous_count,
            current_count,
            ",".join(invalid_reasons),
        )
        return False

    merged_events = merge_existing_rows(events, existing_rows, today=today)

    with output_file.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=SHIKI_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(merged_events)
    return True
