#!/usr/bin/env python3
"""名駅繁忙センサーの集計結果をDiscordへ投稿する。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ai.meieki_busy_buttons import SIGNALS_DIR  # noqa: E402
from tools.ai.meieki_busy_summary import build_busy_alert_message, read_recent_busy  # noqa: E402
from tools.ai.post_meieki_busy_buttons import default_channel_id, get_setting, load_env_file, normalize_channel_id  # noqa: E402


STATE_PATH = SIGNALS_DIR / "meieki_busy_summary_state.json"


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        with STATE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(message: str) -> None:
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump({"last_message": message}, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    load_env_file()
    token = get_setting("DISCORD_BOT_TOKEN")
    channel_id = normalize_channel_id(default_channel_id())
    if not token:
        print("名駅繁忙センサー投稿設定未完了: DISCORD_BOT_TOKEN")
        return 0
    if not channel_id:
        print("名駅繁忙センサー投稿設定未完了: GEMMA_CHANNEL_NAGOYA")
        return 0

    message = build_busy_alert_message(read_recent_busy(minutes=10))
    if message is None:
        print("名駅繁忙センサー通知なし")
        return 0
    if load_state().get("last_message") == message:
        print("名駅繁忙センサー重複通知スキップ")
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
        await channel.send(message)
        save_state(message)
        print("名駅繁忙センサー通知完了")
        await client.close()

    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
