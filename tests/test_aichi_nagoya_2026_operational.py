import csv
from pathlib import Path

import pytest

from scrapers.utils.google_sheet_events import (
    ASIA_OPERATIONAL_COLUMNS,
    _validate_asia_operational_rows,
)
from tools.event.build_aichi_nagoya_2026_operational import (
    OPERATIONAL_FIELDS,
    build_operational_rows,
    create_operational_csv,
)


def source_row(**overrides):
    row = {
        "snapshot_date": "2026-08-10",
        "event_type": "competition",
        "idProduct": "1",
        "idPerformance": "11",
        "sessionCode": "AAA01",
        "date": "2026-09-20",
        "time": "10:00:00",
        "end_time": "12:00:00",
        "venue": "愛知国際アリーナ",
        "db_display_name": "IGアリーナ",
        "event_name": "競泳",
        "session_info": "女子50m自由形 予選 ／ 男子50mバタフライ 予選",
        "availability_status": "LIMITED",
    }
    row.update(overrides)
    return row


def test_operational_rows_use_fixed_columns_display_venue_and_keep_source_values():
    long_info = "長文" * 1000
    baseline = [source_row()]
    candidates = [source_row(session_info=long_info)]
    rows, stats = build_operational_rows(baseline, candidates)
    assert list(rows[0]) == OPERATIONAL_FIELDS
    assert rows[0]["venue"] == "IGアリーナ"
    assert rows[0]["availability_status"] == "LIMITED"
    assert rows[0]["session_info"] == long_info
    assert stats["asia_operational_output_records"] == 1


def test_opening_closing_and_same_time_sessions_are_all_kept_and_sorted():
    competition = source_row()
    opening = source_row(
        idProduct="2",
        idPerformance="12",
        sessionCode="OOC01",
        event_type="opening_ceremony",
        event_name="開会式 (アジア大会)",
    )
    closing = source_row(
        idProduct="3",
        idPerformance="13",
        sessionCode="OCC01",
        event_type="closing_ceremony",
        event_name="閉会式 (アジア大会)",
        date="2026-10-04",
    )
    rows, stats = build_operational_rows(
        [competition, opening, closing],
        [competition, opening, closing],
    )
    assert len(rows) == 3
    assert [row["event_name"] for row in rows] == ["競泳", "開会式", "閉会式"]
    assert stats["asia_operational_opening_records"] == 1
    assert stats["asia_operational_closing_records"] == 1


def test_only_candidate_rows_are_selected():
    selected = source_row()
    outside = source_row(idProduct="9", idPerformance="19", sessionCode="OUT01")
    rows, _ = build_operational_rows([selected, outside], [selected])
    assert len(rows) == 1
    assert rows[0]["venue"] == "IGアリーナ"


def test_unresolved_display_venue_aborts():
    with pytest.raises(ValueError, match="venue resolution failed"):
        build_operational_rows([source_row()], [source_row(db_display_name="")])


def test_build_does_not_modify_baseline(tmp_path: Path):
    baseline = tmp_path / "baseline.csv"
    candidates = tmp_path / "candidates.csv"
    output = tmp_path / "operational.csv"
    fields = list(source_row())
    for path in (baseline, candidates):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(source_row())
    before = baseline.read_bytes()
    create_operational_csv(baseline, candidates, output)
    assert baseline.read_bytes() == before
    with output.open(encoding="utf-8-sig", newline="") as handle:
        assert next(csv.reader(handle)) == OPERATIONAL_FIELDS


def test_empty_operational_data_never_replaces_sheet():
    with pytest.raises(ValueError, match="at least one data row"):
        _validate_asia_operational_rows([ASIA_OPERATIONAL_COLUMNS], [])


def test_different_populated_sheet_is_protected():
    csv_rows = [ASIA_OPERATIONAL_COLUMNS, ["2026-09-20", "10:00", "12:00", "IG", "競泳", "予選", "BUY"]]
    existing = [ASIA_OPERATIONAL_COLUMNS, ["manual", "", "", "", "", "", ""]]
    with pytest.raises(RuntimeError, match="refusing automatic replacement"):
        _validate_asia_operational_rows(csv_rows, existing)
