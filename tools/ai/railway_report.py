#!/usr/bin/env python3
"""鉄道インシデント履歴から月報を作る。"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
HISTORY_PATH = AI_DIR / "railway_history.yml"
REPORT_PATH = AI_DIR / "railway_monthly_report.txt"

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from railway_history import load_history  # noqa: E402


def parse_started_at(record: dict[str, Any]) -> datetime | None:
    value = record.get("started_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def build_monthly_report(records: list[dict[str, Any]], target: datetime | None = None) -> str:
    if target is None:
        target = datetime.now().astimezone()

    by_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        started_at = parse_started_at(record)
        if started_at is None:
            continue
        if started_at.year == target.year and started_at.month == target.month:
            by_line[str(record.get("line") or "鉄道運行情報")].append(record)

    lines = [f"{target.year}年{target.month}月"]
    if not by_line:
        lines.append("鉄道インシデント履歴なし")
        return "\n".join(lines) + "\n"

    for line in sorted(by_line):
        incidents = by_line[line]
        severity_counts = Counter(str(record.get("severity") or "info") for record in incidents)
        reason_counts: Counter[str] = Counter()
        durations: list[int] = []
        longest_record: dict[str, Any] | None = None
        longest_duration = -1

        for record in incidents:
            for reason in record.get("reasons") or []:
                reason_text = str(reason or "").strip()
                if reason_text:
                    reason_counts[reason_text] += 1
            duration = record.get("duration_minutes")
            if isinstance(duration, int):
                durations.append(duration)
                if duration > longest_duration:
                    longest_duration = duration
                    longest_record = record

        average_duration = int(sum(durations) / len(durations)) if durations else 0
        longest_date = ""
        if longest_record is not None:
            started_at = parse_started_at(longest_record)
            if started_at is not None:
                longest_date = f"({started_at:%Y-%m-%d})"

        lines.extend(
            [
                line,
                f"発生回数: {len(incidents)}回",
                "重大度",
                f"critical: {severity_counts.get('critical', 0)}",
                f"warning: {severity_counts.get('warning', 0)}",
                f"info: {severity_counts.get('info', 0)}",
                "原因",
            ]
        )
        if reason_counts:
            for reason, count in reason_counts.most_common():
                lines.append(f"{reason}: {count}")
        else:
            lines.append("なし: 0")
        lines.extend(
            [
                "平均継続時間",
                f"{average_duration}分",
                "最長",
                f"{max(durations) if durations else 0}分",
            ]
        )
        if longest_date:
            lines.append(longest_date)

    return "\n".join(lines) + "\n"


def main() -> int:
    records = load_history(HISTORY_PATH)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(build_monthly_report(records), encoding="utf-8")
    print(f"wrote: {REPORT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
