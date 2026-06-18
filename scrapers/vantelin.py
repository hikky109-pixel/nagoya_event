import re
from bs4 import BeautifulSoup

BLACKLIST = re.compile(
    r"関係者|結婚式|Wedding|ファーム|中地区公式戦|少年野球",
    re.IGNORECASE
)

def scrape_vantelin(page, target_date):
    events = []

    page.goto(
        "https://www.nagoya-dome.co.jp/sp/eventcalen.php",
        timeout=60000
    )
    page.wait_for_timeout(12000)

    soup = BeautifulSoup(page.content(), "html.parser")

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
            "title": title
        })

    return events
