#!/usr/bin/env python3
"""Audit every Asia Games Sheet row against the official Japanese Results API.

This command is read-only.  It never writes Google Sheets, CSV files, or BOT
state, and it never selects a mismatch candidate as an automatic correction.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.utils.google_sheet_events import ASIA_OPERATIONAL_COLUMNS
from tools.event.aichi_nagoya_2026_results import (
    RESULTS_DEFAULT_LANGUAGE,
    RESULTS_HARD_TIMEOUT_SECONDS,
    ExternalRequestTimeout,
    external_request_timeout,
    extract_discipline_codes,
    fetch_day_schedule,
    fetch_normalized_discipline_daily,
    fetch_schedule_matrix,
)
from tools.event.aichi_nagoya_2026_results_dry_run import (
    DISCIPLINE_CANONICAL,
    DRY_RUN_OVERALL_TIMEOUT_SECONDS,
    SHEET_HARD_TIMEOUT_SECONDS,
    _remaining_hard_timeout,
    _result_projection,
    load_asia_sheet_rows_read_only,
    normalize_date,
    normalize_sport,
    normalize_time,
    normalize_venue,
)


EXACT_MATCH = "EXACT_MATCH"
TIME_MISMATCH = "TIME_MISMATCH"
VENUE_MISMATCH = "VENUE_MISMATCH"
DATE_MISMATCH = "DATE_MISMATCH"
MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
RESULTS_NOT_FOUND = "RESULTS_NOT_FOUND"
AUDIT_CLASSIFICATIONS = (
    EXACT_MATCH,
    TIME_MISMATCH,
    VENUE_MISMATCH,
    DATE_MISMATCH,
    MULTIPLE_CANDIDATES,
    RESULTS_NOT_FOUND,
)
NEAREST_RESULTS_LIMIT = 5


def _emit_progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _stderr_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _date_distance_days(left: Any, right: Any) -> int | None:
    try:
        return abs(
            (date.fromisoformat(normalize_date(left)) - date.fromisoformat(normalize_date(right))).days
        )
    except ValueError:
        return None


def _time_distance_minutes(left: Any, right: Any) -> int | None:
    try:
        left_time = datetime.strptime(normalize_time(left), "%H:%M:%S")
        right_time = datetime.strptime(normalize_time(right), "%H:%M:%S")
    except ValueError:
        return None
    return int(abs((left_time - right_time).total_seconds()) // 60)


def _candidate_sort_key(
    sheet_row: dict[str, str], record: dict[str, Any]
) -> tuple[Any, ...]:
    date_distance = _date_distance_days(sheet_row.get("date"), record.get("date"))
    time_distance = _time_distance_minutes(sheet_row.get("time"), record.get("time"))
    venue_mismatch = int(
        normalize_venue(sheet_row.get("venue")) != normalize_venue(record.get("venue_name"))
    )
    return (
        venue_mismatch,
        date_distance if date_distance is not None else 10**9,
        time_distance if time_distance is not None else 10**9,
        normalize_date(record.get("date")),
        normalize_time(record.get("time")),
        str(record.get("venue_name") or ""),
        str(record.get("result_code") or ""),
    )


def _diagnostic_projection(
    sheet_row: dict[str, str], record: dict[str, Any]
) -> dict[str, Any]:
    projected = _result_projection(record)
    projected.update(
        {
            "result_code": record.get("result_code", ""),
            "date_delta_days": _date_distance_days(
                sheet_row.get("date"), record.get("date")
            ),
            "time_delta_minutes": _time_distance_minutes(
                sheet_row.get("time"), record.get("time")
            ),
            "date_matches": normalize_date(sheet_row.get("date"))
            == normalize_date(record.get("date")),
            "time_matches": normalize_time(sheet_row.get("time"))
            == normalize_time(record.get("time")),
            "venue_matches": normalize_venue(sheet_row.get("venue"))
            == normalize_venue(record.get("venue_name")),
        }
    )
    return projected


def classify_audit_row(
    sheet_row: dict[str, str], results: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Classify one row without treating a diagnostic candidate as a correction."""

    records = list(results)
    sheet_date = normalize_date(sheet_row.get("date"))
    sheet_time = normalize_time(sheet_row.get("time"))
    sheet_venue = normalize_venue(sheet_row.get("venue"))
    sheet_sport = normalize_sport(sheet_row.get("event_name"))

    sport_candidates = [
        record
        for record in records
        if normalize_sport(
            record.get("discipline_name"), record.get("discipline_code")
        )
        == sheet_sport
    ]
    exact_candidates = [
        record
        for record in sport_candidates
        if normalize_date(record.get("date")) == sheet_date
        and normalize_time(record.get("time")) == sheet_time
        and normalize_venue(record.get("venue_name")) == sheet_venue
    ]
    same_date_venue = [
        record
        for record in sport_candidates
        if normalize_date(record.get("date")) == sheet_date
        and normalize_venue(record.get("venue_name")) == sheet_venue
    ]
    same_date_time = [
        record
        for record in sport_candidates
        if normalize_date(record.get("date")) == sheet_date
        and normalize_time(record.get("time")) == sheet_time
    ]
    same_time_venue_other_date = [
        record
        for record in sport_candidates
        if normalize_date(record.get("date")) != sheet_date
        and normalize_time(record.get("time")) == sheet_time
        and normalize_venue(record.get("venue_name")) == sheet_venue
    ]

    if len(exact_candidates) == 1:
        classification = EXACT_MATCH
        selected = exact_candidates
        reason = "date/time/venue/sport matched exactly after explicit aliases"
    elif len(exact_candidates) > 1:
        classification = MULTIPLE_CANDIDATES
        selected = exact_candidates
        reason = "multiple Results units share the exact normalized key"
    elif same_date_venue:
        classification = TIME_MISMATCH
        selected = same_date_venue
        reason = "date/venue/sport matched, but time did not"
    elif same_date_time:
        classification = VENUE_MISMATCH
        selected = same_date_time
        if all(not str(record.get("venue_name") or "").strip() for record in selected):
            reason = (
                "date/time/sport matched, but official Results VenueDesc is empty; "
                "Sheet venue cannot be validated"
            )
        else:
            reason = "date/time/sport matched, but venue alias did not"
    elif same_time_venue_other_date:
        classification = DATE_MISMATCH
        nearest_days = min(
            _date_distance_days(sheet_date, record.get("date")) or 0
            for record in same_time_venue_other_date
        )
        selected = [
            record
            for record in same_time_venue_other_date
            if _date_distance_days(sheet_date, record.get("date")) == nearest_days
        ]
        reason = "time/venue/sport matched on the nearest different Results date"
    else:
        classification = RESULTS_NOT_FOUND
        selected = sorted(
            sport_candidates,
            key=lambda record: _candidate_sort_key(sheet_row, record),
        )[:NEAREST_RESULTS_LIMIT]
        reason = (
            "no Results unit matched three audit keys; nearest same-sport records "
            "are diagnostic only"
            if selected
            else "official Results contains no candidate for the normalized sport"
        )

    selected = sorted(selected, key=lambda record: _candidate_sort_key(sheet_row, record))
    return {
        "classification": classification,
        "candidate_count": len(selected),
        "same_sport_candidate_count": len(sport_candidates),
        "reason": reason,
        "sheet": {
            column: sheet_row.get(column, "") for column in ASIA_OPERATIONAL_COLUMNS
        },
        "results_candidates": [
            _diagnostic_projection(sheet_row, record) for record in selected
        ],
        "auto_selected": False,
    }


def audit_sheet_rows(
    sheet_rows: Iterable[dict[str, str]], results: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    records = list(results)
    return [classify_audit_row(row, records) for row in sheet_rows]


def summarize(audit_rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(row.get("classification") for row in audit_rows)
    return {classification: counts.get(classification, 0) for classification in AUDIT_CLASSIFICATIONS}


def fetch_full_results_period(
    sheet_rows: list[dict[str, str]],
    *,
    matrix_fetcher: Callable[[], Any] | None = None,
    day_fetcher: Callable[[str], Any] | None = None,
    daily_fetcher: Callable[[str, str], list[dict[str, Any]]] | None = None,
    deadline: float | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Fetch relevant disciplines for every official date in the schedule matrix."""

    matrix_hard_timeout = _remaining_hard_timeout(
        deadline, RESULTS_HARD_TIMEOUT_SECONDS, "results_matrix"
    )
    _emit_progress(progress, "full_audit_progress stage=results_matrix_start language=ja")
    if matrix_fetcher is None:
        matrix = fetch_schedule_matrix(
            language=RESULTS_DEFAULT_LANGUAGE,
            hard_timeout=matrix_hard_timeout,
            progress=progress,
        )
    else:
        matrix = matrix_fetcher()
    if not isinstance(matrix, dict) or not isinstance(matrix.get("dates"), list):
        raise ValueError("Results schedule matrix has no dates list")
    official_dates = [normalize_date(value) for value in matrix["dates"]]
    if not official_dates or any(not value for value in official_dates):
        raise ValueError("Results schedule matrix dates are empty or invalid")

    sheet_sports = {normalize_sport(row.get("event_name")) for row in sheet_rows}
    relevant_codes = {
        code
        for code, canonical in DISCIPLINE_CANONICAL.items()
        if canonical in sheet_sports
    }
    _emit_progress(
        progress,
        "full_audit_progress stage=results_matrix_done "
        f"dates={len(official_dates)} relevant_disciplines={len(relevant_codes)}",
    )

    records: list[dict[str, Any]] = []
    daily_request_index = 0
    for date_index, target_date in enumerate(official_dates, start=1):
        overview_hard_timeout = _remaining_hard_timeout(
            deadline, RESULTS_HARD_TIMEOUT_SECONDS, f"results_day_{target_date}"
        )
        _emit_progress(
            progress,
            "full_audit_progress stage=results_day_start "
            f"date={target_date} index={date_index}/{len(official_dates)}",
        )
        if day_fetcher is None:
            overview = fetch_day_schedule(
                target_date,
                language=RESULTS_DEFAULT_LANGUAGE,
                hard_timeout=overview_hard_timeout,
                progress=progress,
            )
        else:
            overview = day_fetcher(target_date)
        disciplines = [
            code
            for code in extract_discipline_codes(overview)
            if code in relevant_codes
        ]
        _emit_progress(
            progress,
            "full_audit_progress stage=results_day_overview_done "
            f"date={target_date} relevant_count={len(disciplines)} "
            f"disciplines={','.join(disciplines)}",
        )
        day_record_count = 0
        for discipline in disciplines:
            daily_request_index += 1
            daily_hard_timeout = _remaining_hard_timeout(
                deadline,
                RESULTS_HARD_TIMEOUT_SECONDS,
                f"results_daily_{target_date}_{discipline}",
            )
            _emit_progress(
                progress,
                "full_audit_progress stage=results_daily_start "
                f"request_index={daily_request_index} date={target_date} "
                f"discipline={discipline}",
            )
            started = time.monotonic()
            if daily_fetcher is None:
                daily = fetch_normalized_discipline_daily(
                    discipline,
                    target_date,
                    language=RESULTS_DEFAULT_LANGUAGE,
                    hard_timeout=daily_hard_timeout,
                    progress=progress,
                )
            else:
                daily = daily_fetcher(discipline, target_date)
            if not isinstance(daily, list) or not daily:
                raise ValueError(
                    "Results daily is empty; refusing partial full-period audit: "
                    f"date={target_date} discipline={discipline}"
                )
            selected = [
                record
                for record in daily
                if normalize_date(record.get("date")) == target_date
            ]
            if not selected:
                raise ValueError(
                    "Results daily has no normalized records for requested date: "
                    f"date={target_date} discipline={discipline}"
                )
            records.extend(selected)
            day_record_count += len(selected)
            _emit_progress(
                progress,
                "full_audit_progress stage=results_daily_done "
                f"request_index={daily_request_index} date={target_date} "
                f"discipline={discipline} records={len(selected)} "
                f"elapsed_s={time.monotonic() - started:.3f}",
            )
        _emit_progress(
            progress,
            "full_audit_progress stage=results_day_done "
            f"date={target_date} index={date_index}/{len(official_dates)} "
            f"records={day_record_count}",
        )
    if not records:
        raise ValueError("Results full-period audit fetched zero relevant records")
    return official_dates, records


def run_full_audit(
    *,
    sheet_loader: Callable[[], list[dict[str, str]]] | None = None,
    matrix_fetcher: Callable[[], Any] | None = None,
    day_fetcher: Callable[[str], Any] | None = None,
    daily_fetcher: Callable[[str, str], list[dict[str, Any]]] | None = None,
    overall_timeout: float = DRY_RUN_OVERALL_TIMEOUT_SECONDS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run a bounded, read-only audit for all operational Sheet rows."""

    overall_timeout = float(overall_timeout)
    if overall_timeout <= 0:
        raise ValueError("full audit overall timeout must be greater than zero")
    started = time.monotonic()
    deadline = started + overall_timeout
    stage = "start"
    _emit_progress(
        progress,
        "full_audit_progress stage=start "
        f"overall_timeout_s={overall_timeout:g} language=ja sheet_write=false",
    )
    try:
        with external_request_timeout(overall_timeout, "Results full-period audit"):
            stage = "sheet_fetch"
            sheet_hard_timeout = _remaining_hard_timeout(
                deadline, SHEET_HARD_TIMEOUT_SECONDS, stage
            )
            _emit_progress(progress, "full_audit_progress stage=sheet_fetch_start")
            if sheet_loader is None:
                sheet_rows = load_asia_sheet_rows_read_only(
                    hard_timeout=sheet_hard_timeout,
                    progress=progress,
                )
            else:
                sheet_rows = sheet_loader()
            if not sheet_rows:
                raise ValueError("Asia Games Sheet has zero audit rows")
            _emit_progress(
                progress,
                f"full_audit_progress stage=sheet_fetch_done rows={len(sheet_rows)}",
            )

            stage = "results_fetch"
            official_dates, results = fetch_full_results_period(
                sheet_rows,
                matrix_fetcher=matrix_fetcher,
                day_fetcher=day_fetcher,
                daily_fetcher=daily_fetcher,
                deadline=deadline,
                progress=progress,
            )

            stage = "classify"
            _remaining_hard_timeout(deadline, overall_timeout, stage)
            _emit_progress(
                progress,
                "full_audit_progress stage=classify_start "
                f"sheet_rows={len(sheet_rows)} results_records={len(results)}",
            )
            audited = audit_sheet_rows(sheet_rows, results)
            summary = summarize(audited)
            report = {
                "dry_run": True,
                "full_period_audit": True,
                "sheet_write": False,
                "results_language": RESULTS_DEFAULT_LANGUAGE,
                "sheet_schema": list(ASIA_OPERATIONAL_COLUMNS),
                "sheet_row_count": len(sheet_rows),
                "official_date_count": len(official_dates),
                "official_date_min": min(official_dates),
                "official_date_max": max(official_dates),
                "results_record_count": len(results),
                "summary": summary,
                "rows": audited,
            }
        _emit_progress(
            progress,
            "full_audit_progress stage=complete "
            f"elapsed_s={time.monotonic() - started:.3f} "
            + " ".join(f"{key}={summary[key]}" for key in AUDIT_CLASSIFICATIONS)
            + " sheet_write=false",
        )
        return report
    except Exception as exc:
        _emit_progress(
            progress,
            "full_audit_progress stage=failed "
            f"current_stage={stage} elapsed_s={time.monotonic() - started:.3f} "
            f"error_type={type(exc).__name__} error={exc}",
        )
        raise


def _render_candidate(lines: list[str], candidate: dict[str, Any], index: int) -> None:
    lines.extend(
        [
            (
                f"  Results[{index}] diagnostic_only: date={candidate['date']} "
                f"time={candidate['time']} venue={candidate['venue']} "
                f"sport={candidate['sport']}"
            ),
            (
                f"    date_delta_days={candidate['date_delta_days']} "
                f"time_delta_minutes={candidate['time_delta_minutes']} "
                f"venue_matches={str(candidate['venue_matches']).lower()}"
            ),
            (
                f"    phase={candidate['phase']} round={candidate['round']} "
                f"UnitDesc={candidate['session']}"
            ),
        ]
    )
    if candidate["is_head_to_head"]:
        lines.append(f"    matchup={candidate['matchup']}")
        competitors = candidate.get("competitors") or {}
        for side in ("home", "away"):
            competitor = competitors.get(side) or {}
            if competitor:
                lines.append(
                    f"    {side}: Org={competitor.get('organization', '')} "
                    f"display={competitor.get('display_name', '')} "
                    f"Name={competitor.get('name', '')}"
                )
    lines.append(f"    session_info_candidate={candidate['session_info_candidate']}")


def render_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "dry_run=true full_period_audit=true sheet_write=false language=ja",
        (
            f"SCOPE sheet_rows={report['sheet_row_count']} "
            f"official_dates={report['official_date_count']} "
            f"official_range={report['official_date_min']}..{report['official_date_max']} "
            f"results_records={report['results_record_count']}"
        ),
        "SUMMARY "
        + " ".join(f"{key}={summary[key]}" for key in AUDIT_CLASSIFICATIONS),
        "MISMATCH_ROWS",
    ]
    mismatch_index = 0
    for row_index, item in enumerate(report["rows"], start=1):
        if item["classification"] == EXACT_MATCH:
            continue
        mismatch_index += 1
        sheet = item["sheet"]
        lines.extend(
            [
                "",
                (
                    f"[{mismatch_index}] sheet_row={row_index} "
                    f"classification={item['classification']} "
                    f"candidate_count={item['candidate_count']}"
                ),
                (
                    f"  Sheet: date={sheet['date']} time={sheet['time']} "
                    f"venue={sheet['venue']} event_name={sheet['event_name']}"
                ),
                f"  Reason: {item['reason']}",
            ]
        )
        for candidate_index, candidate in enumerate(item["results_candidates"], start=1):
            _render_candidate(lines, candidate, candidate_index)
    if mismatch_index == 0:
        lines.append("none")
    return "\n".join(lines)


def _compact_candidate_lines(item: dict[str, Any]) -> list[str]:
    unique: list[str] = []
    seen: set[tuple[Any, ...]] = set()
    for candidate in item["results_candidates"]:
        label = candidate["session_info_candidate"] or candidate["phase"]
        venue = candidate["venue"] or "(公式VenueDesc空)"
        key = (candidate["date"], candidate["time"], venue, label)
        if key in seen:
            continue
        seen.add(key)
        unique.append(
            f"{candidate['date']} {candidate['time']} / {venue} / {label}"
        )
    if item["classification"] == TIME_MISMATCH:
        return unique
    if len(unique) <= 8:
        return unique
    return unique[:8] + [f"ほか{len(unique) - 8}種類（詳細はJSON参照）"]


def render_markdown(report: dict[str, Any]) -> str:
    """Render a compact complete mismatch-row index for human review."""

    summary = report["summary"]
    lines = [
        "# アジア大会 Results 全期間監査",
        "",
        "- dry-run: `true`",
        "- Sheet書き込み: `false`",
        f"- Sheet行数: {report['sheet_row_count']}",
        (
            f"- 公式期間: {report['official_date_min']}〜"
            f"{report['official_date_max']}（{report['official_date_count']}日）"
        ),
        f"- Results正規化件数: {report['results_record_count']}",
        "",
        "| 分類 | 件数 |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {classification} | {summary[classification]} |"
        for classification in AUDIT_CLASSIFICATIONS
    )
    lines.extend(
        [
            "",
            "候補はすべて診断用で、`auto_selected=false`です。"
            "TIME_MISMATCHは同日・同会場・同競技の候補を全件掲載します。",
        ]
    )

    for classification in AUDIT_CLASSIFICATIONS:
        if classification == EXACT_MATCH:
            continue
        lines.extend(
            [
                "",
                f"## {classification} ({summary[classification]}件)",
                "",
                "| Sheet行 | Sheet日時 | Sheet会場 | 競技 | 候補数 | 診断用Results候補 |",
                "| ---: | --- | --- | --- | ---: | --- |",
            ]
        )
        for row_index, item in enumerate(report["rows"], start=1):
            if item["classification"] != classification:
                continue
            sheet = item["sheet"]
            candidate_text = "<br>".join(_compact_candidate_lines(item)) or "なし"
            lines.append(
                f"| {row_index} | {sheet['date']} {sheet['time']} | "
                f"{sheet['venue']} | {sheet['event_name']} | "
                f"{item['candidate_count']} | {candidate_text} |"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        dest="output_format",
    )
    parser.add_argument(
        "--overall-timeout",
        type=float,
        default=DRY_RUN_OVERALL_TIMEOUT_SECONDS,
        help=(
            "hard wall-clock limit for all Sheet and Results reads "
            f"(default: {DRY_RUN_OVERALL_TIMEOUT_SECONDS:g}s)"
        ),
    )
    args = parser.parse_args()
    try:
        report = run_full_audit(
            overall_timeout=args.overall_timeout,
            progress=_stderr_progress,
        )
    except Exception as exc:
        print(
            f"full_audit_error error_type={type(exc).__name__} error={exc}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from None
    if args.output_format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.output_format == "markdown":
        print(render_markdown(report))
    else:
        print(render_text(report))


if __name__ == "__main__":
    main()
