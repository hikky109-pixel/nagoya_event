#!/usr/bin/env python3
"""Open-Meteoの6時間天気予報をDiscordへ投稿する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from tools.weather.get_openmeteo_forecast import get_openmeteo_forecast  # noqa: E402


STATE_PATH = ROOT / "data" / "weather" / "openmeteo_forecast_state.json"
JST = ZoneInfo("Asia/Tokyo")
REQUEST_TIMEOUT_SECONDS = 15


def setting(name: str) -> str:
    value = getattr(config, name, None)
    if value is None:
        return ""
    return str(value).strip()


def json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def forecast_line(row: dict[str, Any]) -> str:
    label = str(row.get("label") or "--:--")
    weather = str(row.get("weather") or "不明")
    temp = row.get("temperature_2m")
    precip = row.get("precipitation_probability")
    text = f"{label} {weather}"
    if temp is not None:
        text += f" {int(temp)}℃"
    if precip is not None and int(precip) >= 30:
        text += f" ☔{int(precip)}%"
    return text


def comment_for_forecast(rows: list[dict[str, Any]]) -> str:
    rainy_rows = [
        row
        for row in rows
        if int(row.get("precipitation_probability") or 0) >= 50 or str(row.get("weather") or "") in {"雨", "雷雨"}
    ]
    if rainy_rows:
        first = str(rainy_rows[0].get("label") or "")
        if first in {"18:00", "00:00"}:
            return "夕方以降はにわか雨の可能性があります😇"
        return "雨の可能性があります。空模様に注意してください😇"
    if any(int(row.get("temperature_2m") or 0) >= 35 for row in rows):
        return "日中はかなり暑くなりそうです。水分補給を忘れずに😇"
    return "大きな崩れは少なそうです😇"


def build_message(forecast: dict[str, Any]) -> str:
    rows = forecast.get("forecast") if isinstance(forecast.get("forecast"), list) else []
    lines = ["🌤️ 名古屋6時間天気", ""]
    if not rows:
        lines.append("予報を取得できませんでした。")
    else:
        lines.extend(forecast_line(row) for row in rows[:4] if isinstance(row, dict))
    lines.extend(["", "💬", comment_for_forecast([row for row in rows if isinstance(row, dict)])])
    return "\n".join(lines)


def post_discord(token: str, channel_id: str, content: str) -> tuple[bool, int, str]:
    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "nagoya-event-openmeteo/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return 200 <= int(response.status) < 300, int(response.status), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except OSError:
            body = str(exc)
        return False, int(exc.code), body
    except (OSError, urllib.error.URLError) as exc:
        return False, 0, str(exc)


def run(*, force: bool = False, hours: int = 24) -> dict[str, Any]:
    forecast = get_openmeteo_forecast(hours=hours)
    content = build_message(forecast)
    forecast_hash = json_hash({"forecast": forecast.get("forecast", [])})
    state = load_state()

    if not force and state.get("last_forecast_hash") == forecast_hash:
        return {"sent": False, "skipped": True, "reason": "duplicate", "hash": forecast_hash, "content": content}

    token = setting("DISCORD_BOT_TOKEN")
    channel_id = setting("WEATHER_ALERT_CHANNEL_ID")
    if not token or not channel_id:
        return {
            "sent": False,
            "skipped": True,
            "reason": "missing_discord_config",
            "channel_id_configured": bool(channel_id),
            "hash": forecast_hash,
            "content": content,
        }

    ok, status_code, body = post_discord(token, channel_id, content)
    if ok:
        state.update(
            {
                "last_forecast_hash": forecast_hash,
                "last_sent_at": datetime.now(JST).isoformat(timespec="seconds"),
                "last_sent": True,
            }
        )
        save_state(state)
    return {
        "sent": ok,
        "skipped": False,
        "status_code": status_code,
        "body": body,
        "hash": forecast_hash,
        "content": content,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open-Meteoの6時間天気予報をDiscordへ投稿する。")
    parser.add_argument("--force", action="store_true", help="重複判定を無視して投稿する。")
    parser.add_argument("--hours", type=int, default=24, help="取得する予報時間数。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(force=args.force, hours=args.hours)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("sent") or result.get("skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
