import re
import urllib.request


URL = "https://top.meitetsu.co.jp/em/"


def get_meitetsu_status():
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    html = (
        urllib.request.urlopen(req, timeout=15)
        .read()
        .decode("utf-8", errors="ignore")
    )

    m = re.search(
        r'<p class="emLv00" id="descriptionText">(.*?)</p>',
        html,
        re.S
    )

    if not m:
        return None

    text = re.sub(r"<.*?>", "", m.group(1))
    text = " ".join(text.split())

    return text


if __name__ == "__main__":
    print(get_meitetsu_status())