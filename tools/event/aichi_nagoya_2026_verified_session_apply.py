"""Verify a completed F-only apply before rebasing a content reference in memory."""

from __future__ import annotations

import copy
from typing import Any


def rebase_content_reference_after_verified_apply(
    reference: dict[str, Any], apply_report: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy with only verified session_info changes applied."""

    result = copy.deepcopy(reference)
    apply_result = apply_report.get("apply_result") or {}
    planned = apply_report.get("planned_updates")
    if (
        apply_report.get("mode") != "apply"
        or apply_report.get("sheet_write") is not True
        or apply_report.get("target_column") != "F"
        or apply_report.get("target_field") != "session_info"
        or not isinstance(planned, list)
        or not planned
        or apply_report.get("planned_update_count") != len(planned)
        or apply_result.get("applied") != len(planned)
        or apply_result.get("not_applied") != 0
        or apply_result.get("unexpected") != 0
    ):
        raise ValueError("accepted apply report is not a completely verified F-only apply")

    rows = result.get("rows")
    if not isinstance(rows, list):
        raise ValueError("content reference has no rows")
    seen: set[int] = set()
    for item in planned:
        if not isinstance(item, dict) or type(item.get("sheet_row_number")) is not int:
            raise ValueError("invalid applied Sheet row")
        sheet_row = item["sheet_row_number"]
        data_index = sheet_row - 2
        if data_index < 0 or data_index >= len(rows) or sheet_row in seen:
            raise ValueError(f"invalid or duplicate applied Sheet row: {sheet_row}")
        seen.add(sheet_row)
        if item.get("cell") != f"F{sheet_row}" or item.get("sheet_data_row") != sheet_row - 1:
            raise ValueError(f"apply report does not target F{sheet_row}")
        sheet = rows[data_index].get("sheet")
        if not isinstance(sheet, dict):
            raise ValueError(f"content reference row {sheet_row} has no Sheet data")
        for field in ("date", "time", "venue", "event_name"):
            if str(sheet.get(field) or "").strip() != str(item.get(field) or "").strip():
                raise ValueError(
                    f"apply report identity differs from content reference at row {sheet_row}: {field}"
                )
        old = str(item.get("old_session_info") or "").strip()
        new = str(item.get("new_session_info") or "").strip()
        if not new or old == new:
            raise ValueError(f"apply report has no F change at row {sheet_row}")
        if str(sheet.get("session_info") or "").strip() != old:
            raise ValueError(f"apply report old session_info differs at row {sheet_row}")
        sheet["session_info"] = new
    return result
