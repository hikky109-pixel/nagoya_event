from utils import is_wanted_venue

from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

from tools.common.scraper_health import (
    build_admin_warning_message,
    check_selector_count,
    check_structure_hash,
    has_major_warning,
)


def _jailhouse_health_messages(soup):
    messages = []
    day_selector = ".day[data-date]"
    event_selector = "ul.layout > li"
    messages.extend(
        check_selector_count(
            "jailhouse",
            soup,
            day_selector,
            "days",
            min_count=1,
        )
    )
    messages.extend(
        check_selector_count(
            "jailhouse",
            soup,
            event_selector,
            "events",
            min_count=1,
            drop_ratio=0.8,
        )
    )
    fragment_nodes = soup.select(".day[data-date], ul.layout > li")
    messages.extend(
        check_structure_hash(
            "jailhouse",
            "\n".join(str(node) for node in fragment_nodes),
            "calendar",
        )
    )
    if has_major_warning(messages, "jailhouse"):
        messages.append(
            build_admin_warning_message(
                "JAILHOUSE",
                {
                    "日付": len(soup.select(day_selector)),
                    "イベント": len(soup.select(event_selector)),
                },
            )
        )
    return messages


def scrape_jailhouse_with_health(page, target_date):
    events = []

    url = f"https://www.jailhouse.jp/live-calendar/?cal_y={target_date.year}&cal_m={target_date.month}"
    target_str = target_date.strftime("%Y/%m/%d")

    try:
        page.goto(url, wait_until="networkidle")
    except Exception as exc:
        messages = [
            "scraper_health_warning: "
            f"jailhouse HTML取得失敗 error={type(exc).__name__} url={url}",
            build_admin_warning_message(
                "JAILHOUSE",
                {"日付": 0, "イベント": 0},
            ),
        ]
        return [], messages

    soup = BeautifulSoup(page.content(), "html.parser")
    health_messages = _jailhouse_health_messages(soup)

    day = soup.select_one(f'.day[data-date="{target_str}"]')
    if not day:
        return events, health_messages

    row = day.find_parent("div", class_="row")
    if not row:
        return events, health_messages

    for li in row.select("ul.layout > li"):
        title_tag = li.select_one("p.title")
        other_tag = li.select_one("p.other")
        place_tag = li.select_one("p.place")
        link_tag = li.select_one("a")

        title = title_tag.get_text(" ", strip=True) if title_tag else ""
        artist = other_tag.get_text(" ", strip=True) if other_tag else ""
        venue = place_tag.get_text(" ", strip=True) if place_tag else "JAILHOUSE"

        if not title:
            continue

        time_text = "未定"

        if link_tag and link_tag.get("href"):
            detail_url = urljoin("https://www.jailhouse.jp", link_tag.get("href"))

            try:
               page.goto(
                    detail_url,
                    wait_until="domcontentloaded",
                    timeout=15000
               )
            except Exception:
                 print(f"JAILHOUSE詳細取得失敗: {detail_url}")
                 continue

            detail_soup = BeautifulSoup(
                 page.content(),
                 "html.parser"
    )

            live_info = detail_soup.select_one("div.live-info")
            if live_info:
                detail_text = live_info.get_text(" ", strip=True)

                m = re.search(r"START\s+(AM|PM)\s+(\d+):(\d+)", detail_text)

                if m:
                    ampm = m.group(1)
                    hour = int(m.group(2))
                    minute = int(m.group(3))

                    if ampm == "PM" and hour < 12:
                        hour += 12

                    if ampm == "AM" and hour == 12:
                        hour = 0

                    time_text = f"{hour:02d}:{minute:02d}"

        full_title = title
        if artist:
            full_title += f" / {artist}"
            
        if not is_wanted_venue(venue):
            print(f"JAILHOUSE除外: {venue} | {full_title}")
            continue

        events.append({
            "time": time_text,
            "venue": venue,
            "title": full_title,
            "source": "jailhouse",
        })

    return events, health_messages


def scrape_jailhouse(page, target_date):
    events, _messages = scrape_jailhouse_with_health(page, target_date)
    return events
