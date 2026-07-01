#!/usr/bin/env python3
"""Weather alert state machine shared by beta sender and Gemma."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from tools.weather.get_openmeteo_forecast import get_openmeteo_forecast
    from tools.weather.weather_normalizer import get_all_weather_snapshot
except ModuleNotFoundError:
    from get_openmeteo_forecast import get_openmeteo_forecast
    from weather_normalizer import get_all_weather_snapshot


DEFAULT_STATE_PATH = ROOT / "data" / "ai" / "weather_state.json"
JMA_WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/warning/230000.json"
COOLDOWN_MINUTES = 30
RECOVERY_MINUTES = 30
JST = timezone(timedelta(hours=9))
NAGOYA_CITY_CODE = "2310000"
AICHI_OFFICE_CODE = "230000"
TOKAI_CENTER_CODE = "010400"

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
JMA_WARNING_NAMES = {
    "03": "大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "08": "高潮警報",
    "10": "大雨注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "18": "洪水注意報",
    "19": "高潮注意報",
}
JMA_INFORMATION_KEYWORDS = (
    "土砂災害注意情報",
    "土砂災害警戒情報",
    "氾濫注意情報",
)
JMA_RELEVANT_TEXT = (
    "愛知",
    "名古屋",
    "日光川",
    "庄内川",
    "矢田川",
    "天白川",
    "新川",
)


def now_jst() -> datetime:
    return datetime.now(JST)


def float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_datetime(value: Any) -> datetime | None:
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


def state_rank(kind: str, state: str) -> int:
    states = RAIN_STATES if kind == "rain" else WIND_STATES
    try:
        return states.index(state)
    except ValueError:
        return 0


def empty_component() -> dict[str, Any]:
    return {
        "state": "NONE",
        "last_notified_state": "NONE",
        "below_threshold_since": None,
        "last_notified_at": "",
        "updated_at": "",
    }


def empty_jma_component() -> dict[str, Any]:
    return {
        "active": {},
        "updated_at": "",
    }


def normalize_component(raw: Any) -> dict[str, Any]:
    component = empty_component()
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


def normalize_jma_component(raw: Any) -> dict[str, Any]:
    component = empty_jma_component()
    if not isinstance(raw, dict):
        return component
    active = raw.get("active")
    if not isinstance(active, dict):
        active = {}
    normalized_active: dict[str, dict[str, str]] = {}
    for key, value in active.items():
        if not isinstance(value, dict):
            continue
        normalized_active[str(key)] = {
            "label": str(value.get("label") or key),
            "message": str(value.get("message") or ""),
            "emoji": str(value.get("emoji") or "⚠️"),
            "code": str(value.get("code") or ""),
            "level": str(value.get("level") or ""),
            "level_code": str(value.get("level_code") or ""),
            "notify": bool(value.get("notify", True)),
        }
    component["active"] = normalized_active
    component["updated_at"] = str(raw.get("updated_at") or "")
    return component


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"rain": empty_component(), "wind": empty_component()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

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
        "rain": normalize_component(data.get("rain")),
        "wind": normalize_component(data.get("wind")),
        "jma": normalize_jma_component(data.get("jma")),
    }


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
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
        return float_value(raw_yahoo.get("max_precip_mm"))

    sources = snapshot.get("sources")
    if isinstance(sources, dict):
        yahoo = sources.get("YahooWeather")
        if isinstance(yahoo, dict):
            return float_value(yahoo.get("max_precip_mm"))
    return 0.0


def max_wind_from_forecast(forecast: dict[str, Any]) -> float:
    rows = forecast.get("forecast")
    if not isinstance(rows, list):
        return 0.0
    return max(
        [float_value(row.get("wind_speed_10m")) for row in rows if isinstance(row, dict)]
        or [0.0]
    )


def _jma_raw(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw_jma = snapshot.get("raw_jma")
    if isinstance(raw_jma, dict):
        return raw_jma
    sources = snapshot.get("sources")
    if isinstance(sources, dict):
        jma = sources.get("JMA")
        if isinstance(jma, dict):
            raw = jma.get("raw")
            if isinstance(raw, dict):
                return raw
    return {}


def _nagoya_warning_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    warning = raw.get("warning")
    if not isinstance(warning, dict):
        return []
    for area_type in warning.get("areaTypes", []):
        if not isinstance(area_type, dict):
            continue
        for area in area_type.get("areas", []):
            if not isinstance(area, dict) or str(area.get("code")) != NAGOYA_CITY_CODE:
                continue
            warnings = area.get("warnings")
            if isinstance(warnings, list):
                return [item for item in warnings if isinstance(item, dict)]
            return []
    return []


def _warning_name(warning: dict[str, Any]) -> str:
    name = str(warning.get("name") or "").strip()
    if name:
        return name
    code = str(warning.get("code") or "").zfill(2)
    return JMA_WARNING_NAMES.get(code, "")


def _jma_emoji(label: str) -> str:
    if "雷" in label:
        return "⚡"
    if "洪水" in label or "高潮" in label or "氾濫" in label:
        return "🌊"
    if "解除" in label:
        return "✅"
    return "⚠️"


def _parse_jma_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def _information_active(item: dict[str, Any], now: datetime) -> bool:
    valid = _parse_jma_datetime(item.get("valid") or item.get("validDatetime") or item.get("validMap"))
    if valid is not None:
        return valid >= now
    reported = _parse_jma_datetime(item.get("reportDatetime") or item.get("datetime"))
    if reported is None:
        return False
    return now - timedelta(hours=12) <= reported <= now + timedelta(minutes=10)


def _information_relevant(item: dict[str, Any]) -> bool:
    area_codes = item.get("areaCodes")
    if not isinstance(area_codes, list):
        area_codes = [item.get("areaCode")]
    codes = {str(code) for code in area_codes if code is not None}
    if codes & {NAGOYA_CITY_CODE, AICHI_OFFICE_CODE, TOKAI_CENTER_CODE}:
        return True
    text = " ".join(
        str(item.get(key) or "")
        for key in ("headTitle", "controlTitle", "title", "subtitle")
    )
    return any(marker in text for marker in JMA_RELEVANT_TEXT)


def _flood_target(title: str) -> str:
    target = title.replace("氾濫注意情報", "").strip()
    if "水系" in target and "水系 " not in target:
        target = target.replace("水系", "水系 ", 1)
    return target or title


def jma_active_advisories_from_snapshot(
    snapshot: dict[str, Any],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = now or now_jst()
    raw = _jma_raw(snapshot)
    advisories: list[dict[str, Any]] = []

    warning = raw.get("warning")
    if isinstance(warning, dict):
        for area_type in warning.get("areaTypes", []):
            if not isinstance(area_type, dict):
                continue
            for area in area_type.get("areas", []):
                if not isinstance(area, dict) or str(area.get("code")) != NAGOYA_CITY_CODE:
                    continue
                for warning_item in area.get("warnings", []):
                    if not isinstance(warning_item, dict) or warning_item.get("status") != "発表":
                        continue
                    label = _warning_name(warning_item)
                    if label not in set(JMA_WARNING_NAMES.values()):
                        continue
                    emoji = _jma_emoji(label)
                    advisories.append(
                        {
                            "key": f"warning:nagoya:{label}",
                            "label": label,
                            "emoji": emoji,
                            "message": f"{emoji} 気象庁発表: 名古屋市に{label}が発表中です。",
                        }
                    )
                break

    information = raw.get("information")
    if isinstance(information, list):
        for item in information:
            if not isinstance(item, dict) or not _information_active(item, current):
                continue
            if not _information_relevant(item):
                continue
            title = str(item.get("headTitle") or item.get("controlTitle") or "").strip()
            if not title:
                continue
            if "氾濫注意情報" in title:
                label = title
                target = _flood_target(title)
                advisories.append(
                    {
                        "key": f"information:{label}",
                        "label": label,
                        "emoji": "🌊",
                        "message": f"🌊 気象庁発表: {target}に氾濫注意情報が発表中です。",
                    }
                )
                continue
            if any(keyword in title for keyword in JMA_INFORMATION_KEYWORDS):
                label = "土砂災害注意情報" if "土砂災害" in title else title
                advisories.append(
                    {
                        "key": f"information:{title}",
                        "label": label,
                        "emoji": "⚠️",
                        "message": f"⚠️ 気象庁発表: 名古屋市周辺に{label}が発表中です。",
                    }
                )

    unique: dict[str, dict[str, str]] = {}
    for advisory in advisories:
        key = advisory.get("key", "")
        if key:
            unique[key] = advisory
    return list(unique.values())


def jma_debug_logs_from_snapshot(
    snapshot: dict[str, Any],
    advisories: list[dict[str, Any]],
) -> list[str]:
    raw = _jma_raw(snapshot)
    warning_items = _nagoya_warning_items(raw)
    parsed = [str(advisory.get("label") or "") for advisory in advisories if advisory.get("label")]
    logs = [
        f"jma_fetch_url: {JMA_WARNING_URL}",
        f"jma_area_code: {NAGOYA_CITY_CODE}",
        f"jma_raw_count: {len(warning_items)}",
        "jma_raw_head20: "
        + json.dumps(warning_items[:20], ensure_ascii=False, separators=(",", ":")),
        "jma_parsed: "
        + json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
    ]
    if not advisories:
        logs.append("jma_warning: no active advisories parsed")
    return logs


def _advisory_level(advisory: dict[str, Any]) -> str:
    level = str(advisory.get("level") or "").strip()
    if level:
        return level
    level_code = str(advisory.get("level_code") or "").strip()
    if level_code.startswith("2"):
        return "2"
    if level_code.startswith("3"):
        return "3"
    if level_code.startswith("4"):
        return "4"
    if level_code.startswith("5"):
        return "5"
    return ""


def _is_landslide_level2(advisory: dict[str, Any]) -> bool:
    code = str(advisory.get("code") or "").strip()
    label = str(advisory.get("label") or "")
    message = str(advisory.get("message") or "")
    text = label + " " + message
    level = _advisory_level(advisory)
    if code == "29" and level == "2":
        return True
    if "土砂" in text and ("レベル2" in text or "レベル２" in text):
        return True
    return False


def jma_advisory_notify_enabled(advisory: dict[str, Any]) -> bool:
    if advisory.get("notify") is False:
        return False
    if _is_landslide_level2(advisory):
        return False
    return True


def get_current_values() -> tuple[float, float, dict[str, Any], list[str]]:
    logs: list[str] = []
    snapshot = get_all_weather_snapshot()
    rain_mm = max_precipitation_from_snapshot(snapshot)
    try:
        wind_mps = max_wind_from_forecast(get_openmeteo_forecast(hours=24))
    except Exception as exc:
        logs.append(f"weather_source_failed: source=Open-Meteo wind error={type(exc).__name__}")
        wind_mps = 0.0
    return rain_mm, wind_mps, snapshot, logs


def build_transition_message(kind: str, state: str, value: float) -> str:
    if kind == "rain":
        if state == "NONE":
            return "☔ 雨のピークは過ぎました。"
        return f"{RAIN_MESSAGES[state]}: 名古屋中心部で1時間以内に{value:.1f}mm/h予測。"

    if state == "NONE":
        return "🍃 風は落ち着きました。"
    return f"{WIND_MESSAGES[state]}: 名古屋中心部で最大{value:.0f}m/s予測。"


def cooldown_active(component: dict[str, Any], now: datetime) -> bool:
    last_notified_at = parse_datetime(component.get("last_notified_at"))
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
    previous_rank = state_rank(kind, previous_state)
    notified_rank = state_rank(kind, previous_notified)
    current_rank = state_rank(kind, current_state)
    now_text = now.isoformat(timespec="seconds")
    updated = dict(component)
    logs: list[str] = []
    value_unit = "mm/h" if kind == "rain" else "m/s"

    updated["updated_at"] = now_text

    if current_state == "NONE":
        if previous_rank > 0:
            below_since = parse_datetime(updated.get("below_threshold_since"))
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
            f"weather_notify_suppressed: downgrade {kind}={current_state} "
            f"value={value:g}{value_unit} last_notified={previous_notified}"
        )
        return updated, None, logs

    if cooldown_active(component, now):
        logs.append(f"weather_notify_suppressed: cooldown {kind}={current_state} value={value:g}")
        return updated, None, logs

    logs.append(f"weather_notify_suppressed: same_state {kind}={current_state} value={value:g}")
    return updated, None, logs


def evaluate_weather_state(
    state: dict[str, Any],
    *,
    rain_mm: float,
    wind_mps: float,
    jma_advisories: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    current = now or now_jst()
    updated_rain, rain_message, rain_logs = evaluate_component(
        "rain",
        normalize_component(state.get("rain")),
        rain_state(rain_mm),
        rain_mm,
        current,
    )
    updated_wind, wind_message, wind_logs = evaluate_component(
        "wind",
        normalize_component(state.get("wind")),
        wind_state(wind_mps),
        wind_mps,
        current,
    )
    messages = [message for message in (rain_message, wind_message) if message]
    updated_jma, jma_messages, jma_logs = evaluate_jma_state(
        normalize_jma_component(state.get("jma")),
        jma_advisories or [],
        current,
    )
    messages.extend(jma_messages)
    return {"rain": updated_rain, "wind": updated_wind, "jma": updated_jma}, messages, rain_logs + wind_logs + jma_logs


def evaluate_jma_state(
    component: dict[str, Any],
    advisories: list[dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any], list[str], list[str]]:
    now_text = now.isoformat(timespec="seconds")
    previous_active = component.get("active")
    if not isinstance(previous_active, dict):
        previous_active = {}
    current_active: dict[str, dict[str, str]] = {}
    for advisory in advisories:
        key = str(advisory.get("key") or "").strip()
        if not key:
            continue
        current_active[key] = {
            "label": str(advisory.get("label") or key),
            "message": str(advisory.get("message") or ""),
            "emoji": str(advisory.get("emoji") or "⚠️"),
            "code": str(advisory.get("code") or ""),
            "level": _advisory_level(advisory),
            "level_code": str(advisory.get("level_code") or ""),
            "notify": jma_advisory_notify_enabled(advisory),
        }

    messages: list[str] = []
    logs: list[str] = []
    previous_keys = set(previous_active)
    current_keys = set(current_active)

    for key in sorted(current_keys - previous_keys):
        advisory = current_active[key]
        if not advisory.get("notify", True):
            if advisory.get("code") == "29" or "土砂" in str(advisory.get("label") or ""):
                logs.append("landslide_suppressed: level=2 code=29 reason=policy")
            else:
                logs.append(f"weather_notify_suppressed: jma_policy {advisory.get('label', key)}")
            continue
        message = advisory.get("message") or f"{advisory.get('emoji', '⚠️')} 気象庁発表: {advisory.get('label', key)}が発表中です。"
        messages.append(message)
        logs.append(f"weather_state_changed: jma issued {advisory.get('label', key)}")

    for key in sorted(previous_keys & current_keys):
        label = current_active[key].get("label") or key
        logs.append(f"weather_notify_suppressed: same_state jma={label}")

    for key in sorted(previous_keys - current_keys):
        previous = previous_active.get(key)
        if not isinstance(previous, dict):
            previous = {"label": key}
        if not previous.get("notify", True):
            if previous.get("code") == "29" or "土砂" in str(previous.get("label") or ""):
                logs.append("landslide_suppressed: level=2 code=29 reason=policy")
            else:
                logs.append(f"weather_recovered: jma {previous.get('label', key)} released_without_notification")
            continue
        label = str(previous.get("label") or key)
        messages.append(f"✅ 気象庁発表: {label}は解除されました。")
        logs.append(f"weather_recovered: jma {label} released")

    return {"active": current_active, "updated_at": now_text}, messages, logs
