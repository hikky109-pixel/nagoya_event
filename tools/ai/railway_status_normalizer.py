#!/usr/bin/env python3
"""鉄道運行情報取得スクリプトの戻り値を list[str] にそろえる。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from get_aonami_status import get_aonami_status  # noqa: E402
from get_johoku_status import get_johoku_status  # noqa: E402
from get_jrc_zairai_status import get_jrc_zairai_status, get_jrc_zairai_status_snapshot  # noqa: E402
from get_kintetsu_status import get_kintetsu_status  # noqa: E402
from get_linimo_status import get_linimo_status  # noqa: E402
from get_meitetsu_status import get_meitetsu_status  # noqa: E402
from get_nagoya_subway_status import get_nagoya_subway_status  # noqa: E402
from get_yutorito_status import get_yutorito_status  # noqa: E402
from jrc_shinkansen_status import get_jrc_shinkansen_status  # noqa: E402


NORMAL_HINTS = (
    "平常",
    "通常",
    "遅れはございません",
    "運行に関する情報はありません",
    "支障はありません",
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _prefixed(prefix: str, messages: list[Any]) -> list[str]:
    alerts: list[str] = []
    for message in messages:
        text = _clean_text(message)
        if text:
            alerts.append(f"{prefix}: {text}")
    return alerts


def _safe(label: str, getter: Callable[[], list[str]]) -> list[str]:
    try:
        return getter()
    except Exception as exc:
        return [f"{label}: 取得失敗: {exc}"]


def normalize_aonami_status() -> list[str]:
    return _prefixed("あおなみ線", get_aonami_status(abnormal_only=True))


def normalize_johoku_status() -> list[str]:
    return _prefixed("城北線", get_johoku_status())


def _normalize_jrc_zairai_result(result: Any) -> list[str]:
    if result is None:
        return []
    if isinstance(result, str):
        text = _clean_text(result)
        return [f"JR東海在来線: {text}"] if text else []
    if not isinstance(result, dict):
        return []

    alerts: list[str] = []
    for line_name, messages in result.items():
        if isinstance(messages, list):
            for message in messages:
                text = _clean_text(message)
                if text:
                    alerts.append(f"JR東海在来線 {line_name}: {text}")
            continue

        text = _clean_text(messages)
        if text:
            alerts.append(f"JR東海在来線 {line_name}: {text}")
    return alerts


def normalize_jrc_zairai_status() -> list[str]:
    return _normalize_jrc_zairai_result(get_jrc_zairai_status())


def normalize_jrc_zairai_status_snapshot() -> tuple[list[str], dict[str, datetime]]:
    result, updated_at = get_jrc_zairai_status_snapshot()
    alerts = _normalize_jrc_zairai_result(result)
    if updated_at is None:
        return alerts, {}
    return alerts, {alert: updated_at for alert in alerts}


def normalize_kintetsu_status() -> list[str]:
    return _prefixed("近鉄", get_kintetsu_status(abnormal_only=True))


def normalize_linimo_status() -> list[str]:
    return _prefixed("リニモ", get_linimo_status())


def normalize_meitetsu_status() -> list[str]:
    text = _clean_text(get_meitetsu_status())
    if not text:
        return []
    if any(hint in text for hint in NORMAL_HINTS):
        return []
    return [f"名鉄: {text}"]


def normalize_nagoya_subway_status() -> list[str]:
    result = get_nagoya_subway_status(abnormal_only=True)
    if not isinstance(result, dict):
        return []

    alerts: list[str] = []
    for line_name, info in result.items():
        if not isinstance(info, dict):
            continue
        status = _clean_text(info.get("status"))
        section = _clean_text(info.get("section"))
        cause = _clean_text(info.get("cause"))
        message = _clean_text(info.get("message"))
        parts = [part for part in (status, section, cause, message) if part]
        if parts:
            alerts.append(f"名古屋市営地下鉄 {line_name}: {' / '.join(parts)}")
    return alerts


def normalize_yutorito_status() -> list[str]:
    return _prefixed("ゆとりーとライン", get_yutorito_status())


def _normalize_jrc_shinkansen_result(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []
    if result.get("status") == "normal":
        return []
    if result.get("status") == "service_stop":
        return ["東海道新幹線: 運行情報提供停止"]

    message = _clean_text(result.get("message")) or "異常情報あり"
    details = result.get("details")
    if details:
        detail_text = _clean_text(json.dumps(details, ensure_ascii=False))
        if detail_text:
            message = f"{message} / {detail_text}"
    return [f"東海道新幹線: {message}"]


def normalize_jrc_shinkansen_status() -> list[str]:
    return _normalize_jrc_shinkansen_result(get_jrc_shinkansen_status())


def normalize_jrc_shinkansen_status_snapshot() -> tuple[list[str], dict[str, datetime]]:
    result = get_jrc_shinkansen_status()
    alerts = _normalize_jrc_shinkansen_result(result)
    if not alerts or not isinstance(result, dict):
        return alerts, {}

    raw_updated_at = result.get("updated_at")
    updated_at = None
    if isinstance(raw_updated_at, (int, float)):
        updated_at = datetime.fromtimestamp(raw_updated_at, timezone.utc)
    elif isinstance(raw_updated_at, str):
        try:
            updated_at = datetime.fromisoformat(raw_updated_at)
        except ValueError:
            pass
    if updated_at is None:
        return alerts, {}
    return alerts, {alert: updated_at for alert in alerts}


def get_all_railway_alerts() -> list[str]:
    alerts, _updated_at_by_alert = get_all_railway_alerts_snapshot()
    return alerts


def get_all_railway_alerts_snapshot() -> tuple[list[str], dict[str, datetime]]:
    alerts: list[str] = []
    updated_at_by_alert: dict[str, datetime] = {}
    checks_before_jrc: list[tuple[str, Callable[[], list[str]]]] = [
        ("あおなみ線", normalize_aonami_status),
        ("城北線", normalize_johoku_status),
    ]
    checks_after_jrc: list[tuple[str, Callable[[], list[str]]]] = [
        ("近鉄", normalize_kintetsu_status),
        ("リニモ", normalize_linimo_status),
        ("名鉄", normalize_meitetsu_status),
        ("名古屋市営地下鉄", normalize_nagoya_subway_status),
        ("ゆとりーとライン", normalize_yutorito_status),
    ]

    for label, getter in checks_before_jrc:
        alerts.extend(_safe(label, getter))

    try:
        jrc_alerts, jrc_updated_at = normalize_jrc_zairai_status_snapshot()
    except Exception as exc:
        jrc_alerts = [f"JR東海在来線: 取得失敗: {exc}"]
        jrc_updated_at = {}
    alerts.extend(jrc_alerts)
    updated_at_by_alert.update(jrc_updated_at)

    for label, getter in checks_after_jrc:
        alerts.extend(_safe(label, getter))

    try:
        shinkansen_alerts, shinkansen_updated_at = normalize_jrc_shinkansen_status_snapshot()
    except Exception as exc:
        shinkansen_alerts = [f"東海道新幹線: 取得失敗: {exc}"]
        shinkansen_updated_at = {}
    alerts.extend(shinkansen_alerts)
    updated_at_by_alert.update(shinkansen_updated_at)
    return alerts, updated_at_by_alert


if __name__ == "__main__":
    print(get_all_railway_alerts())
