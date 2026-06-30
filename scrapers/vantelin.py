import re
from bs4 import BeautifulSoup

from tools.common.scraper_health import (
    check_selector_count,
    check_sequence,
    check_structure_hash,
)

BLACKLIST = re.compile(
    r"関係者|結婚式|Wedding|ファーム|中地区公式戦|少年野球",
    re.IGNORECASE
)
CALENDAR_URL = "https://www.nagoya-dome.co.jp/sp/eventcalen.php"


def _month_sequence(soup):
    months = []
    for node in soup.select(".month"):
        text = node.get_text(" ", strip=True)
        match = re.search(r"(\d{1,2})\s*月?", text)
        if not match:
            continue
        month = str(int(match.group(1)))
        if month not in months:
            months.append(month)
    return months


def _calendar_fragment(soup):
    nodes = soup.select(".month, .events, .eventDay, .eventTitle")
    return "\n".join(str(node) for node in nodes)


def _health_messages(soup):
    messages = []
    months = _month_sequence(soup)
    messages.extend(
        check_sequence(
            "vantelin",
            "months",
            "months",
            months,
            min_count=1,
        )
    )
    messages.extend(
        check_selector_count(
            "vantelin",
            soup,
            ".eventDay",
            "events",
            min_count=1,
            drop_ratio=0.8,
        )
    )
    messages.extend(
        check_structure_hash(
            "vantelin",
            _calendar_fragment(soup),
            "calendar",
        )
    )
    return messages


def _health_count(messages, label):
    for message in messages:
        if message.startswith(f"scraper_health: vantelin {label}="):
            return len(message.split("=", 1)[1].split(",")) if message.split("=", 1)[1] else 0
        if message.startswith(f"scraper_health: vantelin {label} count="):
            try:
                return int(message.rsplit("=", 1)[1])
            except ValueError:
                return 0
    return 0


def _admin_health_message(messages):
    major = [
        message for message in messages
        if message.startswith("scraper_health_warning: vantelin")
        and (
            "months 0件" in message
            or "events 0件" in message
            or "HTML取得失敗" in message
        )
    ]
    if not major:
        return ""
    month_count = _health_count(messages, "months")
    event_count = _health_count(messages, "events")
    return (
        "⚠️ バンテリンドームスクレイパー異常\n\n"
        f"月タブ: {month_count}件\n"
        f"イベント: {event_count}件\n\n"
        "HTML構造変更または取得失敗の可能性があります。"
    )


def _html_fetch_failed_admin_message():
    return (
        "⚠️ バンテリンドームスクレイパー異常\n\n"
        "月タブ: 0件\n"
        "イベント: 0件\n\n"
        "HTML構造変更または取得失敗の可能性があります。"
    )


def scrape_vantelin_with_health(page, target_date):
    events = []
    health_messages = []

    try:
        response = page.goto(
            CALENDAR_URL,
            timeout=60000
        )
    except Exception as exc:
        health_messages.append(
            "scraper_health_warning: "
            f"vantelin HTML取得失敗 error={type(exc).__name__} url={CALENDAR_URL}"
        )
        health_messages.append(_html_fetch_failed_admin_message())
        return [], health_messages

    if response and response.status >= 400:
        health_messages.append(
            "scraper_health_warning: "
            f"vantelin HTML取得失敗 status={response.status} url={CALENDAR_URL}"
        )
        health_messages.append(_html_fetch_failed_admin_message())
        return [], health_messages

    page.wait_for_timeout(12000)

    soup = BeautifulSoup(page.content(), "html.parser")
    health_messages.extend(_health_messages(soup))
    admin_message = _admin_health_message(health_messages)
    if admin_message:
        health_messages.append(admin_message)

    month = target_date.month
    day = target_date.day
    date_regex = re.compile(rf"\b0?{month}/0?{day}\b")

    all_tds = soup.select("td")

    for i, td in enumerate(all_tds):
        day_text = td.get_text(" ", strip=True)

        if not date_regex.search(day_text):
            continue

        title = None

        for next_td in all_tds[i + 1:i + 6]:
            text = " ".join(next_td.get_text(" ", strip=True).split())

            if not text:
                continue

            if date_regex.search(text):
                break

            if "開始" in text or "開場" in text:
                continue

            title = text
            break

        if not title:
            continue

        if "---" in day_text or BLACKLIST.search(title):
            print(f"  └ バンテリン除外: {title}")
            continue

        start_match = re.search(r"開始[\s　／]*(\d{1,2}:\d{2})", day_text)

        if start_match:
            time_text = start_match.group(1)
        else:
            times = re.findall(r"\d{1,2}:\d{2}", day_text)
            time_text = times[-1] if times else "時間情報なし"

        events.append({
            "time": time_text,
            "venue": "バンテリンドームナゴヤ",
            "title": title,
            "source": "calendar",
        })

    return [event for event in events if event.get("source") == "calendar"], health_messages


def scrape_vantelin(page, target_date):
    events, _messages = scrape_vantelin_with_health(page, target_date)
    return events
