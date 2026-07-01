#!/usr/bin/env python3
"""状態遷移ベースの天気速報βをDiscordへ送信する。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

try:
    from tools.weather.get_openmeteo_forecast import get_openmeteo_forecast
    from tools.weather.weather_normalizer import get_all_weather_snapshot
except ModuleNotFoundError:
    from get_openmeteo_forecast import get_openmeteo_forecast
    from weather_normalizer import get_all_weather_snapshot


STATE_PATH = ROOT / "data" / "weather" / "weather_alert_state.json"
COOLDOWN_MINUTES = 30
RECOVERY_MINUTES = 30
JST = timezone(timedelta(hours=9))

RAIN_STATES = ("NONE", "HEAVY", "VERY_HEAVY", "EXTREME")
WIND_STATES = ("NONE", "STRONG", "GALE", "STORM")

RAIN_THRESHOLDS = (
    (50.0, "EXTREME"),
    (20.0, "VERY_HEAVY"),
    (5.0, "HEAVY"),
)
WIND_THRESHOLDS = (
    (20.0, "STORM"),
    (15.0, "GALE"),
    (10.0, "STRONG"),
)

RAIN_MESSAGES = {
    "HEAVY": "🌧️ 強雨注意",
    "VERY_HEAVY": "⚠️ 大雨注意",
    "EXTREME": "🚨 豪雨警戒",
}
WIND_MESSAGES = {
    "STRONG": "🌪️ 強風注意",
    "GALE": "⚠️ 暴風注意",
    "STORM": "🚨 暴風警戒",
}


def _now() -> datetime:
    return datetime.now(JST)


def _setting(name: str) -> str:
    value = getattr(config, name, None)
    if value is None:
        return ""
    return str(value).strip()


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def _state_rank(kind: str, state: str) -> int:
    states = RAIN_STATES if kind == "rain" else WIND_STATES
    try:
        return states.index(state)
    except ValueError:
        return 0


def _empty_component() -> dict[str, Any]:
    return {
        "state": "NONE",
        "last_notified_state": "NONE",
        "below_threshold_since": None,
        "last_notified_at": "",
        "updated_at": "",
    }


def _normalize_component(raw: Any) -> dict[str, Any]:
    component = _empty_component()
    if isinstance(raw, dict):
        component.update(
            {
                "state": str(raw.get("state") or "NONE"),
                "last_notified_state": str(raw.get("last_notified_state") or raw.get("state") or "NONE"),
                "below_threshold_since": raw.get("below_threshold_since"),
                "last_notified_at": str(raw.get("last_notified_at") or ""),
                "updated_at": str(raw.get("updated_at") or ""),
            }
        )
    return component


def _load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"rain": _empty_component(), "wind": _empty_component()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    # Lv14.1 used {"level": N}; migrate it into rain state conservatively.
    if "rain" not in data and "level" in data:
        try:
            legacy_level = int(data.get("level") or 0)
        except (TypeError, ValueError):
            legacy_level = 0
        legacy_state = {0: "NONE", 1: "HEAVY", 2: "HEAVY", 3: "VERY_HEAVY", 4: "EXTREME"}.get(
            legacy_level,
            "NONE",
        )
        data["rain"] = {
            "state": legacy_state,
            "last_notified_state": legacy_state,
            "below_threshold_since": None,
            "last_notified_at": str(data.get("updated_at") or ""),
            "updated_at": str(data.get("updated_at") or ""),
        }

    return {
        "rain": _normalize_component(data.get("rain")),
        "wind": _normalize_component(data.get("wind")),
    }


def _save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def rain_state(value: float) -> str:
    for threshold, state in RAIN_THRESHOLDS:
        if value >= threshold:
            return state
    return "NONE"


def wind_state(value: float) -> str:
    for threshold, state in WIND_THRESHOLDS:
        if value >= threshold:
            return state
    return "NONE"


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


def max_wind_from_forecast(forecast: dict[str, Any]) -> float:
    rows = forecast.get("forecast")
    if not isinstance(rows, list):
        return 0.0
    return max(
        [_float_value(row.get("wind_speed_10m")) for row in rows if isinstance(row, dict)]
        or [0.0]
    )


def get_current_values() -> tuple[float, float]:
    snapshot = get_all_weather_snapshot()
    rain_mm = max_precipitation_from_snapshot(snapshot)
    try:
        wind_mps = max_wind_from_forecast(get_openmeteo_forecast(hours=24))
    except Exception as exc:
        print(f"weather_source_failed: source=Open-Meteo wind error={type(exc).__name__}", flush=True)
        wind_mps = 0.0
    return rain_mm, wind_mps


def build_transition_message(kind: str, state: str, value: float) -> str:
    if kind == "rain":
        if state == "NONE":
            return "☔ 雨のピークは過ぎました。"
        return f"{RAIN_MESSAGES[state]}: 名古屋中心部で1時間以内に{value:.1f}mm/h予測。"

    if state == "NONE":
        return "🍃 風は落ち着きました。"
    return f"{WIND_MESSAGES[state]}: 名古屋中心部で最大{value:.0f}m/s予測。"


def _cooldown_active(component: dict[str, Any], now: datetime) -> bool:
    last_notified_at = _parse_datetime(component.get("last_notified_at"))
    if last_notified_at is None:
        return False
    return now - last_notified_at < timedelta(minutes=COOLDOWN_MINUTES)


def evaluate_component(
    kind: str,
    component: dict[str, Any],
    current_state: str,
    value: float,
    now: datetime,
) -> tuple[dict[str, Any], str | None, list[str]]:
    previous_state = str(component.get("state") or "NONE")
    previous_notified = str(component.get("last_notified_state") or "NONE")
    previous_rank = _state_rank(kind, previous_state)
    notified_rank = _state_rank(kind, previous_notified)
    current_rank = _state_rank(kind, current_state)
    now_text = now.isoformat(timespec="seconds")
    updated = dict(component)
    logs: list[str] = []
    value_unit = "mm/h" if kind == "rain" else "m/s"

    updated["updated_at"] = now_text

    if current_state == "NONE":
        if previous_rank > 0:
            below_since = _parse_datetime(updated.get("below_threshold_since"))
            if below_since is None:
                below_since = now
                updated["below_threshold_since"] = below_since.isoformat(timespec="seconds")
            elapsed_minutes = int((now - below_since).total_seconds() // 60)
            if elapsed_minutes >= RECOVERY_MINUTES:
                updated.update(
                    {
                        "state": "NONE",
                        "last_notified_state": "NONE",
                        "below_threshold_since": None,
                        "last_notified_at": now_text,
                    }
                )
                logs.append(f"weather_recovered: {kind} {previous_state} -> NONE")
                return updated, build_transition_message(kind, "NONE", value), logs
            logs.append(
                f"weather_recovered_pending: {kind} below threshold "
                f"{elapsed_minutes}min/{RECOVERY_MINUTES}min"
            )
            return updated, None, logs

        updated.update({"state": "NONE", "below_threshold_since": None})
        logs.append(f"weather_notify_suppressed: same_state {kind}=NONE value={value:g}")
        return updated, None, logs

    updated["below_threshold_since"] = None
    if current_state != previous_state:
        logs.append(f"weather_state_changed: {kind} {previous_state} -> {current_state}")
    updated["state"] = current_state

    if current_rank > notified_rank:
        updated.update(
            {
                "last_notified_state": current_state,
                "last_notified_at": now_text,
            }
        )
        return updated, build_transition_message(kind, current_state, value), logs

    if current_state == previous_notified:
        logs.append(f"weather_notify_suppressed: same_state {kind}={current_state} value={value:g}")
        return updated, None, logs

    if current_rank < notified_rank:
        logs.append(
            f"weather_notify_suppressed: lower_state {kind}={current_state} "
            f"value={value:g}{value_unit} last_notified={previous_notified}"
        )
        return updated, None, logs

    if _cooldown_active(component, now):
        logs.append(f"weather_notify_suppressed: cooldown {kind}={current_state} value={value:g}")
        return updated, None, logs

    logs.append(f"weather_notify_suppressed: same_state {kind}={current_state} value={value:g}")
    return updated, None, logs


def evaluate_weather_state(
    state: dict[str, Any],
    *,
    rain_mm: float,
    wind_mps: float,
    now: datetime | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    current = now or _now()
    updated_rain, rain_message, rain_logs = evaluate_component(
        "rain",
        _normalize_component(state.get("rain")),
        rain_state(rain_mm),
        rain_mm,
        current,
    )
    updated_wind, wind_message, wind_logs = evaluate_component(
        "wind",
        _normalize_component(state.get("wind")),
        wind_state(wind_mps),
        wind_mps,
        current,
    )
    messages = [message for message in (rain_message, wind_message) if message]
    return {"rain": updated_rain, "wind": updated_wind}, messages, rain_logs + wind_logs


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
    state = _load_state()
    rain_mm, wind_mps = get_current_values()
    updated_state, messages, logs = evaluate_weather_state(
        state,
        rain_mm=rain_mm,
        wind_mps=wind_mps,
    )
    for message in logs:
        print(message, flush=True)

    if not messages and not force:
        _save_state(updated_state)
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
        _save_state(updated_state)
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
