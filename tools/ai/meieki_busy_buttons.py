#!/usr/bin/env python3
"""名駅周辺の繁忙ボタンと押下ログ記録。"""

from __future__ import annotations

import json
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


def build_meieki_busy_view(discord: Any) -> Any:
    class MeiekiBusyView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)
            for place in MEIEKI_BUSY_PLACES:
                button = discord.ui.Button(
                    label=place["label"],
                    emoji=place["emoji"],
                    style=discord.ButtonStyle.primary,
                    custom_id=place["custom_id"],
                )
                button.callback = self._make_callback(place)
                self.add_item(button)

        def _make_callback(self, place: dict[str, str]) -> Any:
            async def callback(interaction: Any) -> None:
                user = getattr(interaction, "user", None)
                channel = getattr(interaction, "channel", None)
                message = getattr(interaction, "message", None)
                append_busy_log(
                    place=place["place"],
                    label=place["label"],
                    user_id=str(getattr(user, "id", "")),
                    user_name=str(getattr(user, "display_name", user or "")),
                    channel_id=str(getattr(channel, "id", "")),
                    message_id=str(getattr(message, "id", "")),
                )
                await interaction.response.send_message("記録しました😇", ephemeral=True)

            return callback

    return MeiekiBusyView()


def message_text() -> str:
    return "🚖 名駅繁忙ボタン\n場所を押すと記録します。"
