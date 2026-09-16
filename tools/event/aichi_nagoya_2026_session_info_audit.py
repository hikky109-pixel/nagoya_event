#!/usr/bin/env python3
"""Read-only audit of safe Asia Games session_info candidates from Results."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.utils.google_sheet_events import ASIA_OPERATIONAL_COLUMNS
from tools.event.aichi_nagoya_2026_availability_update_audit import (
    parse_content_classifications,
)
from tools.event.aichi_nagoya_2026_availability_updater import (
    validate_content_reference,
)
from tools.event.aichi_nagoya_2026_results import external_request_timeout
from tools.event.aichi_nagoya_2026_results_audit import (
    DATE_MISMATCH,
    EXACT_MATCH,
    MULTIPLE_CANDIDATES,
    RESULTS_NOT_FOUND,
    TIME_MISMATCH,
    VENUE_MISMATCH,
    audit_sheet_rows,
    fetch_full_results_period,
)
from tools.event.aichi_nagoya_2026_results_dry_run import (
    DRY_RUN_OVERALL_TIMEOUT_SECONDS,
    load_asia_sheet_rows_read_only,
)


SAFE_TO_UPDATE = "SAFE_TO_UPDATE"
UNCHANGED = "UNCHANGED"
HOLD_TIME_MISMATCH = "HOLD_TIME_MISMATCH"
HOLD_DATE_MISMATCH = "HOLD_DATE_MISMATCH"
HOLD_VENUE_MISMATCH = "HOLD_VENUE_MISMATCH"
HOLD_MULTIPLE_CANDIDATES = "HOLD_MULTIPLE_CANDIDATES"
HOLD_RESULTS_NOT_FOUND = "HOLD_RESULTS_NOT_FOUND"
HOLD_CONTENT_OUTDATED = "HOLD_CONTENT_OUTDATED"
NEEDS_REVIEW = "NEEDS_REVIEW"
CLASSIFICATIONS = (
    SAFE_TO_UPDATE,
    UNCHANGED,
    HOLD_TIME_MISMATCH,
    HOLD_DATE_MISMATCH,
    HOLD_VENUE_MISMATCH,
    HOLD_MULTIPLE_CANDIDATES,
    HOLD_RESULTS_NOT_FOUND,
    HOLD_CONTENT_OUTDATED,
    NEEDS_REVIEW,
)
RESULTS_TO_HOLD = {
    TIME_MISMATCH: HOLD_TIME_MISMATCH,
    DATE_MISMATCH: HOLD_DATE_MISMATCH,
    VENUE_MISMATCH: HOLD_VENUE_MISMATCH,
    MULTIPLE_CANDIDATES: HOLD_MULTIPLE_CANDIDATES,
    RESULTS_NOT_FOUND: HOLD_RESULTS_NOT_FOUND,
}
CONTENT_REVIEW_STATES = {"INSUFFICIENT_SHEET_INFO", "NEEDS_REVIEW"}
EXCLUDED_EVENTS = {"開会式", "閉会式"}
CSV_FIELDS = (
    "sheet_row_number",
    "date",
    "time",
    "venue",
    "event_name",
    "current_session_info",
    "candidate_session_info",
    "result_code",
    "classification",
    "decision_reason",
    "results_audit_state",
    "content_audit_state",
    "aggregation_state",
    "is_japan_match",
)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _comparable(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return "".join(character for character in text if character not in " \t\r\n　()（）[]［］・,，/／")


def _candidate_is_japan_match(candidate: dict[str, Any]) -> bool:
    competitors = candidate.get("competitors") or {}
    return any(
        str((competitors.get(side) or {}).get("organization") or "").upper() == "JPN"
        for side in ("home", "away")
    )


def classify_row(
    sheet_row_number: int,
    results_row: dict[str, Any],
    content_state: str,
) -> dict[str, Any]:
    """Classify one row without ever selecting among multiple Results units."""

    sheet = results_row["sheet"]
    event_name = str(sheet.get("event_name") or "").strip()
    current = str(sheet.get("session_info") or "").strip()
    output = {
        "sheet_row_number": sheet_row_number,
        "sheet": {column: sheet.get(column, "") for column in ASIA_OPERATIONAL_COLUMNS},
        "current_session_info": current,
        "candidate_session_info": "",
        "result_code": "",
        "classification": NEEDS_REVIEW,
        "decision_reason": "",
        "results_audit_state": results_row.get("classification", ""),
        "results_candidate_count": int(results_row.get("candidate_count") or 0),
        "content_audit_state": content_state,
        "aggregation_state": "NOT_APPLICABLE",
        "is_japan_match": False,
    }

    if "発火テスト" in event_name or event_name in EXCLUDED_EVENTS:
        output["classification"] = HOLD_RESULTS_NOT_FOUND
        output["decision_reason"] = "ceremony/test row is outside automatic Results session_info updates"
        return output

    results_state = output["results_audit_state"]
    if results_state in RESULTS_TO_HOLD:
        output["classification"] = RESULTS_TO_HOLD[results_state]
        if results_state == MULTIPLE_CANDIDATES:
            output["aggregation_state"] = "MULTIPLE_RESULTS_NOT_COMBINED"
            output["result_code"] = ",".join(
                str(item.get("result_code") or "").strip()
                for item in results_row.get("results_candidates") or []
                if str(item.get("result_code") or "").strip()
            )
        output["decision_reason"] = (
            f"Results audit state {results_state} does not provide one safe identity"
        )
        return output
    if results_state != EXACT_MATCH:
        output["classification"] = NEEDS_REVIEW
        output["decision_reason"] = f"unsupported Results audit state: {results_state}"
        return output

    candidates = results_row.get("results_candidates") or []
    if len(candidates) != 1:
        output["classification"] = HOLD_MULTIPLE_CANDIDATES
        output["decision_reason"] = "EXACT_MATCH did not contain exactly one Results candidate"
        return output
    candidate = candidates[0]
    output["result_code"] = str(candidate.get("result_code") or "").strip()
    output["is_japan_match"] = _candidate_is_japan_match(candidate)
    output["aggregation_state"] = "SINGLE_RESULT"
    generated = str(candidate.get("session_info_candidate") or "").strip()
    output["candidate_session_info"] = generated

    if content_state == "CONTENT_OUTDATED":
        output["classification"] = HOLD_CONTENT_OUTDATED
        output["decision_reason"] = "content audit found an explicit Sheet/Results contradiction"
        return output
    if content_state in CONTENT_REVIEW_STATES:
        output["classification"] = NEEDS_REVIEW
        output["decision_reason"] = f"content audit remains unresolved: {content_state}"
        return output
    if content_state not in {"CONTENT_MATCH", "AGGREGATED_OK"}:
        output["classification"] = NEEDS_REVIEW
        output["decision_reason"] = f"content audit state is not approved: {content_state}"
        return output

    if candidate.get("is_head_to_head") and candidate.get("is_team_event"):
        matchup = str(candidate.get("matchup") or "").strip()
        if not matchup:
            output["classification"] = NEEDS_REVIEW
            output["decision_reason"] = "team Results unit has no complete Org-derived matchup"
            return output
    if not output["result_code"]:
        output["classification"] = NEEDS_REVIEW
        output["decision_reason"] = "exact Results aggregate has no ResCode; session identity is not stable"
        return output
    if not generated:
        output["classification"] = NEEDS_REVIEW
        output["decision_reason"] = "official phase/session labels cannot produce a non-empty candidate"
        return output

    if _comparable(current) == _comparable(generated):
        output["classification"] = UNCHANGED
        output["decision_reason"] = "current and generated session_info are equivalent after display normalization"
    else:
        output["classification"] = SAFE_TO_UPDATE
        output["decision_reason"] = (
            "one exact date/time/venue/sport Results unit and one stable session_info candidate"
        )
    return output


def audit_session_info_rows(
    results_rows: Iterable[dict[str, Any]],
    content_classifications: dict[int, str],
) -> list[dict[str, Any]]:
    audited: list[dict[str, Any]] = []
    for sheet_data_row, results_row in enumerate(results_rows, start=1):
        sheet_row_number = sheet_data_row + 1
        event_name = str(results_row.get("sheet", {}).get("event_name") or "").strip()
        content_state = (
            "NOT_APPLICABLE"
            if "発火テスト" in event_name or event_name in EXCLUDED_EVENTS
            else content_classifications.get(sheet_data_row, "MISSING")
        )
        audited.append(classify_row(sheet_row_number, results_row, content_state))
    return audited


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(rows)
    counts = Counter(row["classification"] for row in records)
    candidates = [row for row in records if row["candidate_session_info"]]
    labels = [row["candidate_session_info"] for row in candidates]
    return {
        "classifications": {name: counts.get(name, 0) for name in CLASSIFICATIONS},
        "japan_match_candidates": sum(row["is_japan_match"] for row in candidates),
        "quarterfinal_candidates": sum("準々決勝" in label for label in labels),
        "semifinal_candidates": sum("準決勝" in label and "準々決勝" not in label for label in labels),
        "bronze_match_candidates": sum("3位決定戦" in label for label in labels),
        "final_candidates": sum(
            "決勝" in label
            and "準々決勝" not in label
            and "準決勝" not in label
            and "3位決定戦" not in label
            for label in labels
        ),
    }


def run_audit(
    *,
    content_classifications: dict[int, str],
    content_reference: dict[str, Any],
    sheet_loader: Callable[[], list[dict[str, str]]] | None = None,
    matrix_fetcher: Callable[[], Any] | None = None,
    day_fetcher: Callable[[str], Any] | None = None,
    daily_fetcher: Callable[[str, str], list[dict[str, Any]]] | None = None,
    overall_timeout: float = 240.0,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    emit = progress or _progress
    started = time.monotonic()
    deadline = started + float(overall_timeout)
    emit(f"session_info_audit stage=start overall_timeout_s={overall_timeout:g} sheet_write=false")
    with external_request_timeout(overall_timeout, "session_info full-period audit"):
        sheet_rows = (sheet_loader or load_asia_sheet_rows_read_only)()
        if len(sheet_rows) != 245:
            raise ValueError(f"expected 245 Sheet rows, got {len(sheet_rows)}")
        validate_content_reference(sheet_rows, content_reference)
        emit(f"session_info_audit stage=sheet_verified rows={len(sheet_rows)} schema=7")
        official_dates, results = fetch_full_results_period(
            sheet_rows,
            matrix_fetcher=matrix_fetcher,
            day_fetcher=day_fetcher,
            daily_fetcher=daily_fetcher,
            deadline=deadline,
            progress=emit,
        )
        results_rows = audit_sheet_rows(sheet_rows, results)
        rows = audit_session_info_rows(results_rows, content_classifications)
        summary = summarize(rows)
    emit(
        "session_info_audit stage=complete "
        f"elapsed_s={time.monotonic() - started:.3f} sheet_write=false "
        + " ".join(f"{key}={value}" for key, value in summary["classifications"].items())
    )
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dry_run": True,
        "sheet_write": False,
        "target_column": "session_info",
        "sheet_schema": list(ASIA_OPERATIONAL_COLUMNS),
        "sheet_row_count": len(sheet_rows),
        "official_date_count": len(official_dates),
        "results_record_count": len(results),
        "summary": summary,
        "rows": rows,
    }


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# アジア大会 session_info Results補完 read-only監査",
        "",
        f"- 生成日時: `{report['generated_at']}`",
        "- Google Sheet書き込み: `false`",
        f"- Sheet行数: {report['sheet_row_count']}",
        "- 更新候補列: `session_info`（今回は変更なし）",
        "",
        "## 判定件数",
        "",
        "| 判定 | 件数 |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {name} | {summary['classifications'][name]} |" for name in CLASSIFICATIONS)
    lines.extend(
        [
            "",
            "## 優先候補集計",
            "",
            f"- 日本戦候補数: {summary['japan_match_candidates']}",
            f"- 準々決勝候補数: {summary['quarterfinal_candidates']}",
            f"- 準決勝候補数: {summary['semifinal_candidates']}",
            f"- 3位決定戦候補数: {summary['bronze_match_candidates']}",
            f"- 決勝候補数: {summary['final_candidates']}",
        ]
    )
    for classification in CLASSIFICATIONS:
        selected = [row for row in report["rows"] if row["classification"] == classification]
        lines.extend(
            [
                "",
                f"## {classification} ({len(selected)}件)",
                "",
                "| Sheet行 | date | time | venue | event_name | current_session_info | candidate_session_info | ResCode | 判定理由 |",
                "| ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in selected:
            sheet = row["sheet"]
            lines.append(
                f"| {row['sheet_row_number']} | {_md(sheet['date'])} | {_md(sheet['time'])} | "
                f"{_md(sheet['venue'])} | {_md(sheet['event_name'])} | "
                f"{_md(row['current_session_info'])} | {_md(row['candidate_session_info']) or '-'} | "
                f"{_md(row['result_code']) or '-'} | {_md(row['decision_reason'])} |"
            )
    lines.extend(["", "Google Sheet、session_info、availability_status、その他列は変更していない。", ""])
    return "\n".join(lines)


def write_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in report["rows"]:
            sheet = row["sheet"]
            writer.writerow(
                {
                    "sheet_row_number": row["sheet_row_number"],
                    "date": sheet["date"],
                    "time": sheet["time"],
                    "venue": sheet["venue"],
                    "event_name": sheet["event_name"],
                    "current_session_info": row["current_session_info"],
                    "candidate_session_info": row["candidate_session_info"],
                    "result_code": row["result_code"],
                    "classification": row["classification"],
                    "decision_reason": row["decision_reason"],
                    "results_audit_state": row["results_audit_state"],
                    "content_audit_state": row["content_audit_state"],
                    "aggregation_state": row["aggregation_state"],
                    "is_japan_match": row["is_japan_match"],
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-audit", type=Path, required=True)
    parser.add_argument("--content-reference-results", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--overall-timeout", type=float, default=240.0)
    args = parser.parse_args()
    content = parse_content_classifications(args.content_audit.read_text(encoding="utf-8"))
    reference = json.loads(args.content_reference_results.read_text(encoding="utf-8"))
    report = run_audit(
        content_classifications=content,
        content_reference=reference,
        overall_timeout=args.overall_timeout,
    )
    prefix = args.output_prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    prefix.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    write_csv(prefix.with_suffix(".csv"), report)
    print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
