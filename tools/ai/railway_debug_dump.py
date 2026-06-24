#!/usr/bin/env python3
"""Save railway parser failure artifacts for later investigation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from log_utils import log
except ModuleNotFoundError:
    from tools.ai.log_utils import log


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEBUG_DIR = ROOT / "data" / "debug" / "railway"
JST = ZoneInfo("Asia/Tokyo")
MAX_DEBUG_DUMPS = 100


def _next_dump_base(directory: Path, now: datetime) -> Path:
    stem = now.strftime("%Y%m%d_%H%M%S")
    candidate = directory / stem
    suffix = 1
    while candidate.with_suffix(".json").exists() or candidate.with_suffix(".html").exists():
        candidate = directory / f"{stem}_{suffix:02d}"
        suffix += 1
    return candidate


def prune_railway_debug_dumps(
    directory: Path = DEFAULT_DEBUG_DIR,
    keep: int = MAX_DEBUG_DUMPS,
) -> None:
    json_files = sorted(
        directory.glob("*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for json_path in json_files[max(keep, 0):]:
        html_path = json_path.with_suffix(".html")
        json_path.unlink(missing_ok=True)
        html_path.unlink(missing_ok=True)


def save_railway_debug_dump(
    *,
    source: str,
    request_url: str,
    final_url: str,
    status_code: int,
    reason: str,
    html: str,
    details: dict[str, Any] | None = None,
    directory: Path = DEFAULT_DEBUG_DIR,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    saved_at = now or datetime.now(JST)
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=JST)

    directory.mkdir(parents=True, exist_ok=True)
    base = _next_dump_base(directory, saved_at)
    html_path = base.with_suffix(".html")
    json_path = base.with_suffix(".json")

    metadata: dict[str, Any] = {
        "source": source,
        "url": request_url,
        "final_url": final_url,
        "status_code": status_code,
        "reason": reason,
        "saved_at": saved_at.astimezone(JST).isoformat(timespec="seconds"),
    }
    if details:
        metadata.update(details)

    html_path.write_text(html, encoding="utf-8")
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        f.write("\n")

    prune_railway_debug_dumps(directory)
    try:
        display_path = json_path.relative_to(ROOT)
    except ValueError:
        display_path = json_path
    log(f"railway_debug_dump_saved: {display_path}")
    return html_path, json_path
