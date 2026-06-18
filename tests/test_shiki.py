from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

from shiki import dedupe_events, scrape_shiki, write_shiki_csv


JST = timezone(timedelta(hours=9))


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    events = scrape_shiki(page, datetime.now(JST))

    browser.close()

events = dedupe_events(events)

for event in events:
    print(event)

write_shiki_csv(events, "csv_events/shiki.csv", today=datetime.now(JST))
print("CSV written: csv_events/shiki.csv")
