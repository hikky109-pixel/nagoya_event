from utils import is_wanted_venue

from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

def scrape_jailhouse(page, target_date):
    events = []

    url = f"https://www.jailhouse.jp/live-calendar/?cal_y={target_date.year}&cal_m={target_date.month}"
    target_str = target_date.strftime("%Y/%m/%d")

    page.goto(url, wait_until="networkidle")
    soup = BeautifulSoup(page.content(), "html.parser")

    day = soup.select_one(f'.day[data-date="{target_str}"]')
    if not day:
        return events

    row = day.find_parent("div", class_="row")
    if not row:
        return events

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
            "title": full_title
        })

    return events
