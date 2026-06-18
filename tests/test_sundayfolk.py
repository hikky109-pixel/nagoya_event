import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
import re

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# プロジェクト直下の utils.py を読めるようにする
sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils import is_wanted_venue


URL = "https://www.sundayfolk.com/calendar/"


def scrape_sundayfolk(page, target_date):
    events = []

    target_anchor = "d" + target_date.strftime("%Y%m%d")

    page.goto(URL, wait_until="domcontentloaded", timeout=15000)
    soup = BeautifulSoup(page.content(), "html.parser")

    target = soup.select_one(f"#{target_anchor}")
    if not target:
        print(f"サンデーフォーク日付なし: {target_anchor}")
        return events

    rows = target.select("tr")

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        artist = cols[0].get_text(" ", strip=True)

        link_tag = cols[1].select_one("a[href]")
        if not link_tag:
            continue

        detail_url = urljoin(URL, link_tag.get("href"))

        venue = cols[3].get_text(" ", strip=True)

        area_img = cols[4].select_one("img")
        area = area_img.get("alt", "").strip() if area_img else ""

        if area not in ["名古屋", "愛知"]:
            continue

        if not is_wanted_venue(venue):
            print(f"サンデーフォーク除外: {venue} | {artist}")
            continue

        title = artist
        performances = []

        try:
            page.goto(detail_url, wait_until="domcontentloaded", timeout=15000)

            detail_soup = BeautifulSoup(page.content(), "html.parser")
            info_blocks = detail_soup.select("p.livloginfo_gaiyo")

            # タイトル
            title1 = detail_soup.select_one("#liveinfoTitle h1 span")
            title2 = detail_soup.select_one("#liveinfoTitle h2 span")

            artist_text = title1.get_text(" ", strip=True) if title1 else artist
            subtitle = title2.get_text(" ", strip=True) if title2 else ""

            title = artist_text
            if subtitle:
                title += f" | {subtitle}"

            # 日時・会場ブロック
            info_blocks = detail_soup.select("p.livloginfo_gaiyo")

            if len(info_blocks) >= 1:
                date_text = info_blocks[0].get_text("\n", strip=True)

                lines = date_text.splitlines()

                for i, line in enumerate(lines):
                    date_match = re.search(r"(\d{4}/\d{2}/\d{2})", line)
                    if not date_match:
                        continue

                    # まず同じ行の時間を見る
                    time_match = re.search(r"(\d{1,2}:\d{2})", line)

                    # 同じ行になければ次の行を見る
                    if not time_match and i + 1 < len(lines):
                        time_match = re.search(r"(\d{1,2}:\d{2})", lines[i + 1])

                    if not time_match:
                        continue

                    perf_date = datetime.strptime(
                        date_match.group(1),
                        "%Y/%m/%d"
                    ).date()

                    if perf_date == target_date.date():
                        performances.append({
                            "time": time_match.group(1)
                        })                        
                        
            if len(info_blocks) >= 2:
                detail_venue = info_blocks[1].get_text(" ", strip=True)
                if detail_venue:
                    venue = detail_venue

        except Exception as e:
            print(f"サンデーフォーク詳細取得失敗: {detail_url} | {e}")

        # 詳細ページで複数公演が取れた場合
        if performances:
            for perf in performances:
                events.append({
                    "time": perf["time"],
                    "venue": venue,
                    "title": title
                })
        else:
            # 取れなかった場合の保険
            events.append({
                "time": "未定",
                "venue": venue,
                "title": title
            })

    return events


if __name__ == "__main__":
    target_date = datetime(2026, 6, 6)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        events = scrape_sundayfolk(page, target_date)

        browser.close()

    for event in events:
        print(event)