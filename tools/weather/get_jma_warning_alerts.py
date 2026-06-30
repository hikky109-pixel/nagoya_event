#!/usr/bin/env python3
"""気象庁の名古屋市向け警報・注意報だけを取得する。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

try:
    from get_jma_alerts import JMA_WARNING_URL, fetch_json, _nagoya_warning_alerts
except ModuleNotFoundError:
    from tools.weather.get_jma_alerts import JMA_WARNING_URL, fetch_json, _nagoya_warning_alerts


JST = ZoneInfo("Asia/Tokyo")


def _jst_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(JST)
    if now.tzinfo is None:
        return now.replace(tzinfo=JST)
    return now.astimezone(JST)


def get_jma_warning_alerts(now: datetime | None = None) -> list[str]:
    current = _jst_now(now)
    return _nagoya_warning_alerts(fetch_json(JMA_WARNING_URL), current)


def get_jma_warning_snapshot(now: datetime | None = None) -> dict[str, Any]:
    current = _jst_now(now)
    raw = fetch_json(JMA_WARNING_URL)
    return {
        "source": "JMA:warning",
        "raw": raw,
        "alerts": _nagoya_warning_alerts(raw, current),
    }


if __name__ == "__main__":
    print(get_jma_warning_alerts())
