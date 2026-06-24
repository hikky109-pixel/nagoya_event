from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag


URL = "https://top.meitetsu.co.jp/em/"
ABNORMAL_STATUS_MARKERS = (
    "運転見合せ",
    "運転見合わせ",
    "遅延",
    "一部運休",
    "運休",
    "振替輸送",
)
NORMAL_STATUS_MARKERS = (
    "平常運転",
    "平常通り",
    "通常運転",
    "運行に関する情報はありません",
)
DETAIL_LABELS = ("区間", "路線", "理由", "備考")


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cell_values(cell: Tag | None) -> list[str]:
    if cell is None:
        return []

    structured_items = [
        _clean_text(item.get_text(" ", strip=True))
        for item in cell.select("dt, dd, li")
    ]
    values = [item for item in structured_items if item]
    if values:
        return list(dict.fromkeys(values))

    text = _clean_text(cell.get_text(" ", strip=True))
    return [text] if text else []


def _detail_rows(block: Tag) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for row in block.select("tr"):
        header = row.find("th")
        cell = row.find("td")
        label = _clean_text(header.get_text(" ", strip=True) if header else "")
        if label not in DETAIL_LABELS:
            continue
        values = _cell_values(cell)
        if values:
            details[label] = values
    return details


def _alert_body(status: str, details: dict[str, list[str]]) -> str:
    parts = [status]
    for label in ("区間", "理由", "備考"):
        values = details.get(label, [])
        if values:
            parts.append(f"{label}: {' / '.join(values)}")
    return " / ".join(part for part in parts if part)


def _em_level(block: Tag) -> str:
    classes = block.get("class", [])
    if not isinstance(classes, list):
        return ""
    return next(
        (
            class_name
            for class_name in classes
            if isinstance(class_name, str) and class_name.startswith("emLv")
        ),
        "",
    )


def parse_meitetsu_status_snapshot(html: str) -> tuple[list[str], dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    alerts: list[str] = []
    level_by_alert: dict[str, str] = {}

    for block in soup.select("div.emInfo"):
        level = _em_level(block)
        heading = block.find("h2")
        status = _clean_text(heading.get_text(" ", strip=True) if heading else "")
        block_text = _clean_text(block.get_text(" ", strip=True))
        if not status or any(marker in status for marker in NORMAL_STATUS_MARKERS):
            continue
        if not any(marker in block_text for marker in ABNORMAL_STATUS_MARKERS):
            continue

        details = _detail_rows(block)
        lines = details.get("路線", [])
        if not lines:
            continue
        body = _alert_body(status, details)
        for line in lines:
            alert = f"名鉄 {line}: {body}"
            if alert not in alerts:
                alerts.append(alert)
            if level:
                level_by_alert[alert] = level

    return alerts, level_by_alert


def parse_meitetsu_status(html: str) -> list[str]:
    alerts, _level_by_alert = parse_meitetsu_status_snapshot(html)
    return alerts


def get_meitetsu_status_snapshot() -> tuple[list[str], str, datetime | None, dict[str, str]]:
    response = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
        allow_redirects=True,
    )
    response.raise_for_status()

    updated_at = None
    last_modified = response.headers.get("Last-Modified")
    if last_modified:
        try:
            updated_at = parsedate_to_datetime(last_modified)
        except (TypeError, ValueError):
            pass

    html = response.content.decode("utf-8", errors="replace")
    alerts, level_by_alert = parse_meitetsu_status_snapshot(html)
    return alerts, response.url, updated_at, level_by_alert


def get_meitetsu_status() -> list[str]:
    alerts, _source_url, _updated_at, _level_by_alert = get_meitetsu_status_snapshot()
    return alerts


if __name__ == "__main__":
    print(get_meitetsu_status_snapshot())
