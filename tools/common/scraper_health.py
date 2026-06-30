#!/usr/bin/env python3
"""スクレイパーのHTML構造変化を軽量に監視する。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HEALTH_DIR = ROOT / "data" / "health" / "scrapers"


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_scraper_name(scraper: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(scraper or "")).strip("._") or "unknown"


def _health_path(scraper: str) -> Path:
    return HEALTH_DIR / f"{_safe_scraper_name(scraper)}.json"


def load_health_state(scraper: str) -> dict[str, Any]:
    path = _health_path(scraper)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_health_state(scraper: str, state: dict[str, Any]) -> None:
    path = _health_path(scraper)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["scraper"] = _safe_scraper_name(scraper)
    payload["updated_at"] = _now_text()
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _state_section(state: dict[str, Any], key: str) -> dict[str, Any]:
    section = state.get(key)
    if not isinstance(section, dict):
        section = {}
        state[key] = section
    return section


def check_selector_count(
    scraper: str,
    soup: Any,
    selector: str,
    label: str,
    min_count: int = 1,
    drop_ratio: float | None = None,
) -> list[str]:
    state = load_health_state(scraper)
    selector_state = _state_section(state, "selectors")
    previous = selector_state.get(selector)
    previous_count = int(previous.get("count", 0)) if isinstance(previous, dict) else 0
    count = len(soup.select(selector)) if soup is not None else 0

    selector_state[selector] = {
        "label": label,
        "count": count,
        "checked_at": _now_text(),
    }
    save_health_state(scraper, state)

    messages = [f"scraper_health: {scraper} {label} count={count}"]
    if count < min_count:
        messages.append(
            f"scraper_health_warning: {scraper} {label} {count}件 "
            "HTML構造変更または取得失敗の可能性"
        )
    if previous_count > 0 and count == 0:
        messages.append(
            f"scraper_health_warning: {scraper} {label} 件数が0に急減 "
            f"previous={previous_count} current=0"
        )
    elif (
        drop_ratio is not None
        and previous_count > 0
        and count <= previous_count * (1 - drop_ratio)
    ):
        messages.append(
            f"scraper_health_warning: {scraper} {label} count dropped "
            f"previous={previous_count} current={count}"
        )
    return messages


def check_sequence(
    scraper: str,
    key: str,
    label: str,
    values: list[str],
    *,
    min_count: int = 1,
) -> list[str]:
    state = load_health_state(scraper)
    sequences_state = _state_section(state, "sequences")
    previous_values = sequences_state.get(key)
    if not isinstance(previous_values, list):
        previous_values = []

    current_values = [str(value) for value in values if str(value)]
    sequences_state[key] = current_values
    save_health_state(scraper, state)

    current_text = ",".join(current_values)
    messages = [f"scraper_health: {scraper} {label}={current_text}"]
    if len(current_values) < min_count:
        messages.append(
            f"scraper_health_warning: {scraper} {label} 0件 "
            "HTML構造変更または取得失敗の可能性"
        )
    if previous_values and previous_values != current_values:
        messages.append(
            f"scraper_health_info: {scraper} {label} sequence changed "
            f"previous={','.join(previous_values)} current={current_text}"
        )
    return messages


def _year_from_tab(node: Any) -> str:
    text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
    href = str(node.get("href", "")) if hasattr(node, "get") else ""
    for value in (text, href):
        match = re.search(r"(20\d{2})", value)
        if match:
            return match.group(1)
    return text or href


def check_year_tabs(scraper: str, soup: Any, selector: str) -> list[str]:
    state = load_health_state(scraper)
    tabs_state = _state_section(state, "year_tabs")
    previous_years = tabs_state.get(selector)
    if not isinstance(previous_years, list):
        previous_years = []

    years: list[str] = []
    for node in soup.select(selector) if soup is not None else []:
        year = _year_from_tab(node)
        if year and year not in years:
            years.append(year)

    tabs_state[selector] = years
    save_health_state(scraper, state)

    current_text = ",".join(years)
    messages = [f"scraper_health: {scraper} tabs years={current_text}"]
    if not years:
        messages.append(
            f"scraper_health_warning: {scraper} 年タブ 0件 "
            "HTML構造変更または取得失敗の可能性"
        )
    if previous_years and previous_years != years:
        messages.append(
            "scraper_health_info: "
            f"{scraper} 年タブ変更 previous={','.join(previous_years)} "
            f"current={current_text}"
        )
    return messages


def check_structure_hash(scraper: str, html_fragment: str, key: str) -> list[str]:
    state = load_health_state(scraper)
    hashes_state = _state_section(state, "structure_hashes")
    previous = hashes_state.get(key)
    previous_hash = str(previous.get("hash", "")) if isinstance(previous, dict) else ""
    digest = hashlib.sha256(str(html_fragment or "").encode("utf-8")).hexdigest()

    hashes_state[key] = {
        "hash": digest,
        "checked_at": _now_text(),
    }
    save_health_state(scraper, state)

    if previous_hash and previous_hash != digest:
        return [
            "scraper_health_info: "
            f"{scraper} structure hash changed key={key} "
            f"previous={previous_hash[:12]} current={digest[:12]}"
        ]
    return [f"scraper_health: {scraper} structure hash key={key} hash={digest[:12]}"]
