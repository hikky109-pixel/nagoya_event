#!/usr/bin/env python3
"""気象庁ベースの天気速報βをDiscordへ送信する。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

try:
    from tools.weather.weather_normalizer import get_all_weather_snapshot
except ModuleNotFoundError:
    from weather_normalizer import get_all_weather_snapshot


STATE_PATH = ROOT / "state" / "weather_alert_state.json"
WEATHER_ALERT_LEVELS = (
    (30.0, 4, "🌀 災害警戒"),
    (20.0, 3, "🚨 豪雨警戒"),
    (10.0, 2, "⚠️ 大雨注意"),
    (5.0, 1, "☔ 強雨注意"),
)


def _setting(name: str) -> str:
    value = getattr(config, name, None)
    if value is None:
        return ""
    return str(value).strip()


def _load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def max_precipitation_from_snapshot(snapshot: dict[str, Any]) -> float:
    raw_yahoo = snapshot.get("raw_yahoo")
    if isinstance(raw_yahoo, dict):
        return _float_value(raw_yahoo.get("max_precip_mm"))

    sources = snapshot.get("sources")
    if isinstance(sources, dict):
        yahoo = sources.get("YahooWeather")
        if isinstance(yahoo, dict):
            return _float_value(yahoo.get("max_precip_mm"))
    return 0.0


def weather_alert_level(rain_mm: float) -> int:
    for threshold, level, _title in WEATHER_ALERT_LEVELS:
        if rain_mm >= threshold:
            return level
    return 0


def weather_alert_title(level: int) -> str:
    for _threshold, candidate_level, title in WEATHER_ALERT_LEVELS:
        if candidate_level == level:
            return title
    return ""


def build_weather_alert_message(level: int, rain_mm: float) -> str:
    if level <= 0:
        return "☀️ 雨は弱まりました。\n現在の予測雨量は5mm/h未満です。"
    title = weather_alert_title(level)
    return f"{title}\n名古屋中心部で1時間以内に{rain_mm:.1f}mm/h予測。"


def should_notify_weather_level(previous_level: int, current_level: int, *, force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "force"
    if previous_level > 0 and current_level == 0:
        return True, "rain_ended"
    if current_level > 0 and current_level != previous_level:
        return True, "level_changed"
    return False, "same_level" if current_level == previous_level else "below_threshold"


def post_discord(token: str, channel_id: str, content: str) -> tuple[bool, int, str]:
    import requests

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json={"content": content}, timeout=15)
    except requests.RequestException as exc:
        return False, 0, str(exc)
    return 200 <= response.status_code < 300, response.status_code, response.text


def run(*, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    snapshot = get_all_weather_snapshot()
    state = _load_state()
    previous_level = int(state.get("level", 0) or 0)
    rain_mm = max_precipitation_from_snapshot(snapshot)
    current_level = weather_alert_level(rain_mm)
    should_notify, reason = should_notify_weather_level(previous_level, current_level, force=force)

    if not should_notify:
        return {
            "sent": False,
            "skipped": True,
            "reason": reason,
            "level": current_level,
            "previous_level": previous_level,
            "rain_mm": rain_mm,
        }

    content = build_weather_alert_message(current_level, rain_mm)
    if dry_run:
        print(content)
        return {
            "sent": False,
            "skipped": True,
            "reason": "dry_run",
            "level": current_level,
            "previous_level": previous_level,
            "rain_mm": rain_mm,
            "content": content,
        }

    token = _setting("DISCORD_BOT_TOKEN")
    channel_id = _setting("WEATHER_ALERT_CHANNEL_ID")
    if not token or not channel_id:
        return {
            "sent": False,
            "skipped": True,
            "reason": "missing_discord_config",
            "level": current_level,
            "previous_level": previous_level,
            "rain_mm": rain_mm,
            "channel_id_configured": bool(channel_id),
        }

    ok, status_code, body = post_discord(token, channel_id, content)
    if ok:
        _save_state(
            {
                "level": current_level,
                "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            }
        )
    return {
        "sent": ok,
        "skipped": False,
        "status_code": status_code,
        "body": body,
        "level": current_level,
        "previous_level": previous_level,
        "rain_mm": rain_mm,
        "reason": reason,
        "content": content,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="気象庁ベースの天気速報βを送信する。")
    parser.add_argument("--force", action="store_true", help="重複判定を無視し、手動テスト送信を許可する。")
    parser.add_argument("--dry-run", action="store_true", help="Discordへ送らず本文と判定だけ確認する。")
    args = parser.parse_args()

    result = run(force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("sent") or result.get("skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
