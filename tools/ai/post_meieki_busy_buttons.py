#!/usr/bin/env python3
"""名駅繁忙ボタンをDiscordへ投稿する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from tools.ai.meieki_busy_buttons import build_meieki_busy_view, message_text  # noqa: E402


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="名駅繁忙ボタンをDiscordへ投稿する。")
    parser.add_argument("--channel-id", default=default_channel_id(), help="投稿先DiscordチャンネルID。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = get_setting("DISCORD_BOT_TOKEN")
    channel_id = normalize_channel_id(str(args.channel_id))
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
            print(f"投稿先チャンネルが見つかりません: {channel_id}")
            await client.close()
            return
        await channel.send(message_text(), view=build_meieki_busy_view(discord))
        print("名駅繁忙ボタン投稿完了")
        await client.close()

    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
