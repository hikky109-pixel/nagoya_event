from playwright.sync_api import sync_playwright
from datetime import timezone, timedelta
import re

URL = "https://www.cnplayguide.com/evt/evtlst.aspx?kcd=123349"

JST = timezone(timedelta(hours=9))


def get_detail_body(page, title):

    page.goto(URL, wait_until="networkidle", timeout=60000)

    # 宝塚歌劇 星組公演
    page.locator("a").nth(9).click(timeout=10000)

    page.wait_for_load_state("networkidle", timeout=60000)

    body = page.locator("body").inner_text(timeout=10000)

    print("URL:", page.url)
    print(body[:3000])

    return body


def extract_schedule_block(body):

    start = body.find("公演日程")
    end = body.find("席種／料金")

    if start == -1:
        return ""

    if end == -1:
        end = len(body)

    return body[start:end]


def main():

    title = "宝塚歌劇　星組公演"

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        page = browser.new_page()

        body = get_detail_body(page, title)

        schedule_text = extract_schedule_block(body)
        print("ここまでよんでるでぇ")
        print(len(body))
        
        print("===== BODY先頭5000文字 =====")
        print(body[:5000])

        print("\n===== 公演日程ブロック全文 =====\n")
        print(schedule_text)

        print("\n===== 時刻だけ抽出 =====\n")

        times = re.findall(r"\d{1,2}:\d{2}", schedule_text)

        print(times)

        browser.close()


if __name__ == "__main__":
    main()