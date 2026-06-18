from utils import is_wanted_venue
from bs4 import BeautifulSoup
import re

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

def scrape_kyodo_tokai(page, target_date):
    events = []

    target_str = target_date.strftime("%Y年%m月%d日")

    page.goto(URL, wait_until="domcontentloaded", timeout=15000)
    soup = BeautifulSoup(page.content(), "html.parser")

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
            "title": title
        })

    return events
