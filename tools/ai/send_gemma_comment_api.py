#!/usr/bin/env python3
"""ジェンマ課長コメントをDiscord Bot APIで送信する。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
COMMENT_PATH = ROOT / "data" / "ai" / "gemma_comment.txt"
COMMENT_JSON_PATH = ROOT / "data" / "ai" / "gemma_comment.json"

sys.path.insert(0, str(ROOT))
import config  # noqa: E402


def get_setting(name: str) -> str:
    value = getattr(config, name, "")
    return value.strip() if isinstance(value, str) else str(value).strip()


def read_comment() -> str:
    return COMMENT_PATH.read_text(encoding="utf-8")


def read_comment_meta() -> dict[str, Any]:
    if not COMMENT_JSON_PATH.exists():
        return {}
    try:
        with COMMENT_JSON_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def has_railway_beta_alerts(meta: dict[str, Any]) -> bool:
    if meta.get("railway_beta_notification"):
        return True
    alerts = meta.get("railway_beta_alerts")
    return isinstance(alerts, list) and any(str(alert or "").strip() for alert in alerts)


def target_channel_id(meta: dict[str, Any]) -> tuple[str, str]:
    if has_railway_beta_alerts(meta):
        railway_channel_id = get_setting("GEMMA_CHANNEL_RAILWAY")
        if railway_channel_id:
            return railway_channel_id, "railway"
    return get_setting("GEMMA_DISCORD_CHANNEL_ID"), "main"


def post_comment(token: str, channel_id: str, content: str) -> tuple[bool, int, str]:
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
    meta = read_comment_meta()
    channel_id, channel_key = target_channel_id(meta)
    if not token or not channel_id:
        print("Gemma課長Discord API設定未完了")
        return 0

    content = read_comment()
    if not content.strip():
        print("Gemma課長コメントなし: 送信スキップ")
        return 0

    ok, status_code, body = post_comment(token, channel_id, content)
    if ok:
        print(f"Gemma課長コメントDiscord API送信成功: {channel_key}")
    else:
        print(f"Gemma課長コメントDiscord API送信失敗: HTTP{status_code} {body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
