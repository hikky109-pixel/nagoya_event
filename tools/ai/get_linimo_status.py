import re
import urllib.request

URL = "https://www.linimo.jp/delay/"


def get_linimo_status():
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")

    messages = []

    texts = re.findall(r'<p class="hm_bodytext_l">(.*?)</p>', html, flags=re.S)

    for text in texts:
        text = re.sub(r"<.*?>", "", text).strip()
        text = " ".join(text.split())

        if not text:
            continue
        if text.startswith("リニモは、事故・災害等で30分以上"):
            continue
        if text.startswith("[ 最終更新"):
            continue
        if "概ね5分以上の遅延" in text:
            continue

        messages.append(text)

    return messages


if __name__ == "__main__":
    print(get_linimo_status())