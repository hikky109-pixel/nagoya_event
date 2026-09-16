from pathlib import Path

import pytest

from tools.event.aichi_nagoya_2026_ticket_status_audit import (
    MULTIPLE_CANDIDATES,
    NOT_FOUND,
    STATUS_CHANGED,
    UNCHANGED,
    audit_sheet_rows,
    render_markdown,
    run_audit,
    summarize,
)


def candidate(**overrides):
    row = {
        "event_type": "competition",
        "idPerformance": "11",
        "idProduct": "1",
        "sessionCode": "AAA01",
        "date": "2026-09-20",
        "time": "10:00:00",
        "end_time": "12:00:00",
        "venue": "愛知国際アリーナ",
        "db_display_name": "IGアリーナ",
        "event_name": "バスケットボール",
        "session_info": "男子予選（2試合）",
        "availability_status": "BUY",
    }
    row.update(overrides)
    return row


def sheet(**overrides):
    row = {
        "date": "2026-09-20",
        "time": "10:00:00",
        "end_time": "12:00:00",
        "venue": "IGアリーナ",
        "event_name": "バスケットボール",
        "session_info": "男子予選（2試合）",
        "availability_status": "BUY",
    }
    row.update(overrides)
    return row


def product(**overrides):
    row = {
        "idPerformance": 11,
        "idProduct": 1,
        "sessionCode": "AAA01",
        "dhStart": "Sep 20, 2026, 10:00:00 AM",
        "dhEnd": "Sep 20, 2026, 12:00:00 PM",
        "nmVenue": "愛知国際アリーナ",
        "nmEvent": "バスケットボール",
        "nmInfo": "男子予選（2試合）",
        "availabilityStatus": "BUY",
        "nmProduct": "バスケットボール - AAA01",
    }
    row.update(overrides)
    return row


def test_unchanged_and_changed_are_compared_only_after_stable_id_match():
    rows, excluded = audit_sheet_rows(
        [sheet(), sheet(availability_status="SOLD_OUT")],
        [candidate()],
        [product(availabilityStatus="LIMITED")],
    )
    assert excluded == 0
    assert [row["classification"] for row in rows] == [
        STATUS_CHANGED,
        STATUS_CHANGED,
    ]
    assert rows[0]["official_availability_status"] == "LIMITED"
    assert rows[0]["auto_selected"] is False


def test_unchanged_status_is_reported():
    rows, _ = audit_sheet_rows([sheet()], [candidate()], [product()])
    assert rows[0]["classification"] == UNCHANGED


def test_manual_session_info_change_can_still_use_unique_five_field_identity():
    rows, _ = audit_sheet_rows(
        [sheet(session_info="公式Results反映後の説明")],
        [candidate()],
        [product(availabilityStatus="LIMITED")],
    )
    assert rows[0]["classification"] == STATUS_CHANGED
    assert "session_info" not in rows[0]["reason"].split("fields=")[-1].split(";")[0]


def test_ambiguous_baseline_candidates_are_never_selected():
    second = candidate(
        idPerformance="12",
        idProduct="2",
        sessionCode="AAA02",
        time="13:00:00",
        end_time="15:00:00",
        session_info="男子予選（別セッション）",
    )
    rows, _ = audit_sheet_rows(
        [sheet(time="11:00:00", end_time="14:00:00", session_info="集約")],
        [candidate(), second],
        [product(), product(idPerformance=12, idProduct=2, sessionCode="AAA02")],
    )
    assert rows[0]["classification"] == MULTIPLE_CANDIDATES
    assert rows[0]["candidate_count"] == 2
    assert rows[0]["stable_ids"] == {}


def test_missing_current_stable_id_and_unknown_status_are_not_changes():
    missing, _ = audit_sheet_rows([sheet()], [candidate()], [])
    unknown, _ = audit_sheet_rows(
        [sheet()], [candidate()], [product(availabilityStatus="QUEUE")]
    )
    assert missing[0]["classification"] == NOT_FOUND
    assert unknown[0]["classification"] == NOT_FOUND
    assert "unsupported" in unknown[0]["reason"]


def test_current_ticket_metadata_is_preserved_for_cross_audit():
    rows, _ = audit_sheet_rows([sheet()], [candidate()], [product()])
    assert rows[0]["baseline_ticket"]["venue"] == "愛知国際アリーナ"
    assert rows[0]["official_ticket"] == {
        "date": "2026-09-20",
        "time": "10:00:00",
        "end_time": "12:00:00",
        "venue": "愛知国際アリーナ",
        "event_name": "バスケットボール",
        "session_info": "男子予選（2試合）",
        "session_name": "バスケットボール - AAA01",
    }


def test_invalid_current_product_datetime_fails_closed():
    rows, _ = audit_sheet_rows(
        [sheet()], [candidate()], [product(dhStart="", availabilityStatus="LIMITED")]
    )
    assert rows[0]["classification"] == NOT_FOUND
    assert "invalid date/time metadata" in rows[0]["reason"]


def test_fire_test_is_excluded_and_sheet_input_is_not_mutated():
    source = sheet(event_name="【発火テスト】アジア大会")
    before = dict(source)
    rows, excluded = audit_sheet_rows([source], [candidate()], [product()])
    assert rows == []
    assert excluded == 1
    assert source == before


def test_summary_and_markdown_show_old_to_new_without_write_claim():
    rows, _ = audit_sheet_rows(
        [sheet()], [candidate()], [product(availabilityStatus="LIMITED")]
    )
    summary = summarize(rows)
    assert summary["protected_effective_statuses"] == {"LIMITED": 1}
    report = {
        "sheet_row_count": 1,
        "business_row_count": 1,
        "excluded_test_rows": 0,
        "official_product_count": 2,
        "summary": summary,
        "rows": rows,
    }
    rendered = render_markdown(report)
    assert "BUY -> LIMITED: 1" in rendered
    assert "Google Sheet書き込み: `false`" in rendered


def test_run_audit_fails_closed_on_empty_official_response(tmp_path: Path):
    path = tmp_path / "candidates.csv"
    fields = list(candidate())
    import csv

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(candidate())

    with pytest.raises(ValueError, match="unsafe current official ticket response"):
        run_audit(
            candidates_path=path,
            sheet_loader=lambda: [sheet()],
            session_fetcher=lambda: ([], []),
            overall_timeout=5,
        )
