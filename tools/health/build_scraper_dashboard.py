#!/usr/bin/env python3
"""Build a management dashboard from scraper health state files."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HEALTH_DIR = ROOT / "data" / "health" / "scrapers"
DASHBOARD_STATE_PATH = ROOT / "data" / "health" / "scraper_dashboard_state.json"
DASHBOARD_JSON_PATH = ROOT / "data" / "health" / "scraper_dashboard.json"
DASHBOARD_TEXT_PATH = ROOT / "data" / "health" / "scraper_dashboard.txt"
JST = timezone(timedelta(hours=9), "JST")


def _now() -> datetime:
    return datetime.now(JST)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def _count_entries(state: dict[str, Any]) -> dict[str, int]:
    entries: dict[str, int] = {}
    for section_name in ("counts", "selectors"):
        section = state.get(section_name)
        if not isinstance(section, dict):
            continue
        for key, record in section.items():
            if not isinstance(record, dict):
                continue
            label = str(record.get("label") or key)
            try:
                count = int(record.get("count", 0))
            except (TypeError, ValueError):
                count = 0
            entries[label] = count
    return entries


def _hash_entries(state: dict[str, Any]) -> dict[str, str]:
    hashes = state.get("structure_hashes")
    if not isinstance(hashes, dict):
        return {}
    result: dict[str, str] = {}
    for key, record in hashes.items():
        if isinstance(record, dict) and record.get("hash"):
            result[str(key)] = str(record["hash"])
    return result


def _sequence_entries(state: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for section_name in ("sequences", "year_tabs"):
        section = state.get(section_name)
        if not isinstance(section, dict):
            continue
        for key, values in section.items():
            if isinstance(values, list):
                result[str(key)] = [str(value) for value in values]
    return result


def _scraper_snapshot(path: Path) -> dict[str, Any]:
    state = _read_json(path)
    scraper = str(state.get("scraper") or path.stem)
    return {
        "scraper": scraper,
        "updated_at": str(state.get("updated_at") or ""),
        "counts": _count_entries(state),
        "hashes": _hash_entries(state),
        "sequences": _sequence_entries(state),
    }


def load_scraper_snapshots(health_dir: Path = HEALTH_DIR) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    if not health_dir.exists():
        return snapshots
    for path in sorted(health_dir.glob("*.json")):
        snapshot = _scraper_snapshot(path)
        snapshots[snapshot["scraper"]] = snapshot
    return snapshots


def _hash_since(
    *,
    scraper: str,
    key: str,
    current_hash: str,
    previous_dashboard: dict[str, Any],
    now: datetime,
) -> str:
    previous_scrapers = previous_dashboard.get("scrapers")
    if not isinstance(previous_scrapers, dict):
        return now.isoformat(timespec="seconds")
    previous = previous_scrapers.get(scraper)
    if not isinstance(previous, dict):
        return now.isoformat(timespec="seconds")
    previous_hashes = previous.get("hashes")
    if not isinstance(previous_hashes, dict):
        return now.isoformat(timespec="seconds")
    previous_record = previous_hashes.get(key)
    if not isinstance(previous_record, dict):
        return now.isoformat(timespec="seconds")
    if str(previous_record.get("hash") or "") != current_hash:
        return now.isoformat(timespec="seconds")
    return str(previous_record.get("same_since") or now.isoformat(timespec="seconds"))


def evaluate_dashboard(
    snapshots: dict[str, dict[str, Any]],
    previous_dashboard: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    previous_scrapers = previous_dashboard.get("scrapers")
    if not isinstance(previous_scrapers, dict):
        previous_scrapers = {}

    warnings: list[str] = []
    infos: list[str] = []
    scraper_records: dict[str, Any] = {}

    for scraper, snapshot in sorted(snapshots.items()):
        previous = previous_scrapers.get(scraper)
        if not isinstance(previous, dict):
            previous = {}
        previous_counts = previous.get("counts")
        if not isinstance(previous_counts, dict):
            previous_counts = {}
        previous_hashes = previous.get("hashes")
        if not isinstance(previous_hashes, dict):
            previous_hashes = {}

        count_records: dict[str, Any] = {}
        for label, count in snapshot["counts"].items():
            previous_record = previous_counts.get(label)
            previous_count = (
                int(previous_record.get("count", 0))
                if isinstance(previous_record, dict)
                else 0
            )
            count_records[label] = {
                "count": count,
                "previous_count": previous_count,
            }
            if count == 0:
                warnings.append(f"{scraper}: {label} 0件")
            elif previous_count > 0 and count <= previous_count * 0.5:
                warnings.append(
                    f"{scraper}: {label} 前回比50%以上減少 previous={previous_count} current={count}"
                )

        hash_records: dict[str, Any] = {}
        for key, digest in snapshot["hashes"].items():
            previous_record = previous_hashes.get(key)
            previous_hash = (
                str(previous_record.get("hash", ""))
                if isinstance(previous_record, dict)
                else ""
            )
            same_since = _hash_since(
                scraper=scraper,
                key=key,
                current_hash=digest,
                previous_dashboard=previous_dashboard,
                now=now,
            )
            hash_records[key] = {
                "hash": digest,
                "previous_hash": previous_hash,
                "same_since": same_since,
            }
            if previous_hash and previous_hash != digest:
                warnings.append(
                    f"{scraper}: structure hash changed key={key} "
                    f"previous={previous_hash[:12]} current={digest[:12]}"
                )
            since_dt = _parse_dt(same_since)
            if since_dt is not None and now - since_dt >= timedelta(days=7):
                infos.append(f"{scraper}: structure hash stable >=7d key={key}")

        scraper_records[scraper] = {
            "updated_at": snapshot["updated_at"],
            "counts": count_records,
            "hashes": hash_records,
            "sequences": snapshot["sequences"],
        }

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "scrapers": scraper_records,
        "warnings": warnings,
        "infos": infos,
        "status": "warning" if warnings else "ok",
    }


def render_report(dashboard: dict[str, Any]) -> str:
    warnings = dashboard.get("warnings") if isinstance(dashboard.get("warnings"), list) else []
    infos = dashboard.get("infos") if isinstance(dashboard.get("infos"), list) else []
    scrapers = dashboard.get("scrapers") if isinstance(dashboard.get("scrapers"), dict) else {}

    lines = [
        "Scraper Health Dashboard",
        f"generated_at: {dashboard.get('generated_at', '')}",
        f"status: {dashboard.get('status', 'unknown')}",
        "",
        f"warnings: {len(warnings)}",
    ]
    lines.extend(f"- WARNING {warning}" for warning in warnings)
    lines.extend(["", f"infos: {len(infos)}"])
    lines.extend(f"- INFO {info}" for info in infos)
    lines.extend(["", "scrapers:"])

    for scraper, record in sorted(scrapers.items()):
        counts = record.get("counts") if isinstance(record, dict) else {}
        hashes = record.get("hashes") if isinstance(record, dict) else {}
        count_text = ", ".join(
            f"{label}={value.get('count', 0)}"
            for label, value in sorted(counts.items())
            if isinstance(value, dict)
        )
        hash_text = ", ".join(
            f"{key}={value.get('hash', '')[:12]}"
            for key, value in sorted(hashes.items())
            if isinstance(value, dict)
        )
        lines.append(f"- {scraper}: counts[{count_text}] hashes[{hash_text}]")

    return "\n".join(lines).rstrip() + "\n"


def already_ran_today(state: dict[str, Any], now: datetime) -> bool:
    last_run = _parse_dt(str(state.get("last_run_at") or ""))
    return bool(last_run and last_run.date() == now.date())


def build_dashboard(*, force: bool = False, now: datetime | None = None) -> dict[str, Any]:
    current = now or _now()
    previous = _read_json(DASHBOARD_STATE_PATH)
    if not force and already_ran_today(previous, current):
        return {
            "skipped": True,
            "reason": "already_ran_today",
            "last_run_at": previous.get("last_run_at", ""),
        }

    snapshots = load_scraper_snapshots()
    dashboard = evaluate_dashboard(snapshots, previous, current)
    report_text = render_report(dashboard)

    _write_json(DASHBOARD_JSON_PATH, dashboard)
    DASHBOARD_TEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_TEXT_PATH.write_text(report_text, encoding="utf-8")

    state = dict(dashboard)
    state["last_run_at"] = current.isoformat(timespec="seconds")
    _write_json(DASHBOARD_STATE_PATH, state)
    return {
        "skipped": False,
        "dashboard": dashboard,
        "report_text": report_text,
        "json_path": str(DASHBOARD_JSON_PATH),
        "text_path": str(DASHBOARD_TEXT_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build scraper health dashboard.")
    parser.add_argument("--force", action="store_true", help="Run even if dashboard already ran today.")
    args = parser.parse_args()

    result = build_dashboard(force=args.force)
    if result.get("skipped"):
        print(f"scraper_dashboard: skipped reason={result.get('reason')}")
        return 0
    print(str(result.get("report_text") or "").rstrip())
    print(f"wrote: {result.get('text_path')}")
    print(f"wrote: {result.get('json_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
