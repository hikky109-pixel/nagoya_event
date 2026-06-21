#!/usr/bin/env python3
"""名駅周辺の繁忙ボタンと押下ログ記録。"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SIGNALS_DIR = ROOT / "data" / "signals"
LOG_PATH = SIGNALS_DIR / "meieki_busy_log.jsonl"
JST = ZoneInfo("Asia/Tokyo")

MEIEKI_BUSY_PLACES = (
    {
        "place": "sakuradori",
        "label": "桜通口",
        "emoji": "🌸",
        "custom_id": "meieki_busy_sakuradori",
    },
    {
        "place": "taiko",
        "label": "太閤通口",
        "emoji": "🚄",
        "custom_id": "meieki_busy_taiko",
    },
    {
        "place": "meitetsu_kintetsu",
        "label": "名鉄／近鉄乗り場",
        "emoji": "🚃",
        "custom_id": "meieki_busy_meitetsu_kintetsu",
    },
    {
        "place": "midland",
        "label": "ミッドランド前",
        "emoji": "🏢",
        "custom_id": "meieki_busy_midland",
    },
)
PLACE_BY_ID = {place["place"]: place for place in MEIEKI_BUSY_PLACES}


def now_jst_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def append_busy_log(
    *,
    place: str,
    label: str,
    user_id: str,
    user_name: str,
    channel_id: str,
    message_id: str,
) -> None:
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": now_jst_iso(),
        "place": place,
        "label": label,
        "user_id": user_id,
        "user_name": user_name,
        "channel_id": channel_id,
        "message_id": message_id,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False))
        f.write("\n")


async def handle_busy_interaction(interaction: Any, place: str, label: str) -> None:
    try:
        user = getattr(interaction, "user", None)
        channel = getattr(interaction, "channel", None)
        message = getattr(interaction, "message", None)
        emoji = str(PLACE_BY_ID.get(place, {}).get("emoji", ""))
        user_name = str(getattr(user, "display_name", user or ""))
        append_busy_log(
            place=place,
            label=label,
            user_id=str(getattr(user, "id", "")),
            user_name=user_name,
            channel_id=str(getattr(channel, "id", "")),
            message_id=str(getattr(message, "id", "")),
        )
        if channel is None:
            raise RuntimeError("interaction channel is missing")
        await channel.send(f"🚕 名駅繁忙報告: {emoji} {label} / 報告: {user_name}".strip())
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
    except Exception:
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("記録に失敗しました", ephemeral=True)


def build_meieki_busy_view(discord: Any) -> Any:
    class MeiekiBusyView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)

        @discord.ui.button(
            label="桜通口",
            emoji="🌸",
            style=discord.ButtonStyle.primary,
            custom_id="meieki_busy_sakuradori",
        )
        async def sakuradori_button(self, interaction: Any, button: Any) -> None:
            await handle_busy_interaction(interaction, "sakuradori", "桜通口")

        @discord.ui.button(
            label="太閤通口",
            emoji="🚄",
            style=discord.ButtonStyle.primary,
            custom_id="meieki_busy_taiko",
        )
        async def taiko_button(self, interaction: Any, button: Any) -> None:
            await handle_busy_interaction(interaction, "taiko", "太閤通口")

        @discord.ui.button(
            label="名鉄／近鉄乗り場",
            emoji="🚃",
            style=discord.ButtonStyle.primary,
            custom_id="meieki_busy_meitetsu_kintetsu",
        )
        async def meitetsu_kintetsu_button(self, interaction: Any, button: Any) -> None:
            await handle_busy_interaction(interaction, "meitetsu_kintetsu", "名鉄／近鉄乗り場")

        @discord.ui.button(
            label="ミッドランド前",
            emoji="🏢",
            style=discord.ButtonStyle.primary,
            custom_id="meieki_busy_midland",
        )
        async def midland_button(self, interaction: Any, button: Any) -> None:
            await handle_busy_interaction(interaction, "midland", "ミッドランド前")

    return MeiekiBusyView()


def message_text() -> str:
    return (
        "📍 名駅繁忙報告\n"
        "場所を押すと投稿します"
    )
