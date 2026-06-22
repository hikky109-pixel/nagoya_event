import urllib.request
import re

URL = "https://tkj-i.co.jp/status/"


def get_johoku_status() -> list[str]:
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")

    messages = []

    texts = re.findall(r"<p>(.*?)</p>", html, flags=re.S)

    for text in texts:
        text = re.sub(r"<.*?>", "", text).strip()

        if text.startswith("このページでは"):
            continue

        if any(word in text for word in ["運転見合わせ", "運休", "遅延"]):
            messages.append(text)

    return messages


if __name__ == "__main__":
    print(get_johoku_status())
