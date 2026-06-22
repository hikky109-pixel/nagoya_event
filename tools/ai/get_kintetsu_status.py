

import re
import urllib.request

URL = "https://www.kintetsu.jp/unkou/unkou.html"
NORMAL_MESSAGE = "現在は１５分以上の列車の遅れはございません。"
TARGET_LINE = "名古屋線"


def _normalize_text(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ")
    return " ".join(text.split())


def get_kintetsu_status(abnormal_only=False, nagoya_line_only=False):
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    html = (
        urllib.request.urlopen(req, timeout=15)
        .read()
        .decode("shift_jis", errors="ignore")
    )

    messages = []

    for match in re.finditer(r'<font\s+size="\+1"[^>]*>(.*?)</font>', html, re.S | re.I):
        text = _normalize_text(match.group(1))
        if text:
            messages.append(text)

    if not messages:
        fallback = _normalize_text(html)
        if NORMAL_MESSAGE in fallback:
            messages = [NORMAL_MESSAGE]

    if abnormal_only:
        messages = [message for message in messages if message != NORMAL_MESSAGE]

    if nagoya_line_only:
        messages = [message for message in messages if TARGET_LINE in message]

    if not messages:
        return []

    return messages


if __name__ == "__main__":
    print(get_kintetsu_status())