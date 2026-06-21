#!/usr/bin/env python3
"""ジェンマ課長日報をDiscord Bot APIで送信する。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "data" / "ai" / "gemma_report.txt"

sys.path.insert(0, str(ROOT))
import config  # noqa: E402


def get_setting(name: str) -> str:
    value = getattr(config, name, "")
    return value.strip() if isinstance(value, str) else str(value).strip()


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def post_report(token: str, channel_id: str, content: str) -> tuple[bool, int, str]:
    import requests

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {"content": content}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
    except requests.RequestException as exc:
        return False, 0, str(exc)

    return 200 <= response.status_code < 300, response.status_code, response.text


def main() -> int:
    token = get_setting("DISCORD_BOT_TOKEN")
    channel_id = get_setting("GEMMA_DISCORD_CHANNEL_ID")
    if not token or not channel_id:
        print("Gemma課長Discord API設定未完了")
        return 0

    content = read_report()
    ok, status_code, body = post_report(token, channel_id, content)
    if ok:
        print("Gemma課長Discord API送信成功")
    else:
        print(f"Gemma課長Discord API送信失敗: HTTP{status_code} {body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
