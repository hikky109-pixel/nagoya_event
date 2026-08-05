from bs4 import BeautifulSoup
from datetime import datetime
import json
import logging
from pathlib import Path
import re
from urllib.parse import urljoin

from tools.common.scraper_health import (
    build_admin_warning_message,
    check_selector_count,
    check_structure_hash,
    has_major_warning,
)

URL = "https://www.kyodotokai.co.jp/events"
CALENDAR_URL = f"{URL}/calendor"
INDEX_URLS = [f"{URL}/index/{index}/" for index in range(1, 10)]
ROOT = Path(__file__).resolve().parents[1]
DEBUG_DIR = ROOT / "data" / "debug" / "scrapers" / "kyodo_tokai"
EVENT_SELECTOR = "div.eventlistbox dl"
CALENDAR_SELECTOR = "div.calendarbox table tr"
DETAIL_SELECTOR = "div.detailbox"
MAX_FETCH_ATTEMPTS = 2

WANTED_VENUES = [
    "IGアリーナ",
    "日本ガイシホール",
    "愛知県芸術劇場",
    "Niterra日本特殊陶業市民会館",
    "岡谷鋼機名古屋公会堂",
    "Zepp Nagoya",
    "DIAMOND HALL",
    "NAGOYA JAMMIN",
    "NAGOYA JAMMIN’",
    "バンテリンドーム",
]

def _kyodo_health_messages(soup):
    messages = []
    messages.extend(
        check_selector_count(
            "kyodo_tokai",
            soup,
            CALENDAR_SELECTOR,
            "calendar",
            min_count=1,
            drop_ratio=0.8,
        )
    )
    fragment_nodes = soup.select("div.calendarbox")
    messages.extend(
        check_structure_hash(
            "kyodo_tokai",
            "\n".join(str(node) for node in fragment_nodes),
            "calendar",
        )
    )
    if has_major_warning(messages, "kyodo_tokai"):
        messages.append(
            build_admin_warning_message(
                "キョードー東海",
                {"カレンダー日": len(soup.select(CALENDAR_SELECTOR))},
            )
        )
    return messages


def _save_fetch_debug(html, diagnostics):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    html_path = DEBUG_DIR / f"kyodo_tokai_{timestamp}.html"
    json_path = DEBUG_DIR / f"kyodo_tokai_{timestamp}.json"
    html_path.write_text(html or "", encoding="utf-8")
    payload = dict(diagnostics)
    payload["saved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    payload["html_path"] = str(html_path)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return html_path, json_path


def _fetch_page(page, url, selector, page_label):
    attempts = []
    last_html = ""
    last_soup = BeautifulSoup("", "html.parser")

    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        response = None
        error = ""
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
            last_html = page.content()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            try:
                last_html = page.content()
            except Exception:
                last_html = ""

        last_soup = BeautifulSoup(last_html, "html.parser")
        selector_count = len(last_soup.select(selector))
        status = getattr(response, "status", None) if response is not None else None
        attempts.append(
            {
                "attempt": attempt,
                "status_code": status,
                "final_url": str(getattr(page, "url", "") or ""),
                "response_length": len(last_html.encode("utf-8")),
                "selector": selector,
                "selector_count": selector_count,
                "error": error,
            }
        )
        if status == 200 and selector_count > 0:
            return last_soup, attempts, None

    diagnostics = {
        "source_url": url,
        "page_label": page_label,
        "attempts": attempts,
        "final": attempts[-1],
    }
    html_path, json_path = _save_fetch_debug(last_html, diagnostics)
    return last_soup, attempts, (html_path, json_path)


def _fetch_events_page(page, url=URL, page_label="events"):
    return _fetch_page(page, url, EVENT_SELECTOR, page_label)


def _diagnostic_messages(attempts, debug_paths, page_label):
    messages = []
    if len(attempts) > 1:
        messages.append(
            "scraper_health_info: kyodo_tokai fetch retried "
            f"page={page_label} "
            f"first_status={attempts[0]['status_code']} "
            f"first_length={attempts[0]['response_length']} "
            f"first_selector_count={attempts[0]['selector_count']} "
            f"final_status={attempts[-1]['status_code']} "
            f"final_length={attempts[-1]['response_length']} "
            f"final_selector_count={attempts[-1]['selector_count']}"
        )
    if debug_paths is not None:
        html_path, json_path = debug_paths
        final = attempts[-1]
        messages.append(
            "scraper_health_warning: kyodo_tokai fetch diagnostics "
            f"page={page_label} status={final['status_code']} "
            f"final_url={final['final_url']} "
            f"response_length={final['response_length']} "
            f"selector_count={final['selector_count']} "
            f"saved_html={html_path} saved_json={json_path}"
        )
    return messages


def _event_url(dl):
    link = dl.select_one("a.alink[href]")
    return urljoin(URL, link.get("href", "")) if link else ""


def _calendar_url(target_date):
    return f"{CALENDAR_URL}/{target_date:%Y%m}"


def _parse_calendar_candidates(soup, target_date):
    heading = soup.select_one("div.calendarbox h3 strong")
    actual_month = heading.get_text(strip=True) if heading else ""
    expected_month = target_date.strftime("%Y/%m")
    if actual_month != expected_month:
        return [], actual_month

    candidates = []
    seen_urls = set()
    for row in soup.select(CALENDAR_SELECTOR):
        day_tag = row.select_one("th strong")
        if not day_tag or not day_tag.get_text(strip=True).isdigit():
            continue
        day = int(day_tag.get_text(strip=True))
        try:
            event_date = target_date.date().replace(day=day)
        except ValueError:
            continue
        for link in row.select('td a[href*="/events/detail/"]'):
            event_url = urljoin(CALENDAR_URL, link.get("href", ""))
            if not event_url or event_url in seen_urls:
                continue
            seen_urls.add(event_url)
            candidates.append(
                {
                    "date": event_date,
                    "title": link.get_text(" ", strip=True),
                    "url": event_url,
                }
            )
    return candidates, actual_month


def _detail_fields(soup):
    values = {}
    for row in soup.select("div.detailbox table.table01 tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for index, cell in enumerate(cells):
            if cell.name != "th" or index + 1 >= len(cells):
                continue
            label = re.sub(r"\s+", "", cell.get_text(" ", strip=True))
            values[label] = cells[index + 1].get_text(" ", strip=True)

    heading = soup.select_one("div.detailbox h3")
    title = ""
    if heading:
        title = " ".join(
            text.strip()
            for text in heading.find_all(string=True, recursive=False)
            if text.strip()
        )
    return {
        "date": _parse_event_date(values.get("開催日", "")),
        "venue": values.get("会場", ""),
        "time": values.get("開演", "").replace("\xa0", " ").strip() or "未定",
        "title": title,
    }


def _parse_event_date(text):
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if not match:
        return None
    try:
        return datetime(*(int(value) for value in match.groups())).date()
    except ValueError:
        return None


def _log_skip(reason, *, event_url="", title="", venue="", **fields):
    suffix = " ".join(f"{key}={value!r}" for key, value in fields.items())
    logging.info(
        "kyodo_event_skipped_reason reason=%s url=%s title=%r venue=%r%s",
        reason,
        event_url,
        title,
        venue,
        f" {suffix}" if suffix else "",
    )


def _append_event(events, seen_urls, event_url, event_date, time_text, venue, title):
    logging.info(
        "kyodo_event_parsed url=%s date=%s time=%s venue=%r title=%r",
        event_url,
        event_date.isoformat(),
        time_text,
        venue,
        title,
    )
    if event_url in seen_urls:
        _log_skip("duplicate_url", event_url=event_url, title=title, venue=venue)
        return
    seen_urls.add(event_url)
    events.append(
        {
            "time": time_text,
            "venue": venue,
            "title": title,
            "source": "kyodo_tokai",
        }
    )
    logging.info(
        "kyodo_event_added url=%s date=%s time=%s venue=%r title=%r",
        event_url,
        event_date.isoformat(),
        time_text,
        venue,
        title,
    )


def _scrape_alphabetical_fallback(page, target_date, health_messages):
    events = []
    soups = []

    for index, url in enumerate(INDEX_URLS, start=1):
        soup, attempts, debug_paths = _fetch_events_page(
            page, url=url, page_label=f"index_{index}"
        )
        soups.append(soup)
        health_messages.extend(
            _diagnostic_messages(attempts, debug_paths, f"index_{index}")
        )

    seen_urls = set()
    for dl in (dl for soup in soups for dl in soup.select(EVENT_SELECTOR)):
        text = " ".join(dl.get_text(" ", strip=True).split())
        event_url = _event_url(dl)
        title_tag = dl.select_one("a.alink")
        title = title_tag.get_text(" ", strip=True) if title_tag else ""
        event_date = _parse_event_date(text)
        logging.info(
            "kyodo_event_found url=%s title=%r date=%s",
            event_url,
            title,
            event_date.isoformat() if event_date else "",
        )

        dd = dl.select_one("dd")
        venue = ""
        if dd:
            dd_text = dd.get_text(" ", strip=True)
            m_venue = re.search(r"【会場名】\s*(.*?)\s*【料金】", dd_text)
            venue = m_venue.group(1).strip() if m_venue else dd_text

        if not event_date:
            _log_skip("date_parse_failed", event_url=event_url, title=title, venue=venue)
            continue
        if event_date != target_date.date():
            _log_skip(
                "date_mismatch",
                event_url=event_url,
                title=title,
                venue=venue,
                event_date=event_date.isoformat(),
                target_date=target_date.date().isoformat(),
            )
            continue
        if not title:
            _log_skip("title_missing", event_url=event_url, venue=venue)
            continue
        if not venue:
            _log_skip("venue_missing", event_url=event_url, title=title)
            continue

        if not any(v in venue for v in WANTED_VENUES):
            _log_skip("venue_not_wanted", event_url=event_url, title=title, venue=venue)
            continue

        time_text = "未定"

        m_time = re.search(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})", text)
        if m_time:
            time_text = m_time.group(2)

        _append_event(
            events, seen_urls, event_url, event_date, time_text, venue, title
        )

    return events


def scrape_kyodo_tokai_with_health(page, target_date):
    health_messages = []
    calendar_url = _calendar_url(target_date)
    soup, attempts, debug_paths = _fetch_page(
        page, calendar_url, CALENDAR_SELECTOR, "calendar"
    )
    health_messages.extend(_diagnostic_messages(attempts, debug_paths, "calendar"))

    if debug_paths is not None:
        logging.warning("kyodo_calendar_fallback reason=fetch_failed url=%s", calendar_url)
        return (
            _scrape_alphabetical_fallback(page, target_date, health_messages),
            health_messages,
        )

    health_messages.extend(_kyodo_health_messages(soup))
    candidates, actual_month = _parse_calendar_candidates(soup, target_date)
    if actual_month != target_date.strftime("%Y/%m"):
        health_messages.append(
            "scraper_health_warning: kyodo_tokai calendar month mismatch "
            f"expected={target_date:%Y/%m} actual={actual_month or 'missing'}"
        )
        logging.warning(
            "kyodo_calendar_fallback reason=month_mismatch expected=%s actual=%s",
            target_date.strftime("%Y/%m"),
            actual_month,
        )
        return (
            _scrape_alphabetical_fallback(page, target_date, health_messages),
            health_messages,
        )

    logging.info(
        "kyodo_calendar_candidates month=%s count=%s",
        target_date.strftime("%Y-%m"),
        len(candidates),
    )
    events = []
    seen_urls = set()
    for candidate in candidates:
        event_url = candidate["url"]
        title = candidate["title"]
        event_date = candidate["date"]
        logging.info(
            "kyodo_event_found url=%s title=%r date=%s",
            event_url,
            title,
            event_date.isoformat(),
        )
        if event_date != target_date.date():
            _log_skip(
                "date_mismatch",
                event_url=event_url,
                title=title,
                event_date=event_date.isoformat(),
                target_date=target_date.date().isoformat(),
            )
            continue

        detail_soup, detail_attempts, detail_debug = _fetch_page(
            page, event_url, DETAIL_SELECTOR, f"detail_{event_url.rsplit('/', 1)[-1]}"
        )
        health_messages.extend(
            _diagnostic_messages(
                detail_attempts, detail_debug, f"detail_{event_url.rsplit('/', 1)[-1]}"
            )
        )
        if detail_debug is not None:
            _log_skip("detail_fetch_failed", event_url=event_url, title=title)
            continue

        fields = _detail_fields(detail_soup)
        detail_date = fields["date"]
        venue = fields["venue"]
        detail_title = fields["title"] or title
        if detail_date != target_date.date():
            _log_skip(
                "detail_date_mismatch" if detail_date else "date_parse_failed",
                event_url=event_url,
                title=detail_title,
                venue=venue,
                detail_date=detail_date.isoformat() if detail_date else "",
                target_date=target_date.date().isoformat(),
            )
            continue
        if not detail_title:
            _log_skip("title_missing", event_url=event_url, venue=venue)
            continue
        if not venue:
            _log_skip("venue_missing", event_url=event_url, title=detail_title)
            continue
        if not any(wanted in venue for wanted in WANTED_VENUES):
            _log_skip(
                "venue_not_wanted",
                event_url=event_url,
                title=detail_title,
                venue=venue,
            )
            continue
        _append_event(
            events,
            seen_urls,
            event_url,
            detail_date,
            fields["time"],
            venue,
            detail_title,
        )

    return events, health_messages


def scrape_kyodo_tokai(page, target_date):
    events, _messages = scrape_kyodo_tokai_with_health(page, target_date)
    return events
