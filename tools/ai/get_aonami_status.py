

import urllib.request
import xml.etree.ElementTree as ET

FEED_URL = "https://www.aonamiline.co.jp/railinfo/feed/"
NORMAL_MESSAGE = "ただいま、平常通り運転しております。"


def get_aonami_status(abnormal_only=False):
    req = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    xml_data = urllib.request.urlopen(req, timeout=15).read()
    root = ET.fromstring(xml_data)

    messages = []

    for item in root.findall("./channel/item"):
        desc = item.findtext("description", "").strip()
        if desc:
            messages.append(desc)

    if abnormal_only:
        messages = [m for m in messages if NORMAL_MESSAGE not in m]

    return messages


if __name__ == "__main__":
    print(get_aonami_status())