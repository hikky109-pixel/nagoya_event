import re
import urllib.request

URL = "https://www.guideway.co.jp/cgi_system/multieditor/info.cgi?action=data_view&key=1570909242316202&mode=operation_s"
NORMAL_MESSAGE = "平常通り運行しています"


def get_yutorito_status(suspend_only=True):
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    html = urllib.request.urlopen(req, timeout=15).read().decode("shift_jis", errors="ignore")

    messages = []

    h2_list = re.findall(r"<h2>(.*?)</h2>", html, flags=re.S)

    for h2 in h2_list:
        text = re.sub(r"<.*?>", "", h2).strip()
        text = " ".join(text.split())

        if not text:
            continue
        if text == NORMAL_MESSAGE:
            continue

        if suspend_only and not any(word in text for word in ["運休", "運転見合わせ", "運行休止"]):
            continue

        messages.append(text)

    return messages


if __name__ == "__main__":
    print(get_yutorito_status())