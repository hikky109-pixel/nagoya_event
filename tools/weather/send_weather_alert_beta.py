#!/usr/bin/env python3
"""状態遷移ベースの天気速報βをDiscordへ送信する。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

try:
    from tools.weather.weather_state import (
        DEFAULT_STATE_PATH as STATE_PATH,
        evaluate_weather_state,
        get_current_values,
        jma_active_advisories_from_snapshot,
        jma_debug_logs_from_snapshot,
        load_state,
        save_state,
    )
except ModuleNotFoundError:
    from weather_state import (
        DEFAULT_STATE_PATH as STATE_PATH,
        evaluate_weather_state,
        get_current_values,
        jma_active_advisories_from_snapshot,
        jma_debug_logs_from_snapshot,
        load_state,
        save_state,
    )


def _setting(name: str) -> str:
    value = getattr(config, name, None)
    if value is None:
        return ""
    return str(value).strip()


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
    state = load_state(STATE_PATH)
    rain_mm, wind_mps, snapshot, source_logs = get_current_values()
    jma_advisories = jma_active_advisories_from_snapshot(snapshot)
    updated_state, messages, decision_logs = evaluate_weather_state(
        state,
        rain_mm=rain_mm,
        wind_mps=wind_mps,
        jma_advisories=jma_advisories,
    )
    logs = source_logs + jma_debug_logs_from_snapshot(snapshot, jma_advisories) + decision_logs
    for message in logs:
        print(message, flush=True)

    if not messages and not force:
        save_state(updated_state, STATE_PATH)
        return {
            "sent": False,
            "skipped": True,
            "reason": "no_state_transition",
            "rain_mm": rain_mm,
            "wind_mps": wind_mps,
            "logs": logs,
            "state": updated_state,
        }

    content = "\n\n".join(messages) if messages else "☔ 天気速報βテスト\n状態遷移通知の送信テストです。"
    if dry_run:
        print(content)
        return {
            "sent": False,
            "skipped": True,
            "reason": "dry_run",
            "rain_mm": rain_mm,
            "wind_mps": wind_mps,
            "content": content,
            "logs": logs,
            "state": updated_state,
        }

    token = _setting("DISCORD_BOT_TOKEN")
    channel_id = _setting("WEATHER_ALERT_CHANNEL_ID")
    if not token or not channel_id:
        return {
            "sent": False,
            "skipped": True,
            "reason": "missing_discord_config",
            "rain_mm": rain_mm,
            "wind_mps": wind_mps,
            "content": content,
            "channel_id_configured": bool(channel_id),
            "logs": logs,
            "state": updated_state,
        }

    ok, status_code, body = post_discord(token, channel_id, content)
    if ok:
        save_state(updated_state, STATE_PATH)
    return {
        "sent": ok,
        "skipped": False,
        "status_code": status_code,
        "body": body,
        "rain_mm": rain_mm,
        "wind_mps": wind_mps,
        "content": content,
        "logs": logs,
        "state": updated_state,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="状態遷移ベースの天気速報βを送信する。")
    parser.add_argument("--force", action="store_true", help="状態遷移がなくても手動テスト送信を許可する。")
    parser.add_argument("--dry-run", action="store_true", help="Discordへ送らず本文と判定だけ確認する。")
    args = parser.parse_args()

    result = run(force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("sent") or result.get("skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
