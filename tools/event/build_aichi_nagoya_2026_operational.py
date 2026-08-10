#!/usr/bin/env python3
"""Build taxi-operational rows without modifying the immutable baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


OPERATIONAL_FIELDS = [
    "date",
    "time",
    "end_time",
    "venue",
    "event_name",
    "session_info",
    "availability_status",
]
REQUIRED_BASELINE_FIELDS = {
    "snapshot_date",
    "event_type",
    "idProduct",
    "idPerformance",
    "sessionCode",
}
REQUIRED_CANDIDATE_FIELDS = REQUIRED_BASELINE_FIELDS | set(OPERATIONAL_FIELDS) | {"db_display_name"}


def _read_dict_rows(path: Path, required_fields: set[str]) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = required_fields - set(fields)
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path} contains zero records")
    return fields, rows


def _stable_ids(row: dict[str, str]) -> tuple[str, str, str]:
    return row["idPerformance"], row["idProduct"], row["sessionCode"]


def build_operational_rows(
    baseline_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    if not baseline_rows:
        raise ValueError("baseline contains zero records")
    if not candidate_rows:
        raise ValueError("venue candidates contain zero records")
    baseline_ids = {_stable_ids(row) for row in baseline_rows}
    unresolved = 0
    output: list[dict[str, str]] = []
    event_type_counts = {
        "competition": 0,
        "opening_ceremony": 0,
        "closing_ceremony": 0,
    }
    for row in candidate_rows:
        if _stable_ids(row) not in baseline_ids:
            raise ValueError(f"candidate not found in immutable baseline: {_stable_ids(row)}")
        display_venue = row.get("db_display_name", "").strip()
        if not display_venue:
            unresolved += 1
            continue
        event_type = row.get("event_type", "")
        if event_type not in event_type_counts:
            raise ValueError(f"unexpected event_type={event_type!r}")
        event_name = row.get("event_name", "")
        if event_type == "opening_ceremony":
            event_name = "開会式"
        elif event_type == "closing_ceremony":
            event_name = "閉会式"
        output.append(
            {
                "date": row.get("date", ""),
                "time": row.get("time", ""),
                "end_time": row.get("end_time", ""),
                "venue": display_venue,
                "event_name": event_name,
                "session_info": row.get("session_info", ""),
                "availability_status": row.get("availability_status", ""),
            }
        )
        event_type_counts[event_type] += 1
    if unresolved:
        raise ValueError(f"operational venue resolution failed for {unresolved} records")
    if not output:
        raise ValueError("operational extraction produced zero records")
    output.sort(key=lambda row: (row["date"], row["time"], row["venue"]))
    stats = {
        "asia_operational_source_records": len(baseline_rows),
        "asia_operational_candidate_records": len(candidate_rows),
        "asia_operational_output_records": len(output),
        "asia_operational_competition_records": event_type_counts["competition"],
        "asia_operational_opening_records": event_type_counts["opening_ceremony"],
        "asia_operational_closing_records": event_type_counts["closing_ceremony"],
        "asia_operational_venue_unresolved": unresolved,
    }
    return output, stats


def write_operational_csv(path: Path, rows: list[dict[str, str]]) -> str:
    if not rows:
        raise ValueError("refusing to write empty operational CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OPERATIONAL_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_operational_csv(
    baseline_path: Path,
    candidates_path: Path,
    output_path: Path,
) -> dict[str, object]:
    baseline_before = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    _, baseline_rows = _read_dict_rows(baseline_path, REQUIRED_BASELINE_FIELDS)
    _, candidate_rows = _read_dict_rows(candidates_path, REQUIRED_CANDIDATE_FIELDS)
    rows, stats = build_operational_rows(baseline_rows, candidate_rows)
    output_sha256 = write_operational_csv(output_path, rows)
    baseline_after = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    if baseline_after != baseline_before:
        raise RuntimeError("immutable baseline changed while building operational data")
    report = {
        **stats,
        "baseline_sha256": baseline_after,
        "output_sha256": output_sha256,
        "output_path": str(output_path),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("data/aichi_nagoya_2026/baseline/baseline_sessions_20260810.csv"),
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/aichi_nagoya_2026/baseline/venue_candidates_20260810.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/aichi_nagoya_2026/operational/asia_games_operational_20260810.csv"),
    )
    args = parser.parse_args()
    create_operational_csv(args.baseline, args.candidates, args.output)


if __name__ == "__main__":
    main()
