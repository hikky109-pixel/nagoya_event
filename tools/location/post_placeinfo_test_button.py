#!/usr/bin/env python3
"""Yahoo PlaceInfo テストボタンをDiscordへ投稿する。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "location"
STATE_PATH = DATA_DIR / "placeinfo_test_button_state.json"
JST = ZoneInfo("Asia/Tokyo")
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from tools.location.placeinfo_test_buttons import (  # noqa: E402
    is_placeinfo_test_message,
    send_placeinfo_test_button,
)


def get_setting(name: str) -> str:
    value = getattr(config, name, None)
    if value is None:
        return ""
    return str(value).strip()


def normalize_channel_id(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    return value if value.isdigit() else ""


def now_jst() -> datetime:
    return datetime.now(JST)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(message_id: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "last_posted_at": now_jst().isoformat(timespec="seconds"),
        "message_id": message_id,
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_state_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def posted_within_last_hour() -> bool:
    parsed = parse_state_time(load_state().get("last_posted_at"))
    return parsed is not None and now_jst() - parsed < timedelta(hours=1)


async def visible_button_message_exists(channel: Any, client_user: Any) -> bool:
    async for message in channel.history(limit=5):
        if not is_placeinfo_test_message(str(getattr(message, "content", ""))):
            continue
        if getattr(message, "author", None) == client_user:
            return True
    return False


async def post_placeinfo_test_button(channel: Any, discord: Any) -> Any:
    sent = await send_placeinfo_test_button(channel, discord)
    save_state(str(getattr(sent, "id", "")))
    return sent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yahoo PlaceInfo テストボタンを投稿する。")
    parser.add_argument("--force", action="store_true", help="再掲制限を無視して強制投稿する。")
    parser.add_argument("--channel-id", default="", help="投稿先DiscordチャンネルID。通常は設定値を使う。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = get_setting("DISCORD_BOT_TOKEN")
    channel_id = normalize_channel_id(args.channel_id) or normalize_channel_id(
        get_setting("YAHOO_PLACEINFO_TEST_CHANNEL_ID")
    )

    if not token:
        print("Yahoo PlaceInfoテストボタン投稿設定未完了: DISCORD_BOT_TOKEN")
        return 0
    if not channel_id:
        print("Yahoo PlaceInfoテストボタン投稿設定未完了: YAHOO_PLACEINFO_TEST_CHANNEL_ID")
        return 0
    if not get_setting("YAHOO_CLIENT_ID"):
        print("Yahoo PlaceInfoテストボタン投稿設定未完了: YAHOO_CLIENT_ID")
        return 0
    if not get_setting("GPS_WEB_BASE_URL"):
        print("Yahoo PlaceInfoテストボタン投稿設定未完了: GPS_WEB_BASE_URL")
        return 0
    if not args.force and posted_within_last_hour():
        print("Yahoo PlaceInfoテストボタン再掲スキップ: last_posted_within_1h")
        return 0

    try:
        import discord
    except ImportError:
        print("discord.py未インストール")
        return 0

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        channel = client.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await client.fetch_channel(int(channel_id))
            except Exception:
                print(f"投稿先チャンネルが見つかりません: {channel_id}")
                await client.close()
                return

        if not args.force and await visible_button_message_exists(channel, client.user):
            print("Yahoo PlaceInfoテストボタン再掲スキップ: visible_in_recent_5")
            await client.close()
            return

        await post_placeinfo_test_button(channel, discord)
        print("Yahoo PlaceInfoテストボタン投稿完了")
        await client.close()

    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
