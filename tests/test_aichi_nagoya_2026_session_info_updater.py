import json
from pathlib import Path

import pytest

from tools.event import aichi_nagoya_2026_session_info_updater as updater


def sheet_row(**overrides):
    row = {
        "date": "2026-09-20",
        "time": "10:00:00",
        "end_time": "12:00:00",
        "venue": "IGアリーナ",
        "event_name": "バスケットボール",
        "session_info": "旧情報",
        "availability_status": "BUY",
    }
    row.update(overrides)
    return row


def audit_row(**overrides):
    row = {
        "sheet_row_number": 2,
        "sheet": sheet_row(),
        "current_session_info": "旧情報",
        "candidate_session_info": "男子準々決勝｜日本 vs 大韓民国",
        "result_code": "BKBMTEAM5-------------QFNL000100--",
        "classification": "SAFE_TO_UPDATE",
        "is_japan_match": True,
    }
    row.update(overrides)
    return row


def display_row(classification="DISPLAY_OK", sheet_row_number=2):
    return {
        "sheet_row_number": sheet_row_number,
        "display_classification": classification,
    }


def reports(audit=None, display=None):
    return (
        {"rows": [audit or audit_row()]},
        {"rows": [display or display_row()]},
    )


def test_only_safe_and_display_ok_becomes_f_column_plan():
    session, display = reports()
    plan, decisions = updater.build_update_plan(session, display)
    assert len(plan) == 1
    assert plan[0]["cell"] == "F2"
    assert plan[0]["new_session_info"] == "男子準々決勝｜日本 vs 大韓民国"
    assert decisions[0]["update_eligibility"] == "PLANNED"


@pytest.mark.parametrize(
    ("audit_classification", "display_classification", "eligibility"),
    [
        ("SAFE_TO_UPDATE", "DISPLAY_NEEDS_FIX", "HOLD_DISPLAY_NEEDS_FIX"),
        ("HOLD_TIME_MISMATCH", "NOT_REVIEWED", "HOLD_TIME_MISMATCH"),
        ("HOLD_MULTIPLE_CANDIDATES", "NOT_REVIEWED", "HOLD_MULTIPLE_CANDIDATES"),
        ("HOLD_CONTENT_OUTDATED", "NOT_REVIEWED", "HOLD_CONTENT_OUTDATED"),
        ("UNKNOWN_NEW_STATE", "NOT_REVIEWED", "HOLD_UNKNOWN_AUDIT_CLASSIFICATION"),
    ],
)
def test_unsafe_audit_or_display_states_are_held(
    audit_classification, display_classification, eligibility
):
    audit = audit_row(classification=audit_classification)
    display_rows = (
        [display_row(display_classification)]
        if audit_classification == "SAFE_TO_UPDATE"
        else []
    )
    plan, decisions = updater.build_update_plan(
        {"rows": [audit]}, {"rows": display_rows}
    )
    assert plan == []
    assert decisions[0]["update_eligibility"] == eligibility


def test_existing_identical_value_is_unchanged():
    candidate = "男子準々決勝｜日本 vs 大韓民国"
    audit = audit_row(
        sheet=sheet_row(session_info=candidate),
        current_session_info=candidate,
        candidate_session_info=candidate,
    )
    plan, decisions = updater.build_update_plan(
        {"rows": [audit]}, {"rows": [display_row()]}
    )
    assert plan == []
    assert decisions[0]["update_eligibility"] == "UNCHANGED"


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("女子準々決勝", "女子準々決勝｜インド vs 日本", "SAFE"),
        ("女子総当たり戦（3試合）", "女子総当たり戦｜日本 vs タイ", "HOLD_AGGREGATED_SESSION_INFO"),
        ("男女各4試合", "女子予選プールB｜日本 vs チャイニーズ・タイペイ", "HOLD_AGGREGATED_SESSION_INFO"),
        ("男子予選／女子予選", "男子予選グループA｜日本 vs ネパール", "HOLD_AGGREGATED_SESSION_INFO"),
        ("男子3位決定戦／男子決勝", "男子3位決定戦｜日本 vs 大韓民国", "HOLD_AGGREGATED_SESSION_INFO"),
        ("男子決勝 / メダル", "男子決勝｜日本 vs 大韓民国", "HOLD_AGGREGATED_SESSION_INFO"),
        ("男子予選グループA", "男子予選グループA｜日本 vs ネパール", "SAFE"),
        ("女子準々決勝・第1試合", "女子準々決勝｜インド vs 日本", "SAFE"),
        ("女子準々決勝／第1試合", "女子準々決勝｜インド vs 日本", "SAFE"),
        ("予選／詳細", "女子予選プールA｜日本 vs ネパール", "NEEDS_REVIEW"),
    ],
)
def test_information_preservation_gate(old, new, expected):
    classification, _reason = updater.information_preservation_gate(old, new)
    assert classification == expected


def test_aggregated_existing_info_is_removed_from_update_plan():
    audit = audit_row(
        sheet=sheet_row(session_info="女子総当たり戦（3試合）"),
        current_session_info="女子総当たり戦（3試合）",
        candidate_session_info="女子総当たり戦｜日本 vs タイ",
    )
    plan, decisions = updater.build_update_plan(
        {"rows": [audit]}, {"rows": [display_row()]}
    )
    assert plan == []
    assert decisions[0]["update_eligibility"] == "HOLD_AGGREGATED_SESSION_INFO"


@pytest.mark.parametrize("candidate", ["不明?", "不明？", "不明�", ""])
def test_empty_or_malformed_candidate_is_held(candidate):
    audit = audit_row(candidate_session_info=candidate)
    plan, decisions = updater.build_update_plan(
        {"rows": [audit]}, {"rows": [display_row()]}
    )
    assert plan == []
    assert decisions[0]["update_eligibility"].startswith("HOLD_")


def test_apply_prewrite_detects_sheet_change_before_f_write():
    session, display = reports()
    plan, _ = updater.build_update_plan(session, display)
    writes = []
    with pytest.raises(RuntimeError, match="prewrite"):
        updater.apply_update_plan(
            initial_rows=[sheet_row()],
            plan=plan,
            read_sheet=lambda: [sheet_row(time="11:00:00")],
            batch_write=lambda value: writes.append(value),
            progress=lambda _message: None,
            target_field="session_info",
            new_value_key="new_session_info",
            operation_name="session_info_apply",
        )
    assert writes == []


@pytest.mark.parametrize(
    "unexpected_after",
    [
        sheet_row(venue="別会場", session_info="男子準々決勝｜日本 vs 大韓民国"),
        sheet_row(availability_status="LIMITED", session_info="男子準々決勝｜日本 vs 大韓民国"),
    ],
)
def test_postwrite_rejects_a_to_e_or_g_changes(unexpected_after):
    session, display = reports()
    plan, _ = updater.build_update_plan(session, display)
    reads = iter([[sheet_row()], [unexpected_after]])
    with pytest.raises(RuntimeError, match="protected Sheet data"):
        updater.apply_update_plan(
            initial_rows=[sheet_row()], plan=plan,
            read_sheet=lambda: next(reads), batch_write=lambda _plan: None,
            progress=lambda _message: None, target_field="session_info",
            new_value_key="new_session_info", operation_name="session_info_apply",
        )


def test_postwrite_detects_non_target_f_change():
    first = audit_row()
    second = audit_row(
        sheet_row_number=3,
        sheet=sheet_row(event_name="サッカー", session_info="保持"),
        current_session_info="保持",
        classification="HOLD_TIME_MISMATCH",
    )
    plan, _ = updater.build_update_plan(
        {"rows": [first, second]}, {"rows": [display_row()]}
    )
    before = [sheet_row(), sheet_row(event_name="サッカー", session_info="保持")]
    after = [
        sheet_row(session_info=plan[0]["new_session_info"]),
        sheet_row(event_name="サッカー", session_info="勝手な変更"),
    ]
    reads = iter([before, after])
    with pytest.raises(RuntimeError, match="post-write verification failed"):
        updater.apply_update_plan(
            initial_rows=before, plan=plan, read_sheet=lambda: next(reads),
            batch_write=lambda _plan: None, progress=lambda _message: None,
            target_field="session_info", new_value_key="new_session_info",
            operation_name="session_info_apply",
        )


def test_default_dry_run_never_initializes_authenticated_service(tmp_path: Path, monkeypatch):
    report = {
        "generated_at": "2026-09-16T12:00:00+09:00",
        "mode": "dry-run", "sheet_write": False,
        "sheet_name": "アジア大会", "sheet_range_read": "A:G",
        "sheet_schema": list(updater.ASIA_OPERATIONAL_COLUMNS), "sheet_row_count": 245,
        "session_audit_summary": {"classifications": {"SAFE_TO_UPDATE": 0}},
        "display_review_summary": {"classifications": {"DISPLAY_OK": 0}},
        "eligibility_summary": {}, "planned_update_count": 0,
        "important_rounds": {}, "planned_updates": [], "decisions": [],
    }
    monkeypatch.setattr(updater, "run_refresh", lambda **_kwargs: (report, [sheet_row()]))
    monkeypatch.setattr(
        updater, "prepare_google_sheet_access",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("write service created")),
    )
    assert updater.main([
        "--dry-run", "--content-audit", str(tmp_path / "unused.md"),
        "--content-reference-results", str(tmp_path / "unused.json"),
        "--output-prefix", str(tmp_path / "plan"),
    ]) == 0
    assert json.loads((tmp_path / "plan.json").read_text())["sheet_write"] is False


def test_verified_apply_report_can_rebase_only_its_session_info_changes():
    reference = {"rows": [{"sheet": sheet_row()}]}
    item = {
        "sheet_row_number": 2,
        "date": "2026-09-20",
        "time": "10:00:00",
        "venue": "IGアリーナ",
        "event_name": "バスケットボール",
        "old_session_info": "旧情報",
        "new_session_info": "男子準々決勝｜日本 vs 大韓民国",
    }
    apply_report = {
        "mode": "apply",
        "sheet_write": True,
        "planned_updates": [item],
        "apply_result": {"applied": 1, "not_applied": 0, "unexpected": 0},
    }
    rebased = updater.rebase_content_reference_after_verified_apply(
        reference, apply_report
    )
    assert rebased["rows"][0]["sheet"]["session_info"] == item["new_session_info"]
    assert reference["rows"][0]["sheet"]["session_info"] == "旧情報"


@pytest.mark.parametrize(
    "apply_result",
    [
        {"applied": 0, "not_applied": 1, "unexpected": 0},
        {"applied": 1, "not_applied": 0, "unexpected": 1},
    ],
)
def test_incomplete_apply_report_cannot_rebase_content_reference(apply_result):
    report = {
        "mode": "apply",
        "sheet_write": True,
        "planned_updates": [{"sheet_row_number": 2}],
        "apply_result": apply_result,
    }
    with pytest.raises(ValueError, match="completely verified"):
        updater.rebase_content_reference_after_verified_apply(
            {"rows": [{"sheet": sheet_row()}]}, report
        )
