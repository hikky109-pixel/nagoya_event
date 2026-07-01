#!/usr/bin/env python3
"""ジェンマ課長コメントをDiscord Bot APIで送信する。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
COMMENT_PATH = ROOT / "data" / "ai" / "gemma_comment.txt"
COMMENT_JSON_PATH = ROOT / "data" / "ai" / "gemma_comment.json"
SEND_STATE_PATH = ROOT / "data" / "ai" / "gemma_comment_send_state.json"

sys.path.insert(0, str(ROOT))
import config  # noqa: E402

try:
    from log_utils import log
except ModuleNotFoundError:
    from tools.ai.log_utils import log


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


def load_send_state() -> dict[str, Any]:
    if not SEND_STATE_PATH.exists():
        return {}
    try:
        with SEND_STATE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_send_state(state: dict[str, Any]) -> None:
    SEND_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SEND_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def send_dedupe_key(meta: dict[str, Any], channel_key: str, content: str) -> str:
    if channel_key == "railway":
        official_hash = str(meta.get("railway_official_hash") or "").strip()
        if official_hash:
            return f"railway:{official_hash}:{content_hash(content)}"
    return f"{channel_key}:{content_hash(content)}"


def has_railway_beta_alerts(meta: dict[str, Any]) -> bool:
    if meta.get("railway_beta_notification"):
        return True
    alerts = meta.get("railway_beta_alerts")
    return isinstance(alerts, list) and any(str(alert or "").strip() for alert in alerts)


def has_weather_beta_alerts(meta: dict[str, Any]) -> bool:
    if meta.get("weather_beta_notification"):
        return True
    alerts = meta.get("weather_beta_alerts")
    return isinstance(alerts, list) and any(str(alert or "").strip() for alert in alerts)


def target_channel_id(meta: dict[str, Any]) -> tuple[str, str]:
    if has_railway_beta_alerts(meta):
        railway_channel_id = get_setting("GEMMA_CHANNEL_RAILWAY")
        if railway_channel_id:
            return railway_channel_id, "railway"
    if has_weather_beta_alerts(meta):
        weather_channel_id = get_setting("WEATHER_ALERT_CHANNEL_ID")
        if weather_channel_id:
            return weather_channel_id, "weather"
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
        log("Gemma課長Discord API設定未完了")
        return 0

    content = read_comment()
    if not content.strip():
        log("Gemma課長コメントなし: 送信スキップ source=send_gemma_comment_api")
        return 0

    dedupe_key = send_dedupe_key(meta, channel_key, content)
    send_state = load_send_state()
    if send_state.get("last_sent_key") == dedupe_key:
        log(
            "Gemma課長コメント送信スキップ: duplicate "
            f"source=send_gemma_comment_api channel={channel_key} key={dedupe_key}"
        )
        return 0

    ok, status_code, body = post_comment(token, channel_id, content)
    if ok:
        send_state.update(
            {
                "last_sent_key": dedupe_key,
                "last_channel": channel_key,
                "last_railway_official_hash": str(meta.get("railway_official_hash") or ""),
            }
        )
        save_send_state(send_state)
        log(
            "Gemma課長コメントDiscord API送信成功: "
            f"{channel_key} source=send_gemma_comment_api key={dedupe_key}"
        )
    else:
        log(
            "Gemma課長コメントDiscord API送信失敗: "
            f"HTTP{status_code} {body} source=send_gemma_comment_api channel={channel_key}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
