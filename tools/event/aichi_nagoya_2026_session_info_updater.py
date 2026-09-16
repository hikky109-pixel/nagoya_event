#!/usr/bin/env python3
"""Safely plan or apply F-column session_info updates from official Results.

No arguments and ``--dry-run`` are read-only. ``--apply`` is the only path
that creates an authenticated Google Sheets service or writes any cell.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.utils.google_sheet_events import (
    ASIA_OPERATIONAL_COLUMNS,
    ASIA_SHEET_NAME,
    _default_spreadsheet_id,
)
from tools.event.aichi_nagoya_2026_availability_update_audit import (
    parse_content_classifications,
)
from tools.event.aichi_nagoya_2026_availability_updater import (
    DEFAULT_OVERALL_TIMEOUT_SECONDS,
    DEFAULT_SHEETS_REQUEST_TIMEOUT_SECONDS,
    apply_update_plan,
    prepare_google_sheet_access,
)
from tools.event.aichi_nagoya_2026_session_info_audit import (
    CLASSIFICATIONS as SESSION_AUDIT_CLASSIFICATIONS,
    SAFE_TO_UPDATE,
    run_audit as run_session_audit,
)
from tools.event.aichi_nagoya_2026_session_info_display_review import (
    DISPLAY_NEEDS_FIX,
    DISPLAY_OK,
    NEEDS_REVIEW as DISPLAY_REVIEW,
    build_report as build_display_report,
)
from tools.event.aichi_nagoya_2026_verified_session_apply import (
    rebase_content_reference_after_verified_apply,
)


TARGET_FIELD = "session_info"
TARGET_COLUMN = "F"
BAD_CANDIDATE_MARKERS = ("?", "？", "�")
ELIGIBILITY_STATES = (
    "PLANNED",
    "UNCHANGED",
    "HOLD_TIME_MISMATCH",
    "HOLD_DATE_MISMATCH",
    "HOLD_VENUE_MISMATCH",
    "HOLD_MULTIPLE_CANDIDATES",
    "HOLD_RESULTS_NOT_FOUND",
    "HOLD_CONTENT_OUTDATED",
    "HOLD_AGGREGATED_SESSION_INFO",
    "NEEDS_REVIEW",
    "HOLD_DISPLAY_NEEDS_FIX",
    "HOLD_INVALID_CANDIDATE",
    "HOLD_EMPTY_CANDIDATE",
    "HOLD_UNKNOWN_DISPLAY_CLASSIFICATION",
    "HOLD_UNKNOWN_AUDIT_CLASSIFICATION",
)
CSV_FIELDS = (
    "sheet_row_number",
    "cell",
    "date",
    "time",
    "venue",
    "event_name",
    "old_session_info",
    "new_session_info",
    "result_code",
    "audit_classification",
    "display_classification",
    "update_eligibility",
    "information_preservation_reason",
)

SESSION_CONTENT_MARKERS = re.compile(
    r"男子|女子|男女|予選|ラウンド|グループ|プール|総当たり|準々決勝|準決勝|"
    r"3位決定戦|順位決定戦|決勝|メダル"
)
ROUND_PATTERNS = (
    "準々決勝",
    "準決勝",
    "3位決定戦",
    "順位決定戦",
    "決勝",
    "予選",
    "総当たり戦",
)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _normalized_sheet(row: dict[str, Any]) -> dict[str, str]:
    return {column: str(row.get(column) or "").strip() for column in ASIA_OPERATIONAL_COLUMNS}


def _display_by_row(display_report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    for row in display_report.get("rows") or []:
        number = int(row["sheet_row_number"])
        if number in output:
            raise ValueError(f"duplicate display review Sheet row: {number}")
        output[number] = row
    return output


def _normalized_info(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _round_types(value: str) -> set[str]:
    remaining = value
    found: set[str] = set()
    # Longest/specific labels are removed first so their trailing 決勝 is not
    # incorrectly counted as a second round.
    for label in ROUND_PATTERNS:
        if label in remaining:
            found.add(label)
            remaining = remaining.replace(label, "")
    return found


def information_preservation_gate(old: Any, new: Any) -> tuple[str, str]:
    """Protect meaningful aggregate information in an existing Sheet value."""

    current = _normalized_info(old)
    candidate = _normalized_info(new)
    if current == candidate or not current:
        return "SAFE", "existing value is empty or unchanged"

    loss_reasons: list[str] = []
    review_reasons: list[str] = []
    old_counts = [int(value) for value in re.findall(r"(?<!\d)(\d+)\s*試合", current)]
    new_counts = [int(value) for value in re.findall(r"(?<!\d)(\d+)\s*試合", candidate)]
    old_multiple = [value for value in old_counts if value > 1]
    if old_multiple and not any(value >= max(old_multiple) for value in new_counts):
        loss_reasons.append("existing multiple-match count is absent from candidate")

    old_has_both_genders = (
        ("男子" in current and "女子" in current)
        or bool(re.search(r"男女\s*各?\s*\d*\s*試合", current))
    )
    new_has_both_genders = "男子" in candidate and "女子" in candidate
    if old_has_both_genders and not new_has_both_genders:
        loss_reasons.append("existing men's and women's sections are not both preserved")

    old_rounds = _round_types(current)
    new_rounds = _round_types(candidate)
    if len(old_rounds) > 1 and not old_rounds.issubset(new_rounds):
        loss_reasons.append("existing multiple round types are not preserved")
    if "メダル" in current and "メダル" not in candidate:
        loss_reasons.append("existing medal information is absent from candidate")

    separators = re.split(r"\s*(?:／|/|｜|\|)\s*", current)
    if len(separators) > 1:
        meaningful = [part for part in separators if SESSION_CONTENT_MARKERS.search(part)]
        if len(meaningful) >= 2:
            candidate_parts = re.split(r"\s*(?:／|/|｜|\|)\s*", candidate)
            candidate_meaningful = [
                part
                for part in candidate_parts
                if " vs " not in part and SESSION_CONTENT_MARKERS.search(part)
            ]
            if len(candidate_meaningful) < len(meaningful):
                loss_reasons.append("existing independent session sections are not preserved")
        elif len(meaningful) == 1:
            annotations = [
                part.strip()
                for part in separators
                if not SESSION_CONTENT_MARKERS.search(part)
            ]
            if not annotations or not all(
                re.fullmatch(r"(?:第?\d+試合|セッション\d+)", part)
                for part in annotations
            ):
                review_reasons.append("existing separated text has ambiguous session semantics")

    if loss_reasons:
        return "HOLD_AGGREGATED_SESSION_INFO", "; ".join(dict.fromkeys(loss_reasons))
    if review_reasons:
        return "NEEDS_REVIEW", "; ".join(review_reasons)
    return "SAFE", "candidate retains the meaningful information in the existing value"


def build_update_plan(
    session_report: dict[str, Any], display_report: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fail closed and plan only SAFE + DISPLAY_OK, non-empty F cells."""

    displays = _display_by_row(display_report)
    plan: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    seen_cells: set[str] = set()
    for row in session_report.get("rows") or []:
        sheet = _normalized_sheet(row.get("sheet") or {})
        sheet_row = int(row["sheet_row_number"])
        audit_classification = str(row.get("classification") or "UNKNOWN")
        candidate = str(row.get("candidate_session_info") or "").strip()
        current = str(row.get("current_session_info") or "").strip()
        display = displays.get(sheet_row)
        display_classification = (
            str(display.get("display_classification") or "UNKNOWN")
            if display else "NOT_REVIEWED"
        )
        eligibility = audit_classification
        preservation_reason = "not evaluated because upstream audit is not safe"

        if audit_classification not in SESSION_AUDIT_CLASSIFICATIONS:
            eligibility = "HOLD_UNKNOWN_AUDIT_CLASSIFICATION"
        elif audit_classification == SAFE_TO_UPDATE:
            if display_classification == DISPLAY_NEEDS_FIX:
                eligibility = "HOLD_DISPLAY_NEEDS_FIX"
            elif display_classification == DISPLAY_REVIEW:
                eligibility = "NEEDS_REVIEW"
            elif display_classification != DISPLAY_OK:
                eligibility = "HOLD_UNKNOWN_DISPLAY_CLASSIFICATION"
            elif not candidate:
                eligibility = "HOLD_EMPTY_CANDIDATE"
            elif any(marker in candidate for marker in BAD_CANDIDATE_MARKERS):
                eligibility = "HOLD_INVALID_CANDIDATE"
            elif current == candidate:
                eligibility = "UNCHANGED"
                preservation_reason = "existing value and candidate are identical"
            else:
                preservation, preservation_reason = information_preservation_gate(
                    current, candidate
                )
                eligibility = "PLANNED" if preservation == "SAFE" else preservation

        decision = {
            "sheet_row_number": sheet_row,
            "date": sheet["date"],
            "time": sheet["time"],
            "venue": sheet["venue"],
            "event_name": sheet["event_name"],
            "old_session_info": current,
            "new_session_info": candidate,
            "result_code": str(row.get("result_code") or "").strip(),
            "audit_classification": audit_classification,
            "display_classification": display_classification,
            "update_eligibility": eligibility,
            "information_preservation_reason": preservation_reason,
            "is_japan_match": bool(row.get("is_japan_match")),
        }
        decisions.append(decision)
        if eligibility != "PLANNED":
            continue
        cell = f"{TARGET_COLUMN}{sheet_row}"
        if cell in seen_cells:
            raise ValueError(f"duplicate update target: {cell}")
        seen_cells.add(cell)
        plan.append(
            {
                **decision,
                "sheet_data_row": sheet_row - 1,
                "cell": cell,
            }
        )
    return plan, decisions


def _important_counts(plan: list[dict[str, Any]]) -> dict[str, int]:
    labels = [item["new_session_info"] for item in plan]
    return {
        "japan_matches": sum(item["is_japan_match"] for item in plan),
        "quarterfinals": sum("準々決勝" in label for label in labels),
        "semifinals": sum("準決勝" in label and "準々決勝" not in label for label in labels),
        "bronze_matches": sum("3位決定戦" in label for label in labels),
        "finals": sum(
            "決勝" in label
            and "準々決勝" not in label
            and "準決勝" not in label
            and "3位決定戦" not in label
            for label in labels
        ),
    }


def run_refresh(
    *,
    content_audit_path: Path,
    content_reference_results_path: Path,
    overall_timeout: float,
    progress: Callable[[str], None] = _progress,
    audit_runner: Callable[..., dict[str, Any]] = run_session_audit,
    accepted_apply_report: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Re-fetch Sheet and /ja/ Results, then construct a fresh F-only plan."""

    started = time.monotonic()
    progress(
        "session_info_update stage=start mode=read_only "
        f"overall_timeout_s={overall_timeout:g} sheet_write=false"
    )
    content = parse_content_classifications(content_audit_path.read_text(encoding="utf-8"))
    reference = json.loads(content_reference_results_path.read_text(encoding="utf-8"))
    if accepted_apply_report is not None:
        reference = rebase_content_reference_after_verified_apply(
            reference, accepted_apply_report
        )
        progress("session_info_update stage=verified_apply_reference_accepted")
    session_report = audit_runner(
        content_classifications=content,
        content_reference=reference,
        overall_timeout=overall_timeout,
        progress=progress,
    )
    if session_report.get("sheet_write") is not False:
        raise RuntimeError("session audit did not certify read-only execution")
    initial_rows = [_normalized_sheet(row["sheet"]) for row in session_report["rows"]]
    if len(initial_rows) != 245:
        raise ValueError(f"expected 245 Sheet rows, got {len(initial_rows)}")
    display_report = build_display_report(session_report)
    plan, decisions = build_update_plan(session_report, display_report)
    eligibility = Counter(row["update_eligibility"] for row in decisions)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "dry-run",
        "sheet_write": False,
        "sheet_name": ASIA_SHEET_NAME,
        "sheet_range_read": "A:G",
        "sheet_schema": list(ASIA_OPERATIONAL_COLUMNS),
        "sheet_row_count": len(initial_rows),
        "target_column": TARGET_COLUMN,
        "target_field": TARGET_FIELD,
        "session_audit_summary": session_report["summary"],
        "display_review_summary": display_report["summary"],
        "eligibility_summary": {
            state: eligibility.get(state, 0) for state in ELIGIBILITY_STATES
        },
        "planned_update_count": len(plan),
        "important_rounds": _important_counts(plan),
        "planned_updates": plan,
        "decisions": decisions,
    }
    progress(
        "session_info_update stage=plan_complete "
        f"elapsed_s={time.monotonic() - started:.3f} cells={len(plan)} sheet_write=false"
    )
    return report, initial_rows


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    audit = report["session_audit_summary"]["classifications"]
    display = report["display_review_summary"]["classifications"]
    lines = [
        "# アジア大会 session_info F列更新計画",
        "",
        f"- 生成日時: `{report['generated_at']}`",
        f"- モード: `{report['mode']}`",
        f"- Google Sheet書き込み: `{str(report['sheet_write']).lower()}`",
        f"- Sheet行数: {report['sheet_row_count']} / schema: {len(report['sheet_schema'])}列",
        f"- SAFE_TO_UPDATE: {audit.get(SAFE_TO_UPDATE, 0)}",
        f"- DISPLAY_OK: {display.get(DISPLAY_OK, 0)}",
        f"- 更新予定Fセル: {report['planned_update_count']}",
        "",
        "## 判定集計",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in report["eligibility_summary"].items())
    lines.extend(["", "## 重要候補", ""])
    lines.extend(f"- {key}: {value}" for key, value in report["important_rounds"].items())
    lines.extend(
        [
            "",
            "## 更新予定Fセル一覧",
            "",
            "| Sheet行 | セル | date | time | venue | event_name | old_session_info | new_session_info | ResCode | audit | display | eligibility | 情報保持判定 |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in report["planned_updates"]:
        lines.append(
            f"| {item['sheet_row_number']} | {item['cell']} | {_md(item['date'])} | "
            f"{_md(item['time'])} | {_md(item['venue'])} | {_md(item['event_name'])} | "
            f"{_md(item['old_session_info'])} | {_md(item['new_session_info'])} | "
            f"{_md(item['result_code'])} | {item['audit_classification']} | "
            f"{item['display_classification']} | {item['update_eligibility']} | "
            f"{_md(item['information_preservation_reason'])} |"
        )
    lines.extend(["", "A:E、G、非対象F、行、列順、7列schemaは変更していない。", ""])
    return "\n".join(lines)


def write_plan_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for item in report["planned_updates"]:
            writer.writerow({field: item[field] for field in CSV_FIELDS})


def _latest_log(pattern: str) -> Path:
    matches = sorted(Path("logs").glob(pattern))
    if not matches:
        raise FileNotFoundError(f"required audit artifact not found: logs/{pattern}")
    return matches[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read only (default)")
    mode.add_argument("--apply", action="store_true", help="write verified F cells")
    parser.add_argument("--content-audit", type=Path)
    parser.add_argument("--content-reference-results", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--progress-log", type=Path)
    parser.add_argument(
        "--accepted-apply-report",
        type=Path,
        help="verified prior apply JSON allowed only for post-apply read-only re-audit",
    )
    parser.add_argument("--overall-timeout", type=float, default=DEFAULT_OVERALL_TIMEOUT_SECONDS)
    parser.add_argument("--sheets-request-timeout", type=float, default=DEFAULT_SHEETS_REQUEST_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    if args.overall_timeout <= 0 or args.sheets_request_timeout <= 0:
        parser.error("timeouts must be greater than zero")
    today = datetime.now().astimezone().date().isoformat()
    prefix = args.output_prefix or Path("logs") / f"aichi_nagoya_2026_session_info_update_plan_{today}"
    content_path = args.content_audit or _latest_log("aichi_nagoya_2026_content_audit_*.md")
    reference_path = args.content_reference_results or _latest_log("aichi_nagoya_2026_results_audit_*.json")
    progress_path = args.progress_log or prefix.with_suffix(".progress.log")
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text("", encoding="utf-8")

    def progress(message: str) -> None:
        _progress(message)
        with progress_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    try:
        report, initial_rows = run_refresh(
            content_audit_path=content_path,
            content_reference_results_path=reference_path,
            overall_timeout=args.overall_timeout,
            progress=progress,
            accepted_apply_report=(
                json.loads(args.accepted_apply_report.read_text(encoding="utf-8"))
                if args.accepted_apply_report else None
            ),
        )
        if args.apply:
            spreadsheet_id = _default_spreadsheet_id()
            if not spreadsheet_id:
                raise RuntimeError("Google spreadsheet ID is not configured")
            read_sheet, batch_write = prepare_google_sheet_access(
                spreadsheet_id=spreadsheet_id,
                expected_data_rows=len(initial_rows),
                request_timeout=args.sheets_request_timeout,
                progress=progress,
                column_letter=TARGET_COLUMN,
                new_value_key="new_session_info",
                validate_availability_values=False,
            )
            counts = apply_update_plan(
                initial_rows=initial_rows,
                plan=report["planned_updates"],
                read_sheet=read_sheet,
                batch_write=batch_write,
                progress=progress,
                target_field=TARGET_FIELD,
                new_value_key="new_session_info",
                operation_name="session_info_apply",
            )
            report["mode"] = "apply"
            report["sheet_write"] = True
            report["apply_result"] = counts
    except Exception as exc:
        progress(
            "session_info_update stage=failed "
            f"error_type={type(exc).__name__} error={exc} sheet_write={str(args.apply).lower()}"
        )
        raise

    prefix.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(report)
    prefix.with_suffix(".md").write_text(markdown, encoding="utf-8")
    write_plan_csv(prefix.with_suffix(".csv"), report)
    prefix.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
