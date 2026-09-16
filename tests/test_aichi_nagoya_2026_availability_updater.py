import json
from pathlib import Path

import pytest

from tools.event import aichi_nagoya_2026_availability_updater as updater


def sheet_row(**overrides):
    row = {
        "date": "2026-09-20",
        "time": "10:00:00",
        "end_time": "12:00:00",
        "venue": "IGアリーナ",
        "event_name": "バスケットボール",
        "session_info": "男子準々決勝（4試合）",
        "availability_status": "BUY",
    }
    row.update(overrides)
    return row


def safe_cross_row(**overrides):
    row = {
        "sheet_data_row": 1,
        "classification": "SAFE_TO_UPDATE",
        "sheet": sheet_row(),
        "old_availability_status": "BUY",
        "new_availability_status": "LIMITED",
        "ticket_match_reason": "unique stable IDs",
        "results_audit_state": "EXACT_MATCH",
    }
    row.update(overrides)
    return row


def test_build_update_plan_targets_only_physical_g_cells():
    plan = updater.build_update_plan(
        {
            "rows": [
                safe_cross_row(),
                safe_cross_row(
                    sheet_data_row=2,
                    classification="HOLD_RESULTS_MISMATCH",
                ),
            ]
        }
    )
    assert len(plan) == 1
    assert plan[0]["sheet_row_number"] == 2
    assert plan[0]["cell"] == "G2"
    assert plan[0]["new_availability_status"] == "LIMITED"


def test_content_reference_requires_all_other_six_columns_to_match():
    reference = {"rows": [{"sheet": sheet_row(availability_status="SOLD_OUT")}]}
    updater.validate_content_reference([sheet_row()], reference)
    with pytest.raises(ValueError, match="session_info"):
        updater.validate_content_reference(
            [sheet_row(session_info="changed")], reference
        )


def test_apply_preflight_and_postflight_allow_only_planned_status_cell():
    before = [sheet_row()]
    after = [sheet_row(availability_status="LIMITED")]
    reads = iter([before, after])
    written = []
    logs = []
    result = updater.apply_update_plan(
        initial_rows=before,
        plan=updater.build_update_plan({"rows": [safe_cross_row()]}),
        read_sheet=lambda: next(reads),
        batch_write=lambda plan: written.extend(plan),
        progress=logs.append,
    )
    assert result == {"applied": 1, "not_applied": 0, "unexpected": 0}
    assert [item["cell"] for item in written] == ["G2"]
    assert any("postwrite_verified applied=1" in line for line in logs)


def test_apply_aborts_before_write_if_sheet_snapshot_changed():
    writes = []
    with pytest.raises(RuntimeError, match="prewrite"):
        updater.apply_update_plan(
            initial_rows=[sheet_row()],
            plan=updater.build_update_plan({"rows": [safe_cross_row()]}),
            read_sheet=lambda: [sheet_row(time="11:00:00")],
            batch_write=lambda plan: writes.append(plan),
            progress=lambda _message: None,
        )
    assert writes == []


def test_apply_rejects_non_status_change_after_write():
    reads = iter([[sheet_row()], [sheet_row(venue="別会場", availability_status="LIMITED")]])
    with pytest.raises(RuntimeError, match="non-availability"):
        updater.apply_update_plan(
            initial_rows=[sheet_row()],
            plan=updater.build_update_plan({"rows": [safe_cross_row()]}),
            read_sheet=lambda: next(reads),
            batch_write=lambda _plan: None,
            progress=lambda _message: None,
        )


def test_partial_write_error_logs_confirmed_success_count():
    reads = iter([[sheet_row()], [sheet_row(availability_status="LIMITED")]])
    logs = []

    def fail_after_commit(_plan):
        raise TimeoutError("response lost")

    with pytest.raises(TimeoutError, match="response lost"):
        updater.apply_update_plan(
            initial_rows=[sheet_row()],
            plan=updater.build_update_plan({"rows": [safe_cross_row()]}),
            read_sheet=lambda: next(reads),
            batch_write=fail_after_commit,
            progress=logs.append,
        )
    assert any("partial_failure_verified applied=1" in line for line in logs)


def test_authenticated_values_parser_requires_exact_header_and_no_blank_rows():
    values = [updater.ASIA_OPERATIONAL_COLUMNS, list(sheet_row().values())]
    assert updater._parse_values_rows(values) == [sheet_row()]
    with pytest.raises(ValueError, match="header differs"):
        updater._parse_values_rows([["bad"]])
    with pytest.raises(ValueError, match="blank row"):
        updater._parse_values_rows([updater.ASIA_OPERATIONAL_COLUMNS, []])


def test_g_cell_validation_is_checked_before_write():
    response = {
        "sheets": [
            {
                "data": [
                    {
                        "startRow": 1,
                        "rowData": [
                            {
                                "values": [
                                    {
                                        "dataValidation": {
                                            "condition": {
                                                "type": "ONE_OF_LIST",
                                                "values": [
                                                    {"userEnteredValue": "BUY"},
                                                    {"userEnteredValue": "LIMITED"},
                                                    {"userEnteredValue": "SOLD_OUT"},
                                                ],
                                            }
                                        }
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        ]
    }
    rules = updater.extract_validation_rules(response)
    plan = updater.build_update_plan({"rows": [safe_cross_row()]})
    updater.validate_planned_statuses_against_rules(plan, rules)
    plan[0]["new_availability_status"] = "UNKNOWN"
    with pytest.raises(RuntimeError, match="violates validation"):
        updater.validate_planned_statuses_against_rules(plan, rules)


def test_run_refresh_fetches_ticket_then_sheet_then_results(tmp_path: Path, monkeypatch):
    order = []
    current = sheet_row()
    content = tmp_path / "content.md"
    content.write_text("- `CONTENT_MATCH` (1): 1\n", encoding="utf-8")
    reference = tmp_path / "results.json"
    reference.write_text(
        json.dumps({"rows": [{"sheet": current}]}), encoding="utf-8"
    )
    monkeypatch.setattr(updater, "_read_candidate_rows", lambda _path: [{}])
    monkeypatch.setattr(
        updater,
        "audit_ticket_sheet_rows",
        lambda *_args: ([{"classification": "UNCHANGED"}], 0),
    )
    monkeypatch.setattr(
        updater,
        "summarize_ticket",
        lambda _rows: {"classifications": {"UNCHANGED": 1}},
    )
    monkeypatch.setattr(
        updater,
        "audit_results_sheet_rows",
        lambda rows, _results: [
            {
                "classification": "EXACT_MATCH",
                "candidate_count": 1,
                "reason": "exact",
                "sheet": rows[0],
            }
        ],
    )
    monkeypatch.setattr(
        updater,
        "summarize_results",
        lambda _rows: {"EXACT_MATCH": 1},
    )

    def tickets():
        order.append("ticket")
        return ([{}], [{}, {}])

    def sheet():
        order.append("sheet")
        return [current]

    def results(_rows, _remaining):
        order.append("results")
        return ([current["date"]], [{}])

    report, _ = updater.run_refresh(
        candidates_path=tmp_path / "unused.csv",
        content_audit_path=content,
        content_reference_results_path=reference,
        overall_timeout=10,
        request_timeout=1,
        progress=lambda _message: None,
        ticket_fetcher=tickets,
        sheet_loader=sheet,
        results_fetcher=results,
    )
    assert order == ["ticket", "sheet", "results"]
    assert report["sheet_write"] is False


def test_default_cli_mode_never_prepares_google_write_access(
    tmp_path: Path, monkeypatch
):
    report = {
        "generated_at": "2026-09-15T12:00:00+09:00",
        "mode": "dry-run",
        "sheet_write": False,
        "sheet_name": "アジア大会",
        "sheet_range_read": "A:G",
        "planned_update_count": 0,
        "planned_transitions": {
            f"{old} -> {new}": 0 for old, new in updater.TRANSITIONS
        },
        "planned_updates": [],
    }
    monkeypatch.setattr(updater, "run_refresh", lambda **_kwargs: (report, [sheet_row()]))

    def forbidden(**_kwargs):
        raise AssertionError("write access must not be initialized in default mode")

    monkeypatch.setattr(updater, "prepare_google_sheet_access", forbidden)
    assert updater.main(["--output-prefix", str(tmp_path / "plan")]) == 0
    assert (tmp_path / "plan.json").exists()
