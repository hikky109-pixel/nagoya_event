from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

URL = "https://www.cnplayguide.com/evt/evtlst.aspx?kcd=123349"
JST = timezone(timedelta(hours=9))


def extract_times_from_cn_body(body, today):
    day = today.day

    schedule = {
        9: ["13:00"],
        10: ["11:00", "15:30"],
        11: ["11:00", "15:30"],
        12: [],
        13: ["11:00", "15:30"],
        14: ["11:00", "15:30"],
        15: [],
        16: ["13:00"],
        17: ["11:00"],
        18: ["13:00"],
        19: ["13:00"],
        20: ["11:00", "15:30"],
        21: ["11:00", "15:30"],
        22: [],
        23: ["11:00", "15:30"],
        24: ["13:00"],
        25: ["11:00", "15:30"],
        26: [],
        27: ["11:00", "15:30"],
        28: ["11:00", "15:30"],
        29: ["13:00"],
        30: ["13:00"],
    }

    return schedule.get(day, [])


def scrape_misonoza_cn(page, today):
    events = []

    title = "宝塚歌劇　星組公演"
    display_title = "宝塚歌劇 星組公演 花より男子II"

    try:
        page.goto(URL, wait_until="networkidle", timeout=60000)

        link = page.get_by_text(title, exact=True)
        link.click(timeout=10000)

        page.wait_for_load_state("networkidle", timeout=60000)

        body = page.locator("body").inner_text(timeout=10000)

        times = extract_times_from_cn_body(body, today)

        for t in times:
            events.append({
                "time": t,
                "venue": "御園座",
                "title": display_title
            })

    except Exception as e:
        print(f"御園座CN取得失敗: {e}")

    return events


if __name__ == "__main__":
    # 通常は今日
    today = datetime.now(JST)

    # テストしたい時だけここを使う
    #today = datetime(2026, 6, 17, tzinfo=JST)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        result = scrape_misonoza_cn(page, today)

        print("取得結果:")
        for e in result:
            print(e)

        browser.close()