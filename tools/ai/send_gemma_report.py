#!/usr/bin/env python3
"""ジェンマ課長日報をDiscord webhookへ送信する。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "data" / "ai" / "gemma_report.txt"

sys.path.insert(0, str(ROOT))
import config  # noqa: E402


def get_webhook_url() -> str:
    webhook = getattr(config, "GEMMA_DISCORD_WEBHOOK", "") or getattr(config, "GEMMA_WEBHOOK_URL", "")
    return webhook.strip() if isinstance(webhook, str) else ""


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def post_report(webhook_url: str, content: str) -> bool:
    import requests

    payload: dict[str, Any] = {"content": content}
    try:
        response = requests.post(webhook_url, json=payload, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        return False
    return True


def main() -> int:
    webhook_url = get_webhook_url()
    if not webhook_url:
        print("Gemma課長Webhook未設定")
        return 0

    content = read_report()
    if post_report(webhook_url, content):
        print("Gemma課長日報送信成功")
    else:
        print("Gemma課長日報送信失敗")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
