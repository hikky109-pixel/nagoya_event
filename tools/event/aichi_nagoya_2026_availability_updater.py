#!/usr/bin/env python3
"""Safely plan or apply Asia Games availability_status cell updates.

No arguments and ``--dry-run`` are read-only.  ``--apply`` is the only path that
creates a Google Sheets service or sends a values batchUpdate request.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
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
    _sheets_service,
)
from tools.event.aichi_nagoya_2026_availability_update_audit import (
    CLASSIFICATIONS,
    SAFE_TO_UPDATE,
    TRANSITIONS,
    cross_audit,
    parse_content_classifications,
)
from tools.event.aichi_nagoya_2026_results import external_request_timeout
from tools.event.aichi_nagoya_2026_results_audit import (
    audit_sheet_rows as audit_results_sheet_rows,
    fetch_full_results_period,
    summarize as summarize_results,
)
from tools.event.aichi_nagoya_2026_results_dry_run import (
    ASIA_DRY_RUN_SHEET_URL,
    SHEET_REQUEST_TIMEOUT,
    load_asia_sheet_rows_read_only,
)
from tools.event.aichi_nagoya_2026_ticket_status_audit import (
    DEFAULT_CANDIDATES_PATH,
    _read_candidate_rows,
    audit_sheet_rows as audit_ticket_sheet_rows,
    summarize as summarize_ticket,
)
from tools.event.build_aichi_nagoya_2026_baseline import fetch_session_pages
from tools.event.aichi_nagoya_2026_verified_session_apply import (
    rebase_content_reference_after_verified_apply,
)


DEFAULT_OVERALL_TIMEOUT_SECONDS = 240.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0
DEFAULT_SHEETS_REQUEST_TIMEOUT_SECONDS = 20.0
NON_STATUS_COLUMNS = tuple(ASIA_OPERATIONAL_COLUMNS[:-1])
KNOWN_STATUSES = {"BUY", "LIMITED", "SOLD_OUT"}


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _remaining(deadline: float, stage: str) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError(f"availability updater overall timeout before stage={stage}")
    return value


def _normalized_row(source: dict[str, Any]) -> dict[str, str]:
    return {
        column: str(source.get(column) or "").strip()
        for column in ASIA_OPERATIONAL_COLUMNS
    }


def validate_content_reference(
    current_rows: list[dict[str, str]], reference_results_report: dict[str, Any]
) -> None:
    """Require the prior content classifications to describe this exact six-column layout."""

    reference_rows = reference_results_report.get("rows") or []
    if len(reference_rows) != len(current_rows):
        raise ValueError(
            "content reference row count differs from current Sheet: "
            f"reference={len(reference_rows)} current={len(current_rows)}"
        )
    for row_number, (current, reference) in enumerate(
        zip(current_rows, reference_rows), start=1
    ):
        reference_sheet = _normalized_row(reference.get("sheet") or {})
        differences = [
            field
            for field in NON_STATUS_COLUMNS
            if current[field] != reference_sheet[field]
        ]
        if differences:
            raise ValueError(
                "content reference six-column identity differs at data row "
                f"{row_number}: fields={','.join(differences)}"
            )


def build_update_plan(cross_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only safe, currently different G-column cells."""

    plan: list[dict[str, Any]] = []
    seen_cells: set[str] = set()
    for row in cross_report.get("rows", []):
        if row.get("classification") != SAFE_TO_UPDATE:
            continue
        old = str(row.get("old_availability_status") or "").strip()
        new = str(row.get("new_availability_status") or "").strip()
        if old == new:
            continue
        if old not in KNOWN_STATUSES or new not in KNOWN_STATUSES:
            raise ValueError(
                f"unsupported availability transition at data row {row['sheet_data_row']}: "
                f"{old!r} -> {new!r}"
            )
        sheet_row_number = int(row["sheet_data_row"]) + 1
        cell = f"G{sheet_row_number}"
        if cell in seen_cells:
            raise ValueError(f"duplicate update target: {cell}")
        seen_cells.add(cell)
        plan.append(
            {
                "sheet_data_row": row["sheet_data_row"],
                "sheet_row_number": sheet_row_number,
                "cell": cell,
                "date": row["sheet"]["date"],
                "time": row["sheet"]["time"],
                "venue": row["sheet"]["venue"],
                "event_name": row["sheet"]["event_name"],
                "old_availability_status": old,
                "new_availability_status": new,
                "ticket_match_reason": row["ticket_match_reason"],
                "results_audit_state": row["results_audit_state"],
            }
        )
    return plan


def validate_exact_snapshot(
    expected: list[dict[str, str]], actual: list[dict[str, str]], *, stage: str
) -> None:
    if len(expected) != len(actual):
        raise RuntimeError(
            f"Sheet row count changed at {stage}: expected={len(expected)} actual={len(actual)}"
        )
    for data_row, (left, right) in enumerate(zip(expected, actual), start=1):
        differences = [
            field for field in ASIA_OPERATIONAL_COLUMNS if left[field] != right[field]
        ]
        if differences:
            raise RuntimeError(
                f"Sheet snapshot changed at {stage} data_row={data_row} "
                f"fields={','.join(differences)}"
            )


def evaluate_applied_cells(
    before: list[dict[str, str]],
    after: list[dict[str, str]],
    plan: list[dict[str, Any]],
    *,
    target_field: str = "availability_status",
    new_value_key: str = "new_availability_status",
) -> dict[str, int]:
    """Verify that only planned cells in one explicitly selected column changed."""

    if len(before) != len(after):
        raise RuntimeError(
            f"post-write row count changed: before={len(before)} after={len(after)}"
        )
    planned = {int(item["sheet_data_row"]): item for item in plan}
    counts = Counter(applied=0, not_applied=0, unexpected=0)
    for data_row, (left, right) in enumerate(zip(before, after), start=1):
        other_differences = [
            field
            for field in ASIA_OPERATIONAL_COLUMNS
            if field != target_field and left[field] != right[field]
        ]
        if other_differences:
            protected_label = (
                "non-availability"
                if target_field == "availability_status"
                else "protected"
            )
            raise RuntimeError(
                f"{protected_label} Sheet data changed during apply at data_row="
                f"{data_row} fields={','.join(other_differences)}"
            )
        target = planned.get(data_row)
        if target is None:
            if left[target_field] != right[target_field]:
                counts["unexpected"] += 1
            continue
        if right[target_field] == target[new_value_key]:
            counts["applied"] += 1
        elif right[target_field] == left[target_field]:
            counts["not_applied"] += 1
        else:
            counts["unexpected"] += 1
    return dict(counts)


def apply_update_plan(
    *,
    initial_rows: list[dict[str, str]],
    plan: list[dict[str, Any]],
    read_sheet: Callable[[], list[dict[str, str]]],
    batch_write: Callable[[list[dict[str, Any]]], None],
    progress: Callable[[str], None],
    target_field: str = "availability_status",
    new_value_key: str = "new_availability_status",
    operation_name: str = "availability_apply",
) -> dict[str, int]:
    """Preflight, write one column-only batch, then verify every Sheet cell."""

    progress(f"{operation_name} stage=prewrite_sheet_read_start")
    before = read_sheet()
    validate_exact_snapshot(initial_rows, before, stage="prewrite")
    progress(
        f"{operation_name} stage=prewrite_verified rows={len(before)} cells={len(plan)}"
    )
    if not plan:
        return {"applied": 0, "not_applied": 0, "unexpected": 0}
    try:
        progress(f"{operation_name} stage=batch_write_start cells={len(plan)}")
        batch_write(plan)
    except Exception as exc:
        progress(
            f"{operation_name} stage=batch_write_error "
            f"error_type={type(exc).__name__} error={exc}"
        )
        try:
            after_error = read_sheet()
            counts = evaluate_applied_cells(
                before, after_error, plan,
                target_field=target_field, new_value_key=new_value_key,
            )
            progress(
                f"{operation_name} stage=partial_failure_verified "
                f"applied={counts['applied']} not_applied={counts['not_applied']} "
                f"unexpected={counts['unexpected']}"
            )
        except Exception as verify_exc:
            progress(
                f"{operation_name} stage=partial_failure_indeterminate "
                f"error_type={type(verify_exc).__name__} error={verify_exc}"
            )
        raise
    progress(f"{operation_name} stage=postwrite_sheet_read_start")
    after = read_sheet()
    counts = evaluate_applied_cells(
        before, after, plan,
        target_field=target_field, new_value_key=new_value_key,
    )
    progress(
        f"{operation_name} stage=postwrite_verified "
        f"applied={counts['applied']} not_applied={counts['not_applied']} "
        f"unexpected={counts['unexpected']}"
    )
    if counts != {"applied": len(plan), "not_applied": 0, "unexpected": 0}:
        raise RuntimeError(f"post-write verification failed: {counts}")
    return counts


def _parse_values_rows(values: list[list[Any]]) -> list[dict[str, str]]:
    if not values:
        raise ValueError("authenticated Sheet read returned zero rows")
    header = [str(value).strip() for value in values[0]]
    if header != ASIA_OPERATIONAL_COLUMNS:
        raise ValueError(
            f"authenticated Sheet header differs: expected={ASIA_OPERATIONAL_COLUMNS} actual={header}"
        )
    rows: list[dict[str, str]] = []
    for sheet_row_number, source in enumerate(values[1:], start=2):
        values_row = [str(value).strip() for value in source]
        if len(values_row) > len(ASIA_OPERATIONAL_COLUMNS):
            raise ValueError(f"Sheet row {sheet_row_number} exceeds seven columns")
        values_row.extend([""] * (len(ASIA_OPERATIONAL_COLUMNS) - len(values_row)))
        if not any(values_row):
            raise ValueError(f"blank row inside authenticated Sheet range: {sheet_row_number}")
        row = dict(zip(ASIA_OPERATIONAL_COLUMNS, values_row))
        if not row["date"] or not row["event_name"]:
            raise ValueError(f"invalid operational row at Sheet row {sheet_row_number}")
        rows.append(row)
    if not rows:
        raise ValueError("authenticated Sheet contains zero data rows")
    return rows


def _execute_google(request: Any, timeout: float, stage: str) -> Any:
    with external_request_timeout(timeout, stage):
        return request.execute(num_retries=0)


def extract_validation_rules(response: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Map physical Sheet row numbers to G-cell data-validation rules."""

    rules: dict[int, dict[str, Any]] = {}
    for sheet in response.get("sheets", []):
        for grid in sheet.get("data", []):
            start_row = int(grid.get("startRow") or 0)
            for offset, row_data in enumerate(grid.get("rowData", [])):
                values = row_data.get("values") or []
                if values and values[0].get("dataValidation"):
                    rules[start_row + offset + 1] = values[0]["dataValidation"]
    return rules


def validate_planned_statuses_against_rules(
    plan: list[dict[str, Any]], rules: dict[int, dict[str, Any]]
) -> None:
    for item in plan:
        rule = rules.get(int(item["sheet_row_number"]))
        if not rule:
            continue
        condition = rule.get("condition") or {}
        condition_type = condition.get("type")
        if condition_type != "ONE_OF_LIST":
            raise RuntimeError(
                f"unsupported G-cell validation at {item['cell']}: {condition_type!r}"
            )
        allowed = {
            str(value.get("userEnteredValue") or "").strip()
            for value in condition.get("values", [])
        }
        if item["new_availability_status"] not in allowed:
            raise RuntimeError(
                f"planned value violates validation at {item['cell']}: "
                f"value={item['new_availability_status']!r} allowed={sorted(allowed)}"
            )


def prepare_google_sheet_access(
    *,
    spreadsheet_id: str,
    expected_data_rows: int,
    request_timeout: float,
    progress: Callable[[str], None] = _progress,
    column_letter: str = "G",
    new_value_key: str = "new_availability_status",
    validate_availability_values: bool = True,
) -> tuple[Callable[[], list[dict[str, str]]], Callable[[list[dict[str, Any]]], None]]:
    """Resolve the exact tab and return bounded reads and one-column writes."""

    if column_letter not in {"F", "G"}:
        raise ValueError(f"unsupported writable column: {column_letter!r}")

    service = _sheets_service()
    progress(
        "google_sheets_api stage=metadata_start "
        f"sheet={ASIA_SHEET_NAME} timeout_s={request_timeout:g}"
    )
    metadata = _execute_google(
        service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties(sheetId,title,gridProperties(rowCount,columnCount))",
        ),
        request_timeout,
        "Google Sheets metadata",
    )
    progress("google_sheets_api stage=metadata_done")
    matches = [
        sheet
        for sheet in metadata.get("sheets", [])
        if sheet.get("properties", {}).get("title") == ASIA_SHEET_NAME
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one {ASIA_SHEET_NAME!r} tab; found={len(matches)}"
        )
    properties = matches[0]["properties"]
    if int(properties.get("gridProperties", {}).get("columnCount") or 0) < 7:
        raise RuntimeError("Asia Games tab has fewer than seven columns")
    last_row = expected_data_rows + 1
    read_range = f"'{ASIA_SHEET_NAME}'!A1:G{last_row}"
    validation_rules: dict[int, dict[str, Any]] = {}
    if validate_availability_values:
        if column_letter != "G":
            raise ValueError("availability validation is supported only for G")
        progress(
            "google_sheets_api stage=validation_read_start "
            f"range=G2:G{last_row} timeout_s={request_timeout:g}"
        )
        validation_response = _execute_google(
            service.spreadsheets().get(
                spreadsheetId=spreadsheet_id,
                ranges=[f"'{ASIA_SHEET_NAME}'!G2:G{last_row}"],
                includeGridData=True,
                fields="sheets(data(startRow,rowData(values(dataValidation,formattedValue))))",
            ),
            request_timeout,
            "Google Sheets G validation read",
        )
        validation_rules = extract_validation_rules(validation_response)
        progress(
            "google_sheets_api stage=validation_read_done "
            f"rules={len(validation_rules)}"
        )

    def read_sheet() -> list[dict[str, str]]:
        progress(
            "google_sheets_api stage=values_read_start "
            f"range=A1:G{last_row} timeout_s={request_timeout:g}"
        )
        response = _execute_google(
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=read_range,
                majorDimension="ROWS",
                valueRenderOption="FORMATTED_VALUE",
            ),
            request_timeout,
            "Google Sheets authenticated A:G read",
        )
        rows = _parse_values_rows(response.get("values", []))
        progress(f"google_sheets_api stage=values_read_done rows={len(rows)}")
        return rows

    def batch_write(plan: list[dict[str, Any]]) -> None:
        if validate_availability_values:
            validate_planned_statuses_against_rules(plan, validation_rules)
        data = [
            {
                "range": f"'{ASIA_SHEET_NAME}'!{item['cell']}",
                "majorDimension": "ROWS",
                "values": [[item[new_value_key]]],
            }
            for item in plan
        ]
        if any(
            not item["range"].split("!")[-1].startswith(column_letter)
            for item in data
        ):
            raise AssertionError(f"non-{column_letter} update target generated")
        progress(
            "google_sheets_api stage=values_batch_update_start "
            f"cells={len(data)} timeout_s={request_timeout:g}"
        )
        _execute_google(
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            ),
            request_timeout,
            f"Google Sheets {column_letter}-only batchUpdate",
        )
        progress(
            f"google_sheets_api stage=values_batch_update_done cells={len(data)}"
        )

    return read_sheet, batch_write


def run_refresh(
    *,
    candidates_path: Path,
    content_audit_path: Path,
    content_reference_results_path: Path,
    overall_timeout: float,
    request_timeout: float,
    progress: Callable[[str], None] = _progress,
    ticket_fetcher: Callable[[], tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
    sheet_loader: Callable[[], list[dict[str, str]]] | None = None,
    results_fetcher: Callable[[list[dict[str, str]], float], tuple[list[str], list[dict[str, Any]]]] | None = None,
    accepted_session_info_apply_report: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Re-fetch all live inputs and produce a fresh update plan."""

    started = time.monotonic()
    deadline = started + float(overall_timeout)
    progress(
        "availability_update stage=start "
        f"mode=read_only overall_timeout_s={overall_timeout:g} sheet_write=false"
    )
    with external_request_timeout(overall_timeout, "availability update refresh"):
        candidate_rows = _read_candidate_rows(candidates_path)

        progress("availability_update stage=ticket_fetch_start")
        if ticket_fetcher is None:
            pages, products = fetch_session_pages(
                request_timeout=request_timeout,
                overall_timeout=_remaining(deadline, "ticket_fetch"),
                progress=progress,
            )
        else:
            pages, products = ticket_fetcher()
        if not pages or len(products) <= 1:
            raise ValueError("unsafe official ticket response; refusing update plan")
        progress(
            "availability_update stage=ticket_fetch_done "
            f"pages={len(pages)} products={len(products)}"
        )

        progress(
            "availability_update stage=sheet_fetch_start "
            f"range=A:G endpoint={ASIA_DRY_RUN_SHEET_URL}"
        )
        current_rows = (
            load_asia_sheet_rows_read_only(progress=progress)
            if sheet_loader is None
            else sheet_loader()
        )
        if not current_rows:
            raise ValueError("Asia Games Sheet contains zero rows")
        current_rows = [_normalized_row(row) for row in current_rows]
        progress(f"availability_update stage=sheet_fetch_done rows={len(current_rows)}")

        reference_results = json.loads(
            content_reference_results_path.read_text(encoding="utf-8")
        )
        if accepted_session_info_apply_report is not None:
            reference_results = rebase_content_reference_after_verified_apply(
                reference_results, accepted_session_info_apply_report
            )
            progress("availability_update stage=verified_session_info_apply_reference_accepted")
        validate_content_reference(current_rows, reference_results)
        content = parse_content_classifications(
            content_audit_path.read_text(encoding="utf-8")
        )
        progress("availability_update stage=content_reference_verified")

        ticket_rows, excluded = audit_ticket_sheet_rows(
            current_rows, candidate_rows, products
        )
        ticket_report = {
            "summary": summarize_ticket(ticket_rows),
            "rows": ticket_rows,
            "excluded_test_rows": excluded,
        }
        progress(
            "availability_update stage=ticket_classify_done "
            + " ".join(
                f"{key}={value}"
                for key, value in ticket_report["summary"]["classifications"].items()
            )
        )

        progress("availability_update stage=results_fetch_start language=ja")
        if results_fetcher is None:
            official_dates, results = fetch_full_results_period(
                current_rows, deadline=deadline, progress=progress
            )
        else:
            official_dates, results = results_fetcher(
                current_rows, _remaining(deadline, "results_fetch")
            )
        results_rows = audit_results_sheet_rows(current_rows, results)
        results_report = {
            "results_language": "ja",
            "official_date_count": len(official_dates),
            "results_record_count": len(results),
            "summary": summarize_results(results_rows),
            "rows": results_rows,
        }
        progress(
            "availability_update stage=results_classify_done "
            + " ".join(
                f"{key}={value}" for key, value in results_report["summary"].items()
            )
        )

        cross_report = cross_audit(ticket_report, results_report, content)
        plan = build_update_plan(cross_report)
        transitions = Counter(
            f"{item['old_availability_status']} -> {item['new_availability_status']}"
            for item in plan
        )
        report = {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "mode": "dry-run",
            "sheet_write": False,
            "sheet_name": ASIA_SHEET_NAME,
            "sheet_range_read": "A:G",
            "sheet_schema": list(ASIA_OPERATIONAL_COLUMNS),
            "sheet_row_count": len(current_rows),
            "official_ticket_product_count": len(products),
            "official_results_record_count": len(results),
            "ticket_summary": ticket_report["summary"],
            "results_summary": results_report["summary"],
            "safety_summary": cross_report["summary"],
            "planned_update_count": len(plan),
            "planned_transitions": {
                f"{old} -> {new}": transitions.get(f"{old} -> {new}", 0)
                for old, new in TRANSITIONS
            },
            "planned_updates": plan,
            "safety_rows": cross_report["rows"],
        }
    progress(
        "availability_update stage=plan_complete "
        f"elapsed_s={time.monotonic() - started:.3f} cells={len(plan)} sheet_write=false"
    )
    return report, current_rows


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    safety = report.get("safety_summary", {})
    mode = report.get("mode")
    lines = [
        f"# アジア大会 availability_status 更新予定セル {mode}",
        "",
        f"- 生成日時: `{report['generated_at']}`",
        f"- モード: `{report['mode']}`",
        f"- Google Sheet書き込み: `{str(report['sheet_write']).lower()}`",
        f"- Sheet: `{report['sheet_name']}` / 読取範囲 `{report['sheet_range_read']}`",
        f"- 更新予定セル数: {report['planned_update_count']}",
    ]
    if safety:
        lines.extend(
            [
                f"- SAFE_TO_UPDATE: {safety['classifications'].get('SAFE_TO_UPDATE', 0)}",
                "",
                "## 安全性監査の保留理由",
                "",
            ]
        )
        hold_reasons = safety.get("hold_reasons", {})
        lines.extend(
            [f"- {reason}: {count}" for reason, count in hold_reasons.items()]
            or ["- なし"]
        )
    lines.extend(
        [
        "",
        "## 状態変化内訳",
        "",
        ]
    )
    lines.extend(
        f"- {transition}: {count}"
        for transition, count in report["planned_transitions"].items()
    )
    lines.extend(
        [
            "",
            "## 更新予定セル一覧",
            "",
            "| Sheet行 | セル | date | time | venue | event_name | old | new | Ticket照合根拠 | Results監査状態 |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in report["planned_updates"]:
        lines.append(
            f"| {item['sheet_row_number']} | {item['cell']} | {_md(item['date'])} | "
            f"{_md(item['time'])} | {_md(item['venue'])} | {_md(item['event_name'])} | "
            f"{_md(item['old_availability_status'])} | "
            f"{_md(item['new_availability_status'])} | "
            f"{_md(item['ticket_match_reason'])} | "
            f"{_md(item['results_audit_state'])} |"
        )
    lines.append("")
    if mode == "dry-run" and report.get("sheet_write") is False:
        lines.append(
            "この実行ではSheet、7列、行、列順、session_info、BOT状態を変更していない。"
        )
    elif mode == "apply":
        result = report.get("apply_result") or {}
        planned = report.get("planned_update_count")
        if (
            report.get("sheet_write") is True
            and type(planned) is int
            and result.get("applied") == planned
            and result.get("not_applied") == 0
            and result.get("unexpected") == 0
        ):
            lines.append(
                f"postwrite検証済み: 予定されたG列availability_statusの対象{planned}セルのみ更新。"
                "7列スキーマ、行数・行順・列順、A:F（session_infoを含む）、"
                "非対象Gセルは変更なし。BOT状態はこのupdaterでは変更していない。"
            )
        else:
            lines.append(
                "applyの完全成功は確認できていない。部分適用・想定外変更の可能性があるため"
                "成功扱いにしない。"
            )
    else:
        lines.append("実行モードまたは検証結果が不明のため、Sheet変更なしとは判定しない。")
    return "\n".join(lines) + "\n"


def write_plan_csv(path: Path, report: dict[str, Any]) -> None:
    fields = [
        "sheet_row_number",
        "cell",
        "date",
        "time",
        "venue",
        "event_name",
        "old_availability_status",
        "new_availability_status",
        "ticket_match_reason",
        "results_audit_state",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for item in report["planned_updates"]:
            writer.writerow({field: item[field] for field in fields})


def _default_audit_path(name: str) -> Path:
    today = datetime.now().astimezone().date().isoformat()
    return Path("logs") / f"aichi_nagoya_2026_{name}_{today}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read only (default)")
    mode.add_argument("--apply", action="store_true", help="write verified G cells")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument(
        "--content-audit",
        type=Path,
        default=_default_audit_path("content_audit").with_suffix(".md"),
    )
    parser.add_argument(
        "--content-reference-results",
        type=Path,
        default=_default_audit_path("results_audit").with_suffix(".json"),
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=_default_audit_path("availability_update_plan"),
    )
    parser.add_argument("--progress-log", type=Path)
    parser.add_argument(
        "--accepted-session-info-apply-report",
        type=Path,
        help="fully verified F-only session_info apply JSON for in-memory content-reference rebase",
    )
    parser.add_argument(
        "--overall-timeout", type=float, default=DEFAULT_OVERALL_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--sheets-request-timeout",
        type=float,
        default=DEFAULT_SHEETS_REQUEST_TIMEOUT_SECONDS,
    )
    args = parser.parse_args(argv)
    if args.overall_timeout <= 0 or args.request_timeout <= 0:
        parser.error("timeouts must be greater than zero")

    progress_path = args.progress_log or args.output_prefix.with_suffix(".progress.log")
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text("", encoding="utf-8")

    def progress(message: str) -> None:
        _progress(message)
        with progress_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    try:
        report, initial_rows = run_refresh(
            candidates_path=args.candidates,
            content_audit_path=args.content_audit,
            content_reference_results_path=args.content_reference_results,
            overall_timeout=args.overall_timeout,
            request_timeout=args.request_timeout,
            progress=progress,
            accepted_session_info_apply_report=(
                json.loads(args.accepted_session_info_apply_report.read_text(encoding="utf-8"))
                if args.accepted_session_info_apply_report else None
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
            )
            counts = apply_update_plan(
                initial_rows=initial_rows,
                plan=report["planned_updates"],
                read_sheet=read_sheet,
                batch_write=batch_write,
                progress=progress,
            )
            report["mode"] = "apply"
            report["sheet_write"] = True
            report["apply_result"] = counts
    except Exception as exc:
        progress(
            "availability_update stage=failed "
            f"error_type={type(exc).__name__} error={exc} sheet_write={str(args.apply).lower()}"
        )
        raise

    markdown_path = args.output_prefix.with_suffix(".md")
    csv_path = args.output_prefix.with_suffix(".csv")
    json_path = args.output_prefix.with_suffix(".json")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    write_plan_csv(csv_path, report)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
