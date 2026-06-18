from playwright.sync_api import sync_playwright

URL = "https://www.e-tix.jp/misonoza/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.on(
        "response",
        lambda response: print(response.url)
        if "calendar" in response.url.lower() or "json" in response.url.lower()
        else None
    )

    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.goto(URL, wait_until="networkidle", timeout=60000)

    print(page.locator("body").inner_text()[:3000])

    print("TITLE:", page.title())
    print("URL:", page.url)

    browser.close()