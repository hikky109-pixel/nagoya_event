from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from datetime import datetime
import re

BASE_URL = "https://www.sundayfolk.com/calendar/"

YEAR = 2026
START_MONTH = 1
END_MONTH = 6

venues = set()

with sync_playwright() as p:

    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    for month in range(START_MONTH, END_MONTH + 1):

        url = f"{BASE_URL}?ym={YEAR}{month:02d}"

        print(f"取得中: {url}")

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            soup = BeautifulSoup(
                page.content(),
                "html.parser"
            )

            # 地域アイコン
            for row in soup.select("tr"):

                cols = row.find_all("td")

                if len(cols) < 5:
                    continue

                area_img = cols[4].find("img")

                area = (
                    area_img.get("alt", "").strip()
                    if area_img else ""
                )

                if area not in ["名古屋", "愛知"]:
                    continue

                venue = cols[3].get_text(
                    " ",
                    strip=True
                )

                if venue:
                    venues.add(venue)

        except Exception as e:
            print(f"失敗: {url}")
            print(e)

    browser.close()

with open(
    "sundayfolk_venues.txt",
    "w",
    encoding="utf-8"
) as f:

    for venue in sorted(venues):
        f.write(venue + "\n")

print()
print(f"会場数: {len(venues)}")
print("保存: sundayfolk_venues.txt")
