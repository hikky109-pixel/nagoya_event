from playwright.sync_api import sync_playwright
#test
URL = "https://www.cnplayguide.com/evt/evtlst.aspx?kcd=123349"

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60000)

        print("一覧タイトル:")
        print(page.title())

        # 宝塚歌劇 星組公演をクリック
        page.get_by_text("宝塚歌劇　星組公演").click()
        page.wait_for_load_state("networkidle", timeout=60000)

        print("詳細タイトル:")
        print(page.title())

        text = page.locator("body").inner_text(timeout=10000)
        print(text[:8000])

        browser.close()

if __name__ == "__main__":
    main()