#!/usr/bin/env python3
"""Yahoo PlaceInfo テストボタンのViewと押下処理。"""

from __future__ import annotations

import asyncio
import json
import re
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from config import GPS_WEB_BASE_URL
from tools.location.get_yahoo_placeinfo import get_yahoo_placeinfo


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "location"
STATE_PATH = DATA_DIR / "placeinfo_coordinate_requests.json"
JST = ZoneInfo("Asia/Tokyo")
REQUEST_TTL = timedelta(minutes=10)
COORDINATE_PATTERN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
FAILURE_MESSAGE = "位置情報テストを開始できませんでした😇"


def message_text() -> str:
    return "\n".join(
        [
            "📍 Yahoo PlaceInfo テスト",
            "",
            "ブラウザで現在地を取得し、",
            "近くのランドマーク候補を取得します。",
        ]
    )


def is_placeinfo_test_message(content: str) -> bool:
    return str(content or "").strip() == message_text()


def parse_coordinate_text(value: str) -> tuple[float, float] | None:
    match = COORDINATE_PATTERN.match(str(value or ""))
    if match is None:
        return None
    lat = float(match.group(1))
    lon = float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _request_key(user_id: str, channel_id: str) -> str:
    return f"{channel_id}:{user_id}"


def _load_requests() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_requests(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _now() -> datetime:
    return datetime.now(JST)


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def remember_coordinate_request(*, user_id: str, channel_id: str, mode: str) -> None:
    requests = _load_requests()
    requests[_request_key(user_id, channel_id)] = {
        "mode": mode,
        "requested_at": _now().isoformat(timespec="seconds"),
    }
    _save_requests(requests)


def pop_coordinate_request(*, user_id: str, channel_id: str) -> dict[str, Any] | None:
    requests = _load_requests()
    key = _request_key(user_id, channel_id)
    request = requests.pop(key, None)
    _save_requests(requests)
    if not isinstance(request, dict):
        return None
    requested_at = _parse_time(request.get("requested_at"))
    if requested_at is None or _now() - requested_at > REQUEST_TTL:
        return None
    return request


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


async def run_placeinfo_for_coordinates(channel: Any, lat: float, lon: float, *, area: str = "coordinate") -> None:
    result = await asyncio.to_thread(get_yahoo_placeinfo, lat, lon, area=area)
    await channel.send(format_placeinfo_result(result))


async def handle_placeinfo_coordinate_message(message: Any) -> bool:
    coordinate = parse_coordinate_text(str(getattr(message, "content", "")))
    if coordinate is None:
        return False
    author = getattr(message, "author", None)
    channel = getattr(message, "channel", None)
    if author is None or channel is None:
        return False
    request = pop_coordinate_request(
        user_id=str(getattr(author, "id", "")),
        channel_id=str(getattr(channel, "id", "")),
    )
    if request is None:
        return False
    try:
        lat, lon = coordinate
        await run_placeinfo_for_coordinates(channel, lat, lon, area=str(request.get("mode") or "coordinate"))
    except Exception:
        traceback.print_exc()
        await channel.send(FAILURE_MESSAGE)
    return True


async def prompt_for_coordinates(interaction: Any, *, mode: str) -> None:
    user = getattr(interaction, "user", None)
    channel = getattr(interaction, "channel", None)
    if user is not None and channel is not None:
        remember_coordinate_request(
            user_id=str(getattr(user, "id", "")),
            channel_id=str(getattr(channel, "id", "")),
            mode=mode,
        )
    await interaction.response.send_message(
        "座標を送信してください: lat,lon\n例: 35.170915,136.881537",
        ephemeral=True,
    )


async def repost_placeinfo_button(interaction: Any, discord: Any) -> None:
    try:
        channel = getattr(interaction, "channel", None)
        if channel is None:
            await interaction.response.send_message(FAILURE_MESSAGE, ephemeral=True)
            return
        await send_placeinfo_test_button(channel, discord)
        original_message = getattr(interaction, "message", None)
        if original_message is not None:
            try:
                await original_message.delete()
            except Exception:
                print("placeinfo_repost_original_delete_failed", flush=True)
                traceback.print_exc()
        await interaction.response.send_message("📍 新しいPlaceInfoテストボタンを追加しました😇", ephemeral=True)
    except Exception:
        print("placeinfo_repost_failed", flush=True)
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message(FAILURE_MESSAGE, ephemeral=True)
        else:
            await interaction.followup.send(FAILURE_MESSAGE, ephemeral=True)


async def send_placeinfo_test_button(channel: Any, discord: Any) -> Any:
    return await channel.send(message_text(), view=build_placeinfo_test_view(discord))


def gps_web_url() -> str:
    base_url = str(GPS_WEB_BASE_URL or "").strip().rstrip("/")
    if not base_url:
        return ""
    if not base_url.endswith("/gps"):
        base_url = f"{base_url}/gps"
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("source", "discord")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_placeinfo_test_view(discord: Any) -> Any:
    class PlaceInfoTestView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)
            url = gps_web_url()
            if url:
                self.add_item(
                    discord.ui.Button(
                        label="📍 現在地からテスト",
                        style=discord.ButtonStyle.link,
                        url=url,
                    )
                )
            repost_button = discord.ui.Button(
                label="🔄 テストボタン再投稿",
                style=discord.ButtonStyle.secondary,
                custom_id="yahoo_placeinfo_test_repost",
            )
            repost_button.callback = self.repost_button
            self.add_item(repost_button)

        async def repost_button(self, interaction: Any) -> None:
            await repost_placeinfo_button(interaction, discord)

    return PlaceInfoTestView()
