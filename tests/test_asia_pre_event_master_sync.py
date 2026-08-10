import pytest

from scrapers.utils.google_sheet_events import _validate_immutable_snapshot_rows


HEADER = ["snapshot_date", "event_type", "idProduct"]
ROWS = [HEADER, ["2026-08-10", "competition", "1"]]


def test_empty_sheet_allows_initial_immutable_snapshot_write():
    assert _validate_immutable_snapshot_rows(ROWS, []) == ("write", "2026-08-10")


def test_identical_snapshot_is_idempotent():
    assert _validate_immutable_snapshot_rows(ROWS, ROWS) == ("unchanged", "2026-08-10")


def test_same_snapshot_difference_is_never_overwritten():
    changed = [HEADER, ["2026-08-10", "competition", "2"]]
    with pytest.raises(RuntimeError, match="differs for snapshot_date=2026-08-10"):
        _validate_immutable_snapshot_rows(ROWS, changed)


def test_other_snapshot_is_not_appended_to_fixed_master():
    existing = [HEADER, ["2026-08-11", "competition", "1"]]
    with pytest.raises(RuntimeError, match="refusing to append"):
        _validate_immutable_snapshot_rows(ROWS, existing)


def test_mixed_snapshot_csv_is_rejected():
    mixed = ROWS + [["2026-08-11", "competition", "2"]]
    with pytest.raises(ValueError, match="exactly one snapshot_date"):
        _validate_immutable_snapshot_rows(mixed, [])
