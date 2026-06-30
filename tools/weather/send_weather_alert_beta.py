#!/usr/bin/env python3
"""気象庁ベースの天気速報βをDiscordへ送信する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

try:
    from tools.ai.weather_severity import detect_weather_severity
    from tools.weather.weather_normalizer import get_all_weather_snapshot
except ModuleNotFoundError:
    from weather_severity import detect_weather_severity
    from weather_normalizer import get_all_weather_snapshot


STATE_PATH = ROOT / "data" / "weather_alert_beta_state.json"


def _setting(name: str) -> str:
    value = getattr(config, name, None)
    if value is None:
        return ""
    return str(value).strip()


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def build_weather_alert_message(alerts: list[str], *, force: bool = False) -> str:
    severity = detect_weather_severity(alerts)
    emoji = {
        "weather_critical": "🚨",
        "weather_alert": "⛈️",
        "weather_info": "☔",
        "weather_minor": "☔",
    }.get(severity, "☔")
    if not alerts and force:
        return "☔ 天気速報βテスト\n\n気象庁の名古屋向け警報・注意報に、現在送信対象はありません。"
    if not alerts:
        return ""
    uses_yahoo = any(("強雨注意" in alert or "大雨注意" in alert or "雷注意" in alert) for alert in alerts)
    lines = [f"{emoji} 天気速報β"]
    lines.extend(f"・{alert}" for alert in alerts[:5])
    lines.append("")
    lines.append("※ 気象庁・Yahoo天気データより" if uses_yahoo else "※ 気象庁データより")
    return "\n".join(lines)


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
    alerts = snapshot.get("normalized_alerts")
    if not isinstance(alerts, list):
        alerts = []
    alerts = [" ".join(str(alert or "").split()) for alert in alerts if str(alert or "").strip()]
    alert_hash = _json_hash({"alerts": alerts})
    state = _load_state()

    if not force and state.get("last_alert_hash") == alert_hash:
        return {
            "sent": False,
            "skipped": True,
            "reason": "duplicate",
            "alerts": alerts,
            "hash": alert_hash,
        }

    content = build_weather_alert_message(alerts, force=force)
    if not content:
        state.update(
            {
                "last_alert_hash": alert_hash,
                "last_checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "last_sent": False,
            }
        )
        _save_state(state)
        return {
            "sent": False,
            "skipped": True,
            "reason": "no_alerts",
            "alerts": alerts,
            "hash": alert_hash,
        }

    if dry_run:
        print(content)
        return {
            "sent": False,
            "skipped": True,
            "reason": "dry_run",
            "alerts": alerts,
            "hash": alert_hash,
        }

    token = _setting("DISCORD_BOT_TOKEN")
    channel_id = _setting("WEATHER_ALERT_CHANNEL_ID")
    if not token or not channel_id:
        return {
            "sent": False,
            "skipped": True,
            "reason": "missing_discord_config",
            "alerts": alerts,
            "hash": alert_hash,
            "channel_id_configured": bool(channel_id),
        }

    ok, status_code, body = post_discord(token, channel_id, content)
    if ok:
        state.update(
            {
                "last_alert_hash": alert_hash,
                "last_sent_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "last_sent": True,
            }
        )
        _save_state(state)
    return {
        "sent": ok,
        "skipped": False,
        "status_code": status_code,
        "body": body,
        "alerts": alerts,
        "hash": alert_hash,
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
