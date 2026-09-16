import pytest

from tools.event.aichi_nagoya_2026_availability_update_audit import (
    HOLD_CONTENT_OUTDATED,
    HOLD_RESULTS_MISMATCH,
    HOLD_TICKET_NOT_FOUND,
    NEEDS_REVIEW,
    SAFE_TO_UPDATE,
    cross_audit,
    parse_content_classifications,
    render_markdown,
)


def sheet(event_name="バスケットボール"):
    return {
        "date": "2026-09-20",
        "time": "10:00:00",
        "end_time": "12:00:00",
        "venue": "IGアリーナ",
        "event_name": event_name,
        "session_info": "男子準々決勝（4試合）",
        "availability_status": "BUY",
    }


def ticket_row(**overrides):
    source = sheet()
    row = {
        "sheet_data_row": 1,
        "sheet": source,
        "classification": "STATUS_CHANGED",
        "official_availability_status": "LIMITED",
        "candidate_count": 1,
        "reason": "baseline identity matched; stable IDs matched; status differs",
        "stable_ids": {
            "idPerformance": "11",
            "idProduct": "1",
            "sessionCode": "BKB01",
        },
        "baseline_ticket": {
            "date": source["date"],
            "time": source["time"],
            "end_time": source["end_time"],
            "venue": "愛知国際アリーナ",
            "event_name": source["event_name"],
            "session_info": source["session_info"],
        },
        "official_ticket": {
            "date": source["date"],
            "time": source["time"],
            "end_time": source["end_time"],
            "venue": "愛知国際アリーナ",
            "event_name": source["event_name"],
            "session_info": source["session_info"],
            "session_name": "バスケットボール - BKB01",
        },
    }
    row.update(overrides)
    return row


def results_row(classification="EXACT_MATCH", **overrides):
    row = {
        "classification": classification,
        "candidate_count": 1,
        "reason": "exact key",
        "sheet": sheet(),
        "results_candidates": [],
        "auto_selected": False,
    }
    row.update(overrides)
    return row


def report(ticket, results, content=None):
    return cross_audit(
        {"rows": ticket},
        {"rows": results},
        content or {1: "CONTENT_MATCH"},
    )


def test_exact_unique_mapping_is_safe_and_transition_is_counted():
    audited = report([ticket_row()], [results_row()])
    assert audited["rows"][0]["classification"] == SAFE_TO_UPDATE
    assert audited["summary"]["safe_transitions"]["BUY -> LIMITED"] == 1
    assert audited["summary"]["would_change_cells"] == 1


def test_exact_results_still_hold_unresolved_content_states():
    expected = {
        "CONTENT_OUTDATED": (HOLD_CONTENT_OUTDATED, "CONTENT_OUTDATED"),
        "INSUFFICIENT_SHEET_INFO": (NEEDS_REVIEW, "INSUFFICIENT_SHEET_INFO"),
        "NEEDS_REVIEW": (NEEDS_REVIEW, "CONTENT_NEEDS_REVIEW"),
    }
    for content_state, (classification, reason_code) in expected.items():
        audited = report([ticket_row()], [results_row()], {1: content_state})
        row = audited["rows"][0]
        assert row["classification"] == classification
        assert row["hold_reason_code"] == reason_code
        assert row["would_write"] is False


def test_only_explicit_safe_content_states_pass_exact_results():
    for content_state in ("CONTENT_MATCH", "AGGREGATED_OK"):
        audited = report([ticket_row()], [results_row()], {1: content_state})
        assert audited["rows"][0]["classification"] == SAFE_TO_UPDATE

    unknown = report([ticket_row()], [results_row()], {1: "FUTURE_STATE"})
    assert unknown["rows"][0]["classification"] == NEEDS_REVIEW
    assert unknown["rows"][0]["hold_reason_code"] == "CONTENT_UNKNOWN_STATE"


def test_changed_ticket_content_plus_outdated_results_content_is_held():
    ticket = ticket_row()
    ticket["official_ticket"] = {
        **ticket["official_ticket"],
        "session_info": "男子準々決勝（3試合）",
    }
    audited = report([ticket], [results_row()], {1: "CONTENT_OUTDATED"})
    assert audited["rows"][0]["classification"] == HOLD_CONTENT_OUTDATED
    assert audited["summary"]["hold_reasons"] == {"CONTENT_OUTDATED": 1}


@pytest.mark.parametrize(
    "results_state",
    ["TIME_MISMATCH", "VENUE_MISMATCH", "DATE_MISMATCH", "RESULTS_NOT_FOUND"],
)
def test_results_mismatches_are_held(results_state):
    mismatch = report([ticket_row()], [results_row(results_state)])
    row = mismatch["rows"][0]
    assert row["classification"] == HOLD_RESULTS_MISMATCH
    assert row["hold_reason_code"] == results_state


def test_ticket_core_change_is_held():

    ticket = ticket_row()
    ticket["official_ticket"] = {**ticket["official_ticket"], "time": "13:00:00"}
    core_change = report([ticket], [results_row()])
    assert core_change["rows"][0]["classification"] == HOLD_RESULTS_MISMATCH
    assert "time" in core_change["rows"][0]["decision_reason"]


def test_results_multiple_is_never_selected():
    audited = report([ticket_row()], [results_row("MULTIPLE_CANDIDATES")])
    assert audited["rows"][0]["classification"] == NEEDS_REVIEW
    assert audited["rows"][0]["would_write"] is False


def test_ticket_multiple_is_never_selected():
    ticket = ticket_row(classification="MULTIPLE_CANDIDATES")
    audited = report([ticket], [results_row()])
    assert audited["rows"][0]["classification"] == NEEDS_REVIEW
    assert audited["rows"][0]["hold_reason_code"] == "TICKET_MULTIPLE_CANDIDATES"
    assert audited["rows"][0]["would_write"] is False


def test_ticket_not_found_is_protected_even_when_results_are_exact():
    ticket = ticket_row(
        classification="NOT_FOUND",
        official_availability_status="",
        official_ticket={},
    )
    audited = report([ticket], [results_row()])
    assert audited["rows"][0]["classification"] == HOLD_TICKET_NOT_FOUND
    assert audited["summary"]["ticket_not_found_protected"] == 1


def test_ceremony_can_be_safe_without_results_or_content_row():
    ceremony_sheet = sheet("開会式")
    ticket = ticket_row(sheet=ceremony_sheet)
    ticket["baseline_ticket"] = {
        **ticket["baseline_ticket"],
        "event_name": "開会式",
    }
    ticket["official_ticket"] = {
        **ticket["official_ticket"],
        "event_name": "開会式",
    }
    results = results_row(
        "RESULTS_NOT_FOUND", sheet=ceremony_sheet, candidate_count=0
    )
    audited = cross_audit({"rows": [ticket]}, {"rows": [results]}, {})
    assert audited["rows"][0]["classification"] == SAFE_TO_UPDATE
    assert audited["rows"][0]["content_audit_state"] == "NOT_APPLICABLE"


def test_content_index_parser_and_markdown_are_machine_checkable():
    parsed = parse_content_classifications(
        "- `CONTENT_MATCH` (2): 1, 3\n- `CONTENT_OUTDATED` (1): 2\n"
    )
    assert parsed == {1: "CONTENT_MATCH", 3: "CONTENT_MATCH", 2: "CONTENT_OUTDATED"}
    rendered = render_markdown(report([ticket_row()], [results_row()]))
    assert "SAFE_TO_UPDATE (1件)" in rendered
    assert "Google Sheet書き込み: `false`" in rendered
