#!/usr/bin/env python3
"""鉄道運行情報取得スクリプトの戻り値を list[str] にそろえる。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from get_aonami_status import get_aonami_status  # noqa: E402
from get_johoku_status import get_johoku_status  # noqa: E402
from get_jrc_zairai_status import get_jrc_zairai_status  # noqa: E402
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


def normalize_jrc_zairai_status() -> list[str]:
    result = get_jrc_zairai_status()
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


def normalize_jrc_shinkansen_status() -> list[str]:
    result = get_jrc_shinkansen_status()
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


def get_all_railway_alerts() -> list[str]:
    alerts: list[str] = []
    checks: list[tuple[str, Callable[[], list[str]]]] = [
        ("あおなみ線", normalize_aonami_status),
        ("城北線", normalize_johoku_status),
        ("JR東海在来線", normalize_jrc_zairai_status),
        ("近鉄", normalize_kintetsu_status),
        ("リニモ", normalize_linimo_status),
        ("名鉄", normalize_meitetsu_status),
        ("名古屋市営地下鉄", normalize_nagoya_subway_status),
        ("ゆとりーとライン", normalize_yutorito_status),
        ("東海道新幹線", normalize_jrc_shinkansen_status),
    ]
    for label, getter in checks:
        alerts.extend(_safe(label, getter))
    return alerts


if __name__ == "__main__":
    print(get_all_railway_alerts())
