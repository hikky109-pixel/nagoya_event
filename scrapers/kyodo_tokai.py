from utils import is_wanted_venue
from bs4 import BeautifulSoup
import re

from tools.common.scraper_health import (
    build_admin_warning_message,
    check_selector_count,
    check_structure_hash,
    has_major_warning,
)

URL = "https://www.kyodotokai.co.jp/events"

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
    event_selector = "div.eventlistbox dl"
    messages.extend(
        check_selector_count(
            "kyodo_tokai",
            soup,
            event_selector,
            "events",
            min_count=1,
            drop_ratio=0.8,
        )
    )
    fragment_nodes = soup.select("div.eventlistbox")
    messages.extend(
        check_structure_hash(
            "kyodo_tokai",
            "\n".join(str(node) for node in fragment_nodes),
            "events",
        )
    )
    if has_major_warning(messages, "kyodo_tokai"):
        messages.append(
            build_admin_warning_message(
                "キョードー東海",
                {"イベント": len(soup.select(event_selector))},
            )
        )
    return messages


def scrape_kyodo_tokai_with_health(page, target_date):
    events = []

    target_str = target_date.strftime("%Y年%m月%d日")

    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=15000)
    except Exception as exc:
        messages = [
            "scraper_health_warning: "
            f"kyodo_tokai HTML取得失敗 error={type(exc).__name__} url={URL}",
            build_admin_warning_message(
                "キョードー東海",
                {"イベント": 0},
            ),
        ]
        return [], messages

    soup = BeautifulSoup(page.content(), "html.parser")
    health_messages = _kyodo_health_messages(soup)

    for dl in soup.select("div.eventlistbox dl"):
        text = " ".join(dl.get_text(" ", strip=True).split())

        if target_str not in text:
            continue

        title_tag = dl.select_one("a.alink")
        title = title_tag.get_text(" ", strip=True) if title_tag else ""

        dd = dl.select_one("dd")
        venue = ""
        if dd:
            dd_text = dd.get_text(" ", strip=True)
            m_venue = re.search(r"【会場名】\s*(.*?)\s*【料金】", dd_text)
            venue = m_venue.group(1).strip() if m_venue else dd_text

        if not title or not venue:
            continue

        if not any(v in venue for v in WANTED_VENUES):
            print(f"キョードー除外: {venue} | {title}")
            continue

        time_text = "未定"

        m_time = re.search(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})", text)
        if m_time:
            time_text = m_time.group(2)

        events.append({
            "time": time_text,
            "venue": venue,
            "title": title,
            "source": "kyodo_tokai",
        })

    return events, health_messages


def scrape_kyodo_tokai(page, target_date):
    events, _messages = scrape_kyodo_tokai_with_health(page, target_date)
    return events
