#!/usr/bin/env python3
"""Cross-audit ticket availability changes against Results and content audits.

This command only reads existing audit artifacts.  It has no Google Sheets read or
write path and never selects an ambiguous Results candidate.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SAFE_TO_UPDATE = "SAFE_TO_UPDATE"
HOLD_RESULTS_MISMATCH = "HOLD_RESULTS_MISMATCH"
HOLD_CONTENT_OUTDATED = "HOLD_CONTENT_OUTDATED"
HOLD_TICKET_NOT_FOUND = "HOLD_TICKET_NOT_FOUND"
NEEDS_REVIEW = "NEEDS_REVIEW"
CLASSIFICATIONS = (
    SAFE_TO_UPDATE,
    HOLD_RESULTS_MISMATCH,
    HOLD_CONTENT_OUTDATED,
    HOLD_TICKET_NOT_FOUND,
    NEEDS_REVIEW,
)
RESULTS_MISMATCHES = {
    "TIME_MISMATCH",
    "VENUE_MISMATCH",
    "DATE_MISMATCH",
    "RESULTS_NOT_FOUND",
}
SAFE_CONTENT_STATES = {"CONTENT_MATCH", "AGGREGATED_OK"}
CEREMONIES = {"開会式", "閉会式"}
CORE_TICKET_FIELDS = ("date", "time", "venue", "event_name")
TRANSITIONS = (
    ("BUY", "LIMITED"),
    ("BUY", "SOLD_OUT"),
    ("LIMITED", "BUY"),
    ("LIMITED", "SOLD_OUT"),
    ("SOLD_OUT", "BUY"),
    ("SOLD_OUT", "LIMITED"),
)
CSV_FIELDS = [
    "sheet_data_row",
    "classification",
    "date",
    "time",
    "venue",
    "event_name",
    "old_availability_status",
    "new_availability_status",
    "ticket_match_reason",
    "results_audit_state",
    "results_audit_reason",
    "content_audit_state",
    "hold_reason_code",
    "decision_reason",
    "idPerformance",
    "idProduct",
    "sessionCode",
]


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = text.translate(str.maketrans({"[": "(", "]": ")", "［": "(", "］": ")"}))
    return re.sub(r"\s+", "", text)


def parse_content_classifications(markdown: str) -> dict[int, str]:
    """Read the machine-checkable row index from the content audit Markdown."""

    mapping: dict[int, str] = {}
    pattern = re.compile(r"^- `([A-Z_]+)` \(\d+\): ([0-9, ]+)$", re.MULTILINE)
    for classification, row_numbers in pattern.findall(markdown):
        for value in row_numbers.split(","):
            row_number = int(value.strip())
            if row_number in mapping:
                raise ValueError(f"duplicate content classification for Sheet row {row_number}")
            mapping[row_number] = classification
    if not mapping:
        raise ValueError("content audit has no classification index")
    return mapping


def _identity(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(_normalized(row.get(field)) for field in CORE_TICKET_FIELDS)


def _changed_fields(left: dict[str, Any], right: dict[str, Any], fields: Iterable[str]) -> list[str]:
    return [field for field in fields if _normalized(left.get(field)) != _normalized(right.get(field))]


def _base_output(ticket_row: dict[str, Any], results_row: dict[str, Any]) -> dict[str, Any]:
    sheet = ticket_row["sheet"]
    stable = ticket_row.get("stable_ids") or {}
    return {
        "sheet_data_row": ticket_row["sheet_data_row"],
        "sheet": sheet,
        "old_availability_status": sheet["availability_status"],
        "new_availability_status": ticket_row.get("official_availability_status", ""),
        "ticket_audit_state": ticket_row["classification"],
        "ticket_match_reason": ticket_row["reason"],
        "stable_ids": stable,
        "official_ticket": ticket_row.get("official_ticket") or {},
        "results_audit_state": results_row["classification"],
        "results_audit_reason": results_row["reason"],
        "results_candidate_count": results_row["candidate_count"],
        "content_audit_state": "NOT_APPLICABLE",
        "classification": NEEDS_REVIEW,
        "hold_reason_code": "",
        "decision_reason": "",
        "would_write": False,
    }


def cross_audit(
    ticket_report: dict[str, Any],
    results_report: dict[str, Any],
    content_classifications: dict[int, str],
) -> dict[str, Any]:
    """Classify changed and unresolved ticket rows without mutating source data."""

    results_by_row = {
        row_number: row
        for row_number, row in enumerate(results_report.get("rows", []), start=1)
    }
    if not results_by_row:
        raise ValueError("Results audit contains zero rows")

    decisions: list[dict[str, Any]] = []
    unchanged_count = 0
    for ticket_row in ticket_report.get("rows", []):
        state = ticket_row.get("classification")
        if state == "UNCHANGED":
            unchanged_count += 1
            continue
        if state not in {"STATUS_CHANGED", "NOT_FOUND", "MULTIPLE_CANDIDATES"}:
            raise ValueError(f"unsupported ticket audit classification: {state!r}")
        row_number = int(ticket_row["sheet_data_row"])
        results_row = results_by_row.get(row_number)
        if results_row is None:
            raise ValueError(f"Results audit is missing Sheet row {row_number}")
        if _identity(ticket_row["sheet"]) != _identity(results_row["sheet"]):
            raise ValueError(f"ticket/Results artifact identity differs at Sheet row {row_number}")
        output = _base_output(ticket_row, results_row)
        event_name = ticket_row["sheet"]["event_name"].strip()
        if event_name not in CEREMONIES:
            if row_number not in content_classifications:
                raise ValueError(f"content audit is missing Sheet row {row_number}")
            output["content_audit_state"] = content_classifications[row_number]

        if state == "NOT_FOUND":
            output["classification"] = HOLD_TICKET_NOT_FOUND
            output["hold_reason_code"] = "TICKET_NOT_FOUND"
            output["decision_reason"] = (
                "current official ticket product was not resolved; preserve the old Sheet value"
            )
            decisions.append(output)
            continue
        if state == "MULTIPLE_CANDIDATES":
            output["classification"] = NEEDS_REVIEW
            output["hold_reason_code"] = "TICKET_MULTIPLE_CANDIDATES"
            output["decision_reason"] = (
                "ticket audit has multiple candidates; no product was selected"
            )
            decisions.append(output)
            continue

        baseline_ticket = ticket_row.get("baseline_ticket") or {}
        official_ticket = ticket_row.get("official_ticket") or {}
        if not baseline_ticket or not official_ticket:
            output["classification"] = NEEDS_REVIEW
            output["hold_reason_code"] = "TICKET_METADATA_MISSING"
            output["decision_reason"] = "ticket product metadata is missing from the input artifact"
            decisions.append(output)
            continue
        core_differences = _changed_fields(
            baseline_ticket, official_ticket, CORE_TICKET_FIELDS
        )
        if core_differences:
            output["classification"] = HOLD_RESULTS_MISMATCH
            output["hold_reason_code"] = "TICKET_CORE_CHANGED"
            output["decision_reason"] = (
                "current ticket product changed core field(s): "
                + ",".join(core_differences)
            )
            decisions.append(output)
            continue

        results_state = results_row["classification"]
        if event_name in CEREMONIES and results_state == "RESULTS_NOT_FOUND":
            output["classification"] = SAFE_TO_UPDATE
            output["decision_reason"] = (
                "opening/closing ceremony is outside Results; unique stable ticket IDs and "
                "unchanged ticket date/time/venue/event establish the mapping"
            )
        elif results_state == "MULTIPLE_CANDIDATES":
            output["classification"] = NEEDS_REVIEW
            output["hold_reason_code"] = "RESULTS_MULTIPLE_CANDIDATES"
            output["decision_reason"] = (
                "Results audit has multiple exact candidates; none was selected"
            )
        elif results_state in RESULTS_MISMATCHES:
            output["classification"] = HOLD_RESULTS_MISMATCH
            output["hold_reason_code"] = results_state
            output["decision_reason"] = (
                f"Results audit state {results_state} does not safely corroborate the Sheet row"
            )
        elif results_state != "EXACT_MATCH":
            output["classification"] = NEEDS_REVIEW
            output["hold_reason_code"] = "RESULTS_UNKNOWN_STATE"
            output["decision_reason"] = f"unsupported Results audit state: {results_state}"
        elif output["content_audit_state"] == "CONTENT_OUTDATED":
            output["classification"] = HOLD_CONTENT_OUTDATED
            output["hold_reason_code"] = "CONTENT_OUTDATED"
            output["decision_reason"] = (
                "content audit found an explicit contradiction; availability remains unchanged"
            )
        elif output["content_audit_state"] == "INSUFFICIENT_SHEET_INFO":
            output["classification"] = NEEDS_REVIEW
            output["hold_reason_code"] = "INSUFFICIENT_SHEET_INFO"
            output["decision_reason"] = (
                "Sheet content is insufficient to corroborate the ticket session safely"
            )
        elif output["content_audit_state"] == "NEEDS_REVIEW":
            output["classification"] = NEEDS_REVIEW
            output["hold_reason_code"] = "CONTENT_NEEDS_REVIEW"
            output["decision_reason"] = "content audit has an unresolved review state"
        elif output["content_audit_state"] not in SAFE_CONTENT_STATES:
            output["classification"] = NEEDS_REVIEW
            output["hold_reason_code"] = "CONTENT_UNKNOWN_STATE"
            output["decision_reason"] = (
                "content audit state is not explicitly allowed for automatic update: "
                f"{output['content_audit_state']}"
            )
        else:
            output["classification"] = SAFE_TO_UPDATE
            output["decision_reason"] = (
                "exact Results schedule key, safe content audit, unique stable ticket IDs, "
                "and unchanged ticket core fields corroborate the availability mapping"
            )
        output["would_write"] = output["classification"] == SAFE_TO_UPDATE
        decisions.append(output)

    status_changed_count = sum(
        row["ticket_audit_state"] == "STATUS_CHANGED" for row in decisions
    )
    ticket_not_found_count = sum(
        row["ticket_audit_state"] == "NOT_FOUND" for row in decisions
    )
    classifications = Counter(row["classification"] for row in decisions)
    hold_reasons = Counter(
        row["hold_reason_code"] for row in decisions if row["hold_reason_code"]
    )
    safe_transitions = Counter(
        (row["old_availability_status"], row["new_availability_status"])
        for row in decisions
        if row["classification"] == SAFE_TO_UPDATE
    )
    return {
        "dry_run": True,
        "sheet_write": False,
        "scope": "STATUS_CHANGED rows plus protected ticket NOT_FOUND rows",
        "ticket_input_snapshot_note": ticket_report.get("snapshot_note", ""),
        "ticket_input_revalidation_note": ticket_report.get("revalidation_note", ""),
        "summary": {
            "ticket_unchanged_outside_update_scope": unchanged_count,
            "ticket_status_changed_input": status_changed_count,
            "ticket_not_found_protected": ticket_not_found_count,
            "classifications": {
                name: classifications.get(name, 0) for name in CLASSIFICATIONS
            },
            "hold_reasons": dict(sorted(hold_reasons.items())),
            "safe_transitions": {
                f"{old} -> {new}": safe_transitions.get((old, new), 0)
                for old, new in TRANSITIONS
            },
            "would_change_cells": classifications.get(SAFE_TO_UPDATE, 0),
        },
        "rows": decisions,
    }


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# アジア大会 availability_status 更新可否 dry-run突合監査",
        "",
        "- Google Sheet書き込み: `false`",
        "- 対象列: `availability_status`（今回は変更なし）",
        f"- STATUS_CHANGED入力: {summary['ticket_status_changed_input']}",
        f"- Ticket NOT_FOUND保護: {summary['ticket_not_found_protected']}",
        f"- UNCHANGED（更新対象外）: {summary['ticket_unchanged_outside_update_scope']}",
        f"- 実書き込み時の変更セル数: {summary['would_change_cells']}",
    ]
    if report.get("ticket_input_snapshot_note"):
        lines.append(f"- 入力snapshot: {_md(report['ticket_input_snapshot_note'])}")
    if report.get("ticket_input_revalidation_note"):
        lines.append(f"- 再検証: {_md(report['ticket_input_revalidation_note'])}")
    lines.extend(
        [
            "",
            "## 判定件数",
            "",
            "| 分類 | 件数 |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| {name} | {summary['classifications'][name]} |" for name in CLASSIFICATIONS
    )
    lines.extend(["", "## 保留理由", ""])
    if summary["hold_reasons"]:
        lines.extend(
            f"- {reason}: {count}" for reason, count in summary["hold_reasons"].items()
        )
    else:
        lines.append("- なし")
    lines.extend(["", "## SAFE_TO_UPDATE の販売状態変化", ""])
    lines.extend(
        f"- {transition}: {count}"
        for transition, count in summary["safe_transitions"].items()
    )
    safe = [row for row in report["rows"] if row["classification"] == SAFE_TO_UPDATE]
    lines.extend(
        [
            "",
            f"## SAFE_TO_UPDATE ({len(safe)}件)",
            "",
            "| Sheet行 | date | time | venue | event_name | 旧status | 新status | Ticket側照合根拠 | Results側監査状態 | 判定理由 |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in safe:
        sheet = row["sheet"]
        lines.append(
            f"| {row['sheet_data_row']} | {_md(sheet['date'])} | {_md(sheet['time'])} | "
            f"{_md(sheet['venue'])} | {_md(sheet['event_name'])} | "
            f"{_md(row['old_availability_status'])} | {_md(row['new_availability_status'])} | "
            f"{_md(row['ticket_match_reason'])} | {_md(row['results_audit_state'])} | "
            f"{_md(row['decision_reason'])} |"
        )
    for classification in CLASSIFICATIONS[1:]:
        selected = [
            row for row in report["rows"] if row["classification"] == classification
        ]
        lines.extend(
            [
                "",
                f"## {classification} ({len(selected)}件)",
                "",
                "| Sheet行 | date/time | venue | event_name | 旧status | 新status | Results | Content | 理由 |",
                "| ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in selected:
            sheet = row["sheet"]
            lines.append(
                f"| {row['sheet_data_row']} | {_md(sheet['date'])} {_md(sheet['time'])} | "
                f"{_md(sheet['venue'])} | {_md(sheet['event_name'])} | "
                f"{_md(row['old_availability_status'])} | {_md(row['new_availability_status']) or '-'} | "
                f"{_md(row['results_audit_state'])} | {_md(row['content_audit_state'])} | "
                f"{_md(row['decision_reason'])} |"
            )
    lines.extend(
        [
            "",
            "Ticket NOT_FOUNDは旧値を保持する。候補複数は自動選択していない。",
            "Sheet、session_info、availability_status、その他6列、列順、BOT状態は変更していない。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in report["rows"]:
            sheet = row["sheet"]
            stable = row["stable_ids"]
            writer.writerow(
                {
                    "sheet_data_row": row["sheet_data_row"],
                    "classification": row["classification"],
                    "date": sheet["date"],
                    "time": sheet["time"],
                    "venue": sheet["venue"],
                    "event_name": sheet["event_name"],
                    "old_availability_status": row["old_availability_status"],
                    "new_availability_status": row["new_availability_status"],
                    "ticket_match_reason": row["ticket_match_reason"],
                    "results_audit_state": row["results_audit_state"],
                    "results_audit_reason": row["results_audit_reason"],
                    "content_audit_state": row["content_audit_state"],
                    "hold_reason_code": row["hold_reason_code"],
                    "decision_reason": row["decision_reason"],
                    "idPerformance": stable.get("idPerformance", ""),
                    "idProduct": stable.get("idProduct", ""),
                    "sessionCode": stable.get("sessionCode", ""),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket-audit", type=Path, required=True)
    parser.add_argument("--results-audit", type=Path, required=True)
    parser.add_argument("--content-audit", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    ticket = json.loads(args.ticket_audit.read_text(encoding="utf-8"))
    results = json.loads(args.results_audit.read_text(encoding="utf-8"))
    content = parse_content_classifications(
        args.content_audit.read_text(encoding="utf-8")
    )
    report = cross_audit(ticket, results, content)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    write_csv(args.csv_output, report)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(render_markdown(report), end="")


if __name__ == "__main__":
    main()
