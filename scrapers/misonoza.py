from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import urlretrieve
import csv
import json
import re
import subprocess
import tempfile


JST = timezone(timedelta(hours=9))
LIST_URLS = [
    "https://www.misonoza.co.jp/lineup/monthly/",
    "https://www.misonoza.co.jp/lineup/",
]
COMMON_COLUMNS = ["date", "time", "venue", "title"]
MISONOZA_CSV_COLUMNS = [
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
DEFAULT_MISONOZA_CSV_PATH = Path(__file__).resolve().parents[1] / "csv_events" / "misonoza.csv"
NOTIFIED_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "misonoza_notified.json"


def _target_date(today):
    if today is None:
        return datetime.now(JST).date()
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    return datetime.strptime(str(today), "%Y/%m/%d").date()


def _title_from_soup(soup):
    title = soup.title.get_text(" ", strip=True) if soup.title else "不明"
    return title.split("｜公演ご案内ラインアップ｜御園座")[0].strip()


def _date_from_url(url):
    match = re.search(r"month(\d{2})(\d{2})(\d{2})\.html", url)
    if not match:
        return None

    return 2000 + int(match.group(1)), int(match.group(2)), int(match.group(3))


def _make_date(year, month, start_day, day):
    event_year = year
    event_month = month

    if day < start_day:
        event_month += 1
        if event_month > 12:
            event_year += 1
            event_month = 1

    return f"{event_year:04d}/{event_month:02d}/{day:02d}"


def is_rental_event(title: str) -> bool:
    return "【貸館】" in title


def _show_text(soup) -> str:
    showset03 = soup.select_one("#showset03")
    if showset03:
        return showset03.get_text(" ", strip=True)
    return soup.get_text(" ", strip=True)


def has_schedule(events: list[dict]) -> bool:
    return any(event.get("date") and event.get("time") for event in events)


def is_external_link(soup, base_url: str) -> bool:
    base_host = urlparse(base_url).netloc
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue

        linked_url = urljoin(base_url, href)
        linked_host = urlparse(linked_url).netloc
        if linked_host and linked_host != base_host:
            return True

    return False


def _is_misonoza_show_page(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.netloc == "www.misonoza.co.jp"
        and bool(re.search(r"/lineup/month\d{6}\.html$", parsed.path))
    )


def _date_from_text(text: str):
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if not match:
        return None

    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _lineup_item_start_date(item: dict):
    return _page_start_date(item.get("url", "")) or _date_from_text(item.get("text", ""))


def _page_start_date(url: str):
    url_date = _date_from_url(url)
    if not url_date:
        return None

    year, month, start_day = url_date
    return date(year, month, start_day)


def _extract_end_time(text: str) -> str:
    match = re.search(r"(\d{1,2}:\d{2})\s*終演予定", text)
    return match.group(1) if match else ""


def _events_from_rental_text(soup, url, title):
    if not is_rental_event(title):
        return []

    text = soup.get_text(" ", strip=True)
    start_match = re.search(r"(\d{1,2}:\d{2})\s*開演", text)
    if not start_match:
        return []

    start_date = _page_start_date(url)
    if not start_date:
        return []

    event = {
        "date": start_date.strftime("%Y/%m/%d"),
        "time": start_match.group(1),
        "venue": "御園座",
        "title": title,
        "note": "貸館",
        "url": url,
    }

    end_time = _extract_end_time(text)
    if end_time:
        event["end_time"] = end_time

    return [event]


def _apply_event_metadata(events: list[dict], title: str, url: str, soup) -> list[dict]:
    if not events:
        return events

    end_time = _extract_end_time(soup.get_text(" ", strip=True)) if is_rental_event(title) else ""

    for event in events:
        event.setdefault("url", url)
        event.setdefault("status", "confirmed")
        if is_rental_event(title):
            event["note"] = "貸館"
            if end_time:
                event.setdefault("end_time", end_time)

    return events


def build_warning_message(title: str) -> str:
    display_title = title.replace("【貸館】", "").strip()
    if "Love Me Do" in display_title:
        display_title = "Love Me Do"

    return f"""【御園座】
日程取れねぞゴルァ
今北産業
・貸館イベント
・{display_title}
・外部サイト誘導
・時間取得失敗
手動確認よろしく"""


def build_skip_message(title: str) -> str:
    return f"""【御園座】
日程未確定スキップ
今北産業
・{title}
・公演期間のみ取得
・個別開演時間なし
日程表公開待ち"""


def build_reminder_message(title: str) -> str:
    return f"""【御園座】
日程まだ入ってないぞ案件
今北産業
・{title}
・公演開始7日前
・個別開演時間なし
手動確認よろしく"""


def build_ocr_message(title: str) -> str:
    return f"""【御園座OCR】
読めねーぞ案件
今北産業
・スケジュール画像あり
・HTML日程なし
・OCR未対応または失敗
・{title}
手動確認よろしく"""


def _has_schedule_image(soup) -> bool:
    showset03 = soup.select_one("#showset03")
    if not showset03:
        return False

    for img in showset03.select("img[src]"):
        text = " ".join([
            img.get("src", ""),
            img.get("alt", ""),
            img.get("class", "") if isinstance(img.get("class", ""), str) else " ".join(img.get("class", [])),
        ]).lower()
        if any(word in text for word in ("schedule", "timetable", "time", "cast", "日程", "時間", "スケジュール")):
            return True

    return bool(showset03.select("img[src]"))


def _notification_key(title: str, url: str) -> str:
    return f"{title}|{url}"


def _load_notified_state(path: Path = NOTIFIED_STATE_PATH) -> dict:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_notified_state(state: dict, path: Path = NOTIFIED_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _date_to_state_text(value):
    return value.isoformat() if isinstance(value, date) else ""


def _remember_notification(state: dict, item: dict, notification_type: str, target: date, start_date=None, reason="") -> None:
    key = _notification_key(item.get("title", ""), item.get("url", ""))
    record = state.setdefault(key, {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
    })
    record["title"] = item.get("title", "")
    record["url"] = item.get("url", "")
    if start_date:
        record["start_date"] = _date_to_state_text(start_date)
    if reason:
        reasons = set(record.get("reasons", []))
        reasons.add(reason)
        record["reasons"] = sorted(reasons)
    record[f"{notification_type}_notified"] = _date_to_state_text(target)


def _already_notified(state: dict, item: dict, notification_type: str) -> bool:
    key = _notification_key(item.get("title", ""), item.get("url", ""))
    return bool(state.get(key, {}).get(f"{notification_type}_notified"))


def _unscheduled_messages_with_state(item: dict, base_messages: list[str], target: date, state: dict) -> list[str]:
    messages = []
    start_date = item.get("start_date") or _lineup_item_start_date(item)

    for message in base_messages:
        if _is_ocr_message(message):
            if not _already_notified(state, item, "ocr"):
                messages.append(message)
                _remember_notification(
                    state,
                    item,
                    "ocr",
                    target,
                    start_date,
                    reason="schedule_image_found",
                )
            continue

        if not _is_skip_message(message):
            messages.append(message)
            continue

        if start_date and target >= start_date - timedelta(days=7):
            if not _already_notified(state, item, "reminder"):
                messages.append(build_reminder_message(item.get("title", "")))
                _remember_notification(state, item, "reminder", target, start_date)
            continue

        if not _already_notified(state, item, "initial"):
            messages.append(message)
            _remember_notification(state, item, "initial", target, start_date)

    return messages


def _has_period_only(text: str) -> bool:
    has_period = re.search(r"\d{4}年\d{1,2}月\d{1,2}日.*?[〜～-].*?\d{1,2}月?\d{1,2}日", text)
    has_time = re.search(r"\d{1,2}:\d{2}", text)
    return bool(has_period and not has_time)


def _messages_for_unscheduled_item(title: str, text: str, has_external_link: bool) -> list[str]:
    if is_rental_event(title) and has_external_link:
        return [build_warning_message(title)]

    if _has_period_only(text):
        return [build_skip_message(title)]

    return []


def normalize_misonoza_event(event: dict) -> dict:
    normalized = {
        "date": "",
        "time": event.get("time", ""),
        "end_time": event.get("end_time", ""),
        "venue": event.get("venue", "御園座"),
        "title": event.get("title", ""),
        "source": "御園座",
        "status": event.get("status", "confirmed"),
        "note": event.get("note", ""),
        "url": event.get("url", ""),
    }

    date_text = event.get("date", "")
    if date_text:
        normalized["date"] = datetime.strptime(date_text, "%Y/%m/%d").strftime("%Y-%m-%d")

    return normalized


def dedupe_events(events: list[dict]) -> list[dict]:
    unique_events = []
    seen = {}

    for event in events:
        key = (
            event.get("date", ""),
            event.get("time", ""),
            event.get("venue", ""),
            event.get("title", ""),
            event.get("url", ""),
        )

        if key in seen:
            existing = seen[key]
            for field, value in event.items():
                if value and not existing.get(field):
                    existing[field] = value
            continue

        seen[key] = event
        unique_events.append(event)

    return unique_events


def _merge_key(event: dict) -> tuple:
    return (
        event.get("date", ""),
        event.get("time", ""),
        event.get("venue", ""),
        event.get("title", ""),
        event.get("url", ""),
    )


def _is_manual_row(row: dict) -> bool:
    return row.get("status", "") == "manual" or "手動補完" in row.get("note", "")


def _manual_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if _is_manual_row(row)]


def _has_common_manual_keyword(title: str, manual_title: str) -> bool:
    for keyword in ("Love Me Do",):
        if keyword in title and keyword in manual_title:
            return True

    return False


def _is_manual_completed_item(item: dict, manual_rows: list[dict]) -> bool:
    item_title = item.get("title", "")
    item_url = item.get("url", "")

    for row in manual_rows:
        if not _is_manual_row(row):
            continue

        row_url = row.get("url", "")
        if item_url and row_url and item_url == row_url:
            return True

        if _has_common_manual_keyword(item_title, row.get("title", "")):
            return True

    return False


def _is_skip_message(message: str) -> bool:
    return "日程未確定スキップ" in message


def _is_ocr_message(message: str) -> bool:
    return "【御園座OCR】" in message


def _is_warning_message(message: str) -> bool:
    return "日程取れねぞゴルァ" in message


def _is_reminder_message(message: str) -> bool:
    return "日程まだ入ってないぞ案件" in message


def _is_manage_notification_message(message: str) -> bool:
    return (
        _is_skip_message(message)
        or _is_ocr_message(message)
        or _is_warning_message(message)
        or _is_reminder_message(message)
    )


def _suppress_manual_completed_messages(messages: list[str], item: dict, manual_rows: list[dict]) -> list[str]:
    if not _is_manual_completed_item(item, manual_rows):
        return messages

    return [message for message in messages if not _is_manage_notification_message(message)]


def _load_existing_misonoza_csv(output_file: Path) -> list[dict]:
    if not output_file.exists():
        return []

    with output_file.open(newline="", encoding="utf-8") as csv_file:
        return [dict(row) for row in csv.DictReader(csv_file)]


def _merge_manual_rows(scraped_events: list[dict], existing_rows: list[dict]) -> list[dict]:
    merged_events = list(scraped_events)
    by_key = {_merge_key(event): event for event in merged_events}

    for row in existing_rows:
        if not _is_manual_row(row):
            continue

        key = _merge_key(row)
        existing_event = by_key.get(key)
        if existing_event is None:
            merged_events.append(row)
            by_key[key] = row
            continue

        if "手動補完" in row.get("note", ""):
            existing_event["note"] = row["note"]

    return merged_events


def write_misonoza_csv(events: list[dict], output_path: str) -> None:
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    normalized_events = [normalize_misonoza_event(event) for event in dedupe_events(events)]
    existing_rows = _load_existing_misonoza_csv(output_file)
    merged_events = dedupe_events(_merge_manual_rows(normalized_events, existing_rows))

    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=MISONOZA_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(merged_events)


def _events_from_timetable(soup, url, title):
    url_date = _date_from_url(url)
    if not url_date:
        return []

    year, month, start_day = url_date
    showset03 = soup.select_one("#showset03")
    if not showset03:
        return []

    events = []
    seen = set()
    day_text = ""

    for li in showset03.select("ul.timetable li"):
        if "timetableday" in li.get("class", []):
            day_match = re.search(r"\d{1,2}", li.get_text(" ", strip=True))
            day_text = day_match.group(0) if day_match else ""
            continue

        time_text = li.get_text(" ", strip=True)
        time_match = re.search(r"(\d{1,2}:\d{2})", time_text)
        if not time_match or not day_text:
            continue

        day = int(day_text)
        start_time = time_match.group(1)
        key = (day, start_time)
        if key in seen:
            continue

        seen.add(key)
        events.append({
            "date": _make_date(year, month, start_day, day),
            "time": start_time,
            "venue": "御園座",
            "title": title,
        })

    return events


def _ocr_words(image_url):
    with tempfile.NamedTemporaryFile(suffix=".jpg") as image_file:
        urlretrieve(image_url, image_file.name)
        result = subprocess.run(
            ["tesseract", image_file.name, "stdout", "-l", "eng", "--psm", "6", "tsv"],
            check=False,
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        return []

    rows = csv.DictReader(result.stdout.splitlines(), delimiter="	")
    words = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue

        try:
            left = int(row["left"])
            top = int(row["top"])
            width = int(row["width"])
            height = int(row["height"])
        except (KeyError, TypeError, ValueError):
            continue

        words.append({
            "text": text,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "center_x": left + width / 2,
            "center_y": top + height / 2,
        })

    return words


def _events_from_schedule_images(soup, url, title):
    url_date = _date_from_url(url)
    if not url_date:
        return []

    showset03 = soup.select_one("#showset03")
    if not showset03:
        return []

    year, month, start_day = url_date
    events = []
    seen = set()

    for img in showset03.select("img[src]"):
        image_url = urljoin(url, img["src"])
        words = _ocr_words(image_url)
        if not words:
            continue

        date_words = [
            word for word in words
            if re.fullmatch(r"\d{1,2}", word["text"])
            and 1 <= int(word["text"]) <= 31
        ]
        time_words = [
            word for word in words
            if re.fullmatch(r"\d{1,2}:\d{2}", word["text"])
        ]

        date_rows = []
        for word in sorted(date_words, key=lambda item: item["top"]):
            for row in date_rows:
                if abs(row[0]["top"] - word["top"]) <= 8:
                    row.append(word)
                    break
            else:
                date_rows.append([word])

        date_rows = [sorted(row, key=lambda item: item["center_x"]) for row in date_rows if len(row) >= 2]
        date_rows.sort(key=lambda row: row[0]["top"])

        for index, row in enumerate(date_rows):
            row_top = row[0]["top"]
            next_row_top = date_rows[index + 1][0]["top"] if index + 1 < len(date_rows) else float("inf")
            row_times = [word for word in time_words if row_top < word["top"] < next_row_top]

            for time_word in row_times:
                nearest_day = min(row, key=lambda day_word: abs(day_word["center_x"] - time_word["center_x"]))
                if abs(nearest_day["center_x"] - time_word["center_x"]) > 75:
                    continue

                day = int(nearest_day["text"])
                start_time = time_word["text"]
                key = (day, start_time)
                if key in seen:
                    continue

                seen.add(key)
                events.append({
                    "date": _make_date(year, month, start_day, day),
                    "time": start_time,
                    "venue": "御園座",
                    "title": title,
                })

    return events


def _scrape_show_page_with_notifications(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    soup = BeautifulSoup(page.content(), "html.parser")
    title = _title_from_soup(soup)

    events = _events_from_timetable(soup, page.url, title)
    if not events:
        events = _events_from_schedule_images(soup, page.url, title)
    if not events:
        events = _events_from_rental_text(soup, page.url, title)

    events = _apply_event_metadata(events, title, page.url, soup)
    if has_schedule(events):
        return events, []

    if is_rental_event(title) and is_external_link(soup, page.url):
        return [], [build_warning_message(title)]

    if _has_schedule_image(soup):
        return [], [build_ocr_message(title)]

    if _has_period_only(_show_text(soup)):
        return [], [build_skip_message(title)]

    return [], []


def _scrape_show_page(page, url):
    events, _messages = _scrape_show_page_with_notifications(page, url)
    return events


def _lineup_items(page):
    for list_url in LIST_URLS:
        response = page.goto(list_url, wait_until="domcontentloaded", timeout=30000)
        if response and response.status >= 400:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        items = []
        seen = set()

        for title_tag in soup.select("h1.set-lineup-tit"):
            link = title_tag.select_one("a[href]")
            if not link:
                continue

            url = urljoin(page.url, link["href"])
            title = title_tag.get_text(" ", strip=True)
            item_node = title_tag.find_parent(class_="set-lineup-box") or title_tag.parent
            text = item_node.get_text(" ", strip=True) if item_node else title
            key = (title, url)
            if key in seen:
                continue

            seen.add(key)
            items.append({
                "title": title,
                "url": url,
                "text": text,
                "start_date": _date_from_text(text),
                "has_external_link": is_external_link(item_node, page.url) if item_node else False,
                "has_schedule_image": bool(item_node and item_node.select("img[src]")),
                "has_show_page": _is_misonoza_show_page(url),
            })

        if items:
            return items

    return []


def _lineup_urls(page):
    return [item["url"] for item in _lineup_items(page) if item.get("has_show_page")]


def scrape_misonoza_with_notifications(page, today=None):
    target = _target_date(today)
    all_events = []
    messages = []
    notified_state = _load_notified_state()
    notified_state_changed = False
    manual_rows = _manual_rows(_load_existing_misonoza_csv(DEFAULT_MISONOZA_CSV_PATH))

    for item in _lineup_items(page):
        try:
            events = []
            page_messages = []

            if item.get("has_show_page"):
                events, page_messages = _scrape_show_page_with_notifications(page, item["url"])

            all_events.extend(events)

            item_start = _lineup_item_start_date(item)
            if item_start is not None and item_start < target:
                continue

            if has_schedule(events):
                continue

            if page_messages:
                item_messages = page_messages
            else:
                item_messages = _messages_for_unscheduled_item(
                    item["title"],
                    item.get("text", ""),
                    item.get("has_external_link", False),
                )
                if item.get("has_schedule_image") and not item_messages:
                    item_messages = [build_ocr_message(item["title"])]

            item_messages = _suppress_manual_completed_messages(item_messages, item, manual_rows)
            before_state = json.dumps(notified_state, ensure_ascii=False, sort_keys=True)
            item_messages = _unscheduled_messages_with_state(item, item_messages, target, notified_state)
            after_state = json.dumps(notified_state, ensure_ascii=False, sort_keys=True)
            if before_state != after_state:
                notified_state_changed = True
            messages.extend(item_messages)
        except Exception as exc:
            print(f"御園座除外: {item.get('url', '')} | {exc}")

    events = sorted(
        [event for event in all_events if datetime.strptime(event["date"], "%Y/%m/%d").date() >= target],
        key=lambda event: (event["date"], event["time"], event["title"]),
    )

    if notified_state_changed:
        _save_notified_state(notified_state)

    return events, messages


def scrape_misonoza(page, today=None):
    events, _messages = scrape_misonoza_with_notifications(page, today)
    return events
