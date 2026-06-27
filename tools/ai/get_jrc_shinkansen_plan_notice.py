#!/usr/bin/env python3
"""Fetch and persist JR Central Shinkansen plan notices without notifying."""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from log_utils import log
except ModuleNotFoundError:
    from tools.ai.log_utils import log


ROOT = Path(__file__).resolve().parents[2]
SOURCE_URL = (
    "https://traininfo.jr-central.co.jp/shinkansen/"
    "var/maintenance_web/ti99_ja.json"
)
STATE_PATH = ROOT / "data" / "ai" / "shinkansen_plan_notice_state.json"
DEBUG_PATH = ROOT / "data" / "debug" / "railway" / "plan_notice_latest.json"
DEBUG_DIR = ROOT / "data" / "debug" / "railway" / "shinkansen_plan"
JST = ZoneInfo("Asia/Tokyo")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
NEXT_UPDATE_PATTERN = re.compile(
    r"(次回のお知らせは、.+?予定しています。)",
    re.DOTALL,
)


def _clean_message(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def parse_plan_notice_payload(payload: Any) -> dict[str, str]:
    screen = payload.get("screen") if isinstance(payload, dict) else None
    message_html = str(screen.get("message") or "") if isinstance(screen, dict) else ""
    if not message_html:
        message_html = _fallback_message_html(payload)
    message_text = _clean_message(message_html)
    match = NEXT_UPDATE_PATTERN.search(message_text)
    next_update_text = " ".join(match.group(1).split()) if match else ""
    content_hash = hashlib.sha256(message_text.encode("utf-8")).hexdigest()
    return {
        "message_html": message_html,
        "message_text": message_text,
        "next_update_text": next_update_text,
        "content_hash": content_hash,
    }


def _fallback_message_html(value: Any) -> str:
    candidates: list[str] = []

    def walk(node: Any, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                hint = str(key or "")
                if hint in {"message", "service-stop", "service_stop", "notice", "html", "text"}:
                    if isinstance(child, str):
                        candidates.append(child)
                walk(child, hint)
            return
        if isinstance(node, list):
            for child in node:
                walk(child, key_hint)
            return
        if isinstance(node, str) and key_hint in {"message", "service-stop", "service_stop", "notice", "html", "text"}:
            candidates.append(node)

    walk(value)
    scored = [
        text
        for text in candidates
        if any(
            keyword in _clean_message(text)
            for keyword in ("計画運休", "運転計画", "きっぷ", "次回のお知らせ", "運行情報")
        )
    ]
    if scored:
        return max(scored, key=lambda text: len(_clean_message(text)))
    return max(candidates, key=lambda text: len(_clean_message(text)), default="")


def _fetch_payload() -> tuple[dict[str, Any], str, int, str]:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ja,en-US;q=0.9",
            "Referer": "https://traininfo.jr-central.co.jp/shinkansen/pc/ja/ti99.html",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8-sig", errors="replace")
        final_url = response.geturl()
        status_code = response.status
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("plan notice response is not a JSON object")
    return payload, final_url, status_code, raw


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _history_debug_path(debug_dir: Path, now: datetime) -> Path:
    base = debug_dir / f"{now:%Y%m%d_%H%M%S}.json"
    if not base.exists():
        return base
    for index in range(1, 100):
        candidate = debug_dir / f"{now:%Y%m%d_%H%M%S}_{index}.json"
        if not candidate.exists():
            return candidate
    return debug_dir / f"{now:%Y%m%d_%H%M%S}_{now.microsecond}.json"


def save_plan_debug(debug_result: dict[str, Any], now: datetime) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    latest_path = DEBUG_DIR / "latest.json"
    history_path = _history_debug_path(DEBUG_DIR, now)
    _write_json(latest_path, debug_result)
    _write_json(history_path, debug_result)
    _write_json(DEBUG_PATH, debug_result)
    log(
        "shinkansen_plan_debug_saved: "
        f"latest={latest_path.relative_to(ROOT)} history={history_path.relative_to(ROOT)}"
    )


def get_jrc_shinkansen_plan_notice(
    *,
    now: datetime | None = None,
    state_path: Path = STATE_PATH,
    debug_path: Path = DEBUG_PATH,
) -> dict[str, Any]:
    payload, final_url, status_code, raw_response = _fetch_payload()
    parsed = parse_plan_notice_payload(payload)
    fetched_dt = (now or datetime.now(JST)).astimezone(JST)
    fetched_at = fetched_dt.isoformat(timespec="seconds")
    result: dict[str, Any] = {
        "source_url": SOURCE_URL,
        "final_url": final_url,
        "status_code": status_code,
        "available": bool(parsed["message_text"]) and parsed["content_hash"] != EMPTY_SHA256,
        "fetched_at": fetched_at,
        **parsed,
    }
    _write_json(state_path, result)
    debug_result: dict[str, Any] = {**result, "raw_payload": payload}
    if not payload:
        debug_result["response_preview"] = raw_response[:500]
    _write_json(debug_path, debug_result)
    save_plan_debug(debug_result, fetched_dt)
    log(
        "shinkansen_plan_notice_saved: "
        f"available={'yes' if result['available'] else 'no'} "
        f"next_update={'yes' if parsed['next_update_text'] else 'no'} "
        f"hash={parsed['content_hash'][:12]}"
    )
    return result


def main() -> int:
    result = get_jrc_shinkansen_plan_notice()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
