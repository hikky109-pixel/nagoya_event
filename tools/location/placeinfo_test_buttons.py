#!/usr/bin/env python3
"""Yahoo PlaceInfo テストボタンのViewと押下処理。"""

from __future__ import annotations

import asyncio
import traceback
from typing import Any

from tools.location.get_yahoo_placeinfo import get_yahoo_placeinfo


PLACEINFO_TEST_POINTS = {
    "meieki": {
        "label": "名駅",
        "button_label": "名駅座標でテスト",
        "lat": 35.170915,
        "lon": 136.881537,
    },
    "sakae": {
        "label": "栄",
        "button_label": "栄座標でテスト",
        "lat": 35.168720,
        "lon": 136.908976,
    },
    "kanayama": {
        "label": "金山",
        "button_label": "金山座標でテスト",
        "lat": 35.142910,
        "lon": 136.901230,
    },
}


def message_text() -> str:
    return "\n".join(
        [
            "📍 Yahoo PlaceInfo テスト",
            "",
            "現在地または指定座標から",
            "近くのランドマーク候補を取得します。",
        ]
    )


def is_placeinfo_test_message(content: str) -> bool:
    return str(content or "").strip() == message_text()


def format_placeinfo_result(result: dict[str, Any]) -> str:
    lat = result.get("lat")
    lon = result.get("lon")
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []

    lines = [
        "📍 Yahoo PlaceInfo 結果",
        "",
        "座標:",
        f"{float(lat):.6f}, {float(lon):.6f}",
        "",
        "候補:",
    ]
    if not candidates:
        error = str(result.get("error") or "").strip()
        lines.append(f"取得候補なし{f'（{error}）' if error else ''}")
        return "\n".join(lines)

    for index, item in enumerate(candidates[:5], start=1):
        name = str(item.get("name") if isinstance(item, dict) else item).strip()
        if name:
            lines.append(f"{index}. {name}")
    return "\n".join(lines)


async def handle_placeinfo_interaction(interaction: Any, area: str) -> None:
    point = PLACEINFO_TEST_POINTS.get(area)
    if point is None:
        await interaction.response.send_message("座標設定が見つかりません", ephemeral=True)
        return

    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        result = await asyncio.to_thread(
            get_yahoo_placeinfo,
            float(point["lat"]),
            float(point["lon"]),
            area=area,
        )
        channel = getattr(interaction, "channel", None)
        if channel is None:
            await interaction.followup.send(format_placeinfo_result(result), ephemeral=True)
            return
        await channel.send(format_placeinfo_result(result))
    except Exception:
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("PlaceInfo取得に失敗しました", ephemeral=True)
        else:
            await interaction.followup.send("PlaceInfo取得に失敗しました", ephemeral=True)


def build_placeinfo_test_view(discord: Any) -> Any:
    class PlaceInfoTestView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)

        @discord.ui.button(
            label=PLACEINFO_TEST_POINTS["meieki"]["button_label"],
            style=discord.ButtonStyle.primary,
            custom_id="yahoo_placeinfo_test_meieki",
        )
        async def meieki_button(self, interaction: Any, button: Any) -> None:
            await handle_placeinfo_interaction(interaction, "meieki")

        @discord.ui.button(
            label=PLACEINFO_TEST_POINTS["sakae"]["button_label"],
            style=discord.ButtonStyle.primary,
            custom_id="yahoo_placeinfo_test_sakae",
        )
        async def sakae_button(self, interaction: Any, button: Any) -> None:
            await handle_placeinfo_interaction(interaction, "sakae")

        @discord.ui.button(
            label=PLACEINFO_TEST_POINTS["kanayama"]["button_label"],
            style=discord.ButtonStyle.primary,
            custom_id="yahoo_placeinfo_test_kanayama",
        )
        async def kanayama_button(self, interaction: Any, button: Any) -> None:
            await handle_placeinfo_interaction(interaction, "kanayama")

    return PlaceInfoTestView()
