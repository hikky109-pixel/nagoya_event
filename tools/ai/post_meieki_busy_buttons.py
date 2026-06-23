#!/usr/bin/env python3
"""名駅繁忙ボタンをDiscordへ投稿する。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SIGNALS_DIR = ROOT / "data" / "signals"
STATE_PATH = SIGNALS_DIR / "meieki_busy_button_state.json"
JST = ZoneInfo("Asia/Tokyo")
sys.path.insert(0, str(ROOT))


def load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
    except ImportError:
        load_env_file_simple(env_path)
        return
    load_dotenv(env_path)


def load_env_file_simple(env_path: Path) -> None:
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()

import config  # noqa: E402
from tools.ai.meieki_busy_buttons import (  # noqa: E402
    build_meieki_busy_view,
    followup_message_text,
    is_meieki_busy_button_message,
    message_text,
)
from tools.ai.meieki_busy_followup import (  # noqa: E402
    FOLLOWUP_STATE_PATH,
    followup_source_matches_button_state,
    load_followup_state,
    mark_followup_done,
    schedule_followup_if_needed,
    should_post_followup,
)


def get_setting(name: str) -> str:
    value = getattr(config, name, "")
    return value.strip() if isinstance(value, str) else str(value).strip()


def normalize_channel_id(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    return value if value.isdigit() else ""


def default_channel_id() -> str:
    direct = normalize_channel_id(get_setting("GEMMA_CHANNEL_NAGOYA"))
    if direct:
        return direct

    channels = getattr(config, "GEMMA_CHANNELS", {}) or {}
    if isinstance(channels, dict):
        nagoya = normalize_channel_id(str(channels.get("nagoya", "")).strip())
        if nagoya:
            return nagoya
    return ""


def now_jst() -> datetime:
    return datetime.now(JST)


def is_active_hours() -> bool:
    hour = now_jst().hour
    return 6 <= hour < 24 or 0 <= hour < 1


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        with STATE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(message_id: str) -> None:
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "last_posted_at": now_jst().isoformat(timespec="seconds"),
        "message_id": message_id,
    }
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_state_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def posted_within_last_hour() -> bool:
    last_posted_at = str(load_state().get("last_posted_at", ""))
    parsed = parse_state_time(last_posted_at)
    if parsed is None:
        return False
    return now_jst() - parsed < timedelta(hours=1)


async def visible_button_message_exists(channel: Any, client_user: Any) -> bool:
    async for message in channel.history(limit=5):
        if not is_meieki_busy_button_message(str(getattr(message, "content", ""))):
            continue
        author = getattr(message, "author", None)
        if author == client_user:
            return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="名駅繁忙ボタンをDiscordへ投稿する。")
    parser.add_argument("--channel-id", default="", help="投稿先DiscordチャンネルID。")
    parser.add_argument(
        "--force",
        action="store_true",
        help="稼働時間や再掲制限を無視して強制投稿する。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = get_setting("DISCORD_BOT_TOKEN")
    channel_id = normalize_channel_id(str(args.channel_id)) or default_channel_id()
    if not args.force and not is_active_hours():
        print("名駅繁忙ボタン再掲停止時間")
        return 0
    if not token:
        print("名駅繁忙ボタン投稿設定未完了: DISCORD_BOT_TOKEN")
        return 0
    if not channel_id:
        print("名駅繁忙ボタン投稿設定未完了: GEMMA_CHANNEL_NAGOYA")
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
        if await visible_button_message_exists(channel, client.user):
            print("名駅繁忙ボタン再掲スキップ: visible_in_recent_5")
            await client.close()
            return

        if not args.force:
            button_state = load_state()
            followup_state = load_followup_state()
            if should_post_followup(followup_state, now_jst()):
                if not followup_source_matches_button_state(followup_state, button_state):
                    mark_followup_done(followup_state, posted_at=now_jst())
                    print("名駅繁忙確認ボタン再掲スキップ: stale_followup")
                    await client.close()
                    return
                sent = await channel.send(followup_message_text(), view=build_meieki_busy_view(discord))
                save_state(str(getattr(sent, "id", "")))
                mark_followup_done(followup_state, message_id=str(getattr(sent, "id", "")), posted_at=now_jst())
                print("名駅繁忙確認ボタン再掲完了: followup")
                await client.close()
                return

            if posted_within_last_hour():
                scheduled = schedule_followup_if_needed(
                    button_state=button_state,
                    existing_followup_state=followup_state,
                    now=now_jst(),
                )
                if scheduled is not None:
                    print(f"名駅繁忙確認ボタン予約: {FOLLOWUP_STATE_PATH.relative_to(ROOT)}")
                else:
                    print("名駅繁忙ボタン再掲スキップ: last_posted_within_1h")
                await client.close()
                return

        sent = await channel.send(message_text(), view=build_meieki_busy_view(discord))
        save_state(str(getattr(sent, "id", "")))
        print("名駅繁忙ボタン投稿完了")
        await client.close()

    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
