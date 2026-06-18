from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

from misonoza import dedupe_events, scrape_misonoza_with_notifications, write_misonoza_csv


JST = timezone(timedelta(hours=9))


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    events, messages = scrape_misonoza_with_notifications(page, datetime.now(JST))

    browser.close()

events = dedupe_events(events)

for event in events:
    print(event)

for message in messages:
    print()
    print(message)

write_misonoza_csv(events, "csv_events/misonoza.csv")
print("CSV written: csv_events/misonoza.csv")
