#!/usr/bin/env python3
"""名駅周辺の繁忙ボタンと押下ログ記録。"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SIGNALS_DIR = ROOT / "data" / "signals"
LOG_PATH = SIGNALS_DIR / "meieki_busy_log.jsonl"
JST = ZoneInfo("Asia/Tokyo")
CANCEL_CUSTOM_ID = "meieki_busy_cancel"
CANCEL_WINDOW = timedelta(minutes=5)

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


def parse_jst_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


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
    timestamp = now_jst_iso()
    row = {
        "type": "report",
        "ts": timestamp,
        "timestamp": timestamp,
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


def append_cancel_log(*, original_id: str, user_id: str, user_name: str) -> None:
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "type": "cancel",
        "original_id": original_id,
        "user": user_name,
        "user_id": user_id,
        "timestamp": now_jst_iso(),
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False))
        f.write("\n")


def read_busy_log_rows() -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def find_report_row(original_id: str) -> dict[str, Any] | None:
    for row in reversed(read_busy_log_rows()):
        if row.get("type") == "cancel":
            continue
        if str(row.get("message_id", "")) == original_id:
            return row
    return None


def cancelled_original_ids() -> set[str]:
    ids: set[str] = set()
    for row in read_busy_log_rows():
        if row.get("type") == "cancel":
            original_id = str(row.get("original_id", ""))
            if original_id:
                ids.add(original_id)
    return ids


def is_report_cancelled(original_id: str) -> bool:
    return original_id in cancelled_original_ids()


def cancel_message_text(row: dict[str, Any]) -> str:
    place = str(row.get("place", ""))
    label = str(row.get("label", ""))
    emoji = str(PLACE_BY_ID.get(place, {}).get("emoji", ""))
    user_name = str(row.get("user_name", ""))
    place_line = f"{emoji} {label}".strip()
    return "\n".join(
        [
            "🚕 名駅繁忙報告（取消）",
            "",
            place_line,
            f"報告: {user_name}",
        ]
    ).strip()


async def handle_busy_interaction(interaction: Any, place: str, label: str, discord: Any) -> None:
    try:
        user = getattr(interaction, "user", None)
        channel = getattr(interaction, "channel", None)
        emoji = str(PLACE_BY_ID.get(place, {}).get("emoji", ""))
        user_name = str(getattr(user, "display_name", user or ""))
        if channel is None:
            raise RuntimeError("interaction channel is missing")
        sent = await channel.send(
            f"🚕 名駅繁忙報告: {emoji} {label} / 報告: {user_name}".strip(),
            view=build_meieki_busy_cancel_view(discord),
        )
        append_busy_log(
            place=place,
            label=label,
            user_id=str(getattr(user, "id", "")),
            user_name=user_name,
            channel_id=str(getattr(channel, "id", "")),
            message_id=str(getattr(sent, "id", "")),
        )
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
    except Exception:
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("記録に失敗しました", ephemeral=True)


async def handle_cancel_interaction(interaction: Any, discord: Any) -> None:
    try:
        user = getattr(interaction, "user", None)
        message = getattr(interaction, "message", None)
        original_id = str(getattr(message, "id", ""))
        user_id = str(getattr(user, "id", ""))
        user_name = str(getattr(user, "display_name", user or ""))
        row = find_report_row(original_id)
        if row is None:
            await interaction.response.send_message("取消対象が見つかりません", ephemeral=True)
            return
        if str(row.get("user_id", "")) != user_id:
            await interaction.response.send_message("報告者本人のみ取り消せます", ephemeral=True)
            return
        reported_at = parse_jst_ts(str(row.get("ts") or row.get("timestamp") or ""))
        if reported_at is None or datetime.now(JST) - reported_at > CANCEL_WINDOW:
            await interaction.response.send_message("取消期限切れ", ephemeral=True)
            return
        if is_report_cancelled(original_id):
            await interaction.response.send_message("この報告は取消済みです", ephemeral=True)
            return

        append_cancel_log(original_id=original_id, user_id=user_id, user_name=user_name)
        await message.edit(content=cancel_message_text(row), view=build_meieki_busy_cancel_view(discord, disabled=True))
        await interaction.response.send_message("取消しました", ephemeral=True)
    except Exception:
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("取消に失敗しました", ephemeral=True)


def build_meieki_busy_cancel_view(discord: Any, *, disabled: bool = False) -> Any:
    class MeiekiBusyCancelView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)
            if disabled:
                for item in self.children:
                    item.disabled = True

        @discord.ui.button(
            label="取り消し",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=CANCEL_CUSTOM_ID,
        )
        async def cancel_button(self, interaction: Any, button: Any) -> None:
            await handle_cancel_interaction(interaction, discord)

    return MeiekiBusyCancelView()


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
            await handle_busy_interaction(interaction, "sakuradori", "桜通口", discord)

        @discord.ui.button(
            label="太閤通口",
            emoji="🚄",
            style=discord.ButtonStyle.primary,
            custom_id="meieki_busy_taiko",
        )
        async def taiko_button(self, interaction: Any, button: Any) -> None:
            await handle_busy_interaction(interaction, "taiko", "太閤通口", discord)

        @discord.ui.button(
            label="名鉄／近鉄乗り場",
            emoji="🚃",
            style=discord.ButtonStyle.primary,
            custom_id="meieki_busy_meitetsu_kintetsu",
        )
        async def meitetsu_kintetsu_button(self, interaction: Any, button: Any) -> None:
            await handle_busy_interaction(interaction, "meitetsu_kintetsu", "名鉄／近鉄乗り場", discord)

        @discord.ui.button(
            label="ミッドランド前",
            emoji="🏢",
            style=discord.ButtonStyle.primary,
            custom_id="meieki_busy_midland",
        )
        async def midland_button(self, interaction: Any, button: Any) -> None:
            await handle_busy_interaction(interaction, "midland", "ミッドランド前", discord)

    return MeiekiBusyView()


def message_text() -> str:
    return (
        "📍 名駅繁忙報告\n"
        "場所を押すと投稿します"
    )
