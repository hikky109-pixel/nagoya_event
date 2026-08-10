import pytest
from pathlib import Path

import tools.event.build_aichi_nagoya_2026_baseline as baseline_module
from tools.event.build_aichi_nagoya_2026_baseline import (
    build_rows,
    classify_event_type,
    extract_allowed_categories,
    parse_datetime,
    protected_write,
)


KYUOGI = {
    "data": [
        {"url": "https://example.test/?parentCategory=3&eventCategory=7"},
        {"url": ""},
    ]
}
VENUES = {
    "data": [
        {"name": "会場［ホール］", "pref": "愛知", "address": "名古屋市", "comp": "競技", "ev": "種目"}
    ]
}


def product(**overrides):
    value = {
        "idProduct": 1,
        "idPerformance": 11,
        "idEventCategory": 7,
        "sessionCode": "AAA01",
        "idVenue": 5,
        "nmVenue": "会場[ホール]",
        "nmEvent": "競技",
        "nmEventCategory": "競技カテゴリ",
        "nmProduct": "午前セッション",
        "nmInfo": "予選",
        "availabilityStatus": "BUY",
        "cdSellingStatus": "BUY",
        "isSellable": True,
        "dhStart": "Sep 24, 2026, 10:00:00\u202fAM",
        "dhEnd": "Sep 24, 2026, 12:00:00\u202fPM",
    }
    value.update(overrides)
    return value


def test_allowlist_excludes_non_competition_and_keeps_same_day_sessions():
    allowed = extract_allowed_categories(KYUOGI)
    rows, _, _ = build_rows(
        [product(), product(idProduct=2, idPerformance=12, sessionCode="AAA02", dhStart="Sep 24, 2026, 5:00:00\u202fPM", dhEnd="Sep 24, 2026, 7:00:00\u202fPM"), product(idProduct=3, idEventCategory=99)],
        allowed,
        VENUES,
    )
    assert allowed == {7}
    assert [row["sessionCode"] for row in rows] == ["AAA01", "AAA02"]
    assert rows[0]["date"] == rows[1]["date"] == "2026-09-24"
    assert {row["event_type"] for row in rows} == {"competition"}


def test_ceremonies_are_adopted_but_ticket_products_remain_excluded():
    opening = product(idProduct=2, idPerformance=12, idEventCategory=78, nmEventCategory="開会式")
    closing = product(idProduct=3, idPerformance=13, idEventCategory=79, nmEventCategory="閉会式")
    service = product(idProduct=4, idPerformance=14, idEventCategory=99, nmEventCategory="プレミアムプラス")
    rows, _, _ = build_rows([opening, closing, service], {7}, VENUES)
    assert [row["event_type"] for row in rows] == ["opening_ceremony", "closing_ceremony"]
    assert classify_event_type(service, {7}) is None


def test_datetime_and_normalized_venue_match():
    assert parse_datetime("Sep 24, 2026, 10:00:00\u202fAM").strftime("%H:%M") == "10:00"
    selection = [{"正式名称（大会資料）": "会場（ホール）", "採用": "◎"}]
    rows, candidates, counts = build_rows([product()], {7}, VENUES, selection)
    assert rows[0]["end_time"] == "12:00:00"
    assert candidates[0]["venue_match"] == "normalized"
    assert candidates[0]["venue_address"] == "名古屋市"
    assert counts["venue_match_normalized"] == 1


def test_selection_master_limits_candidate_sessions():
    selection = [{"正式名称（大会資料）": "会場（ホール）", "採用": "◎", "エリア": "名古屋"}]
    _, candidates, _ = build_rows(
        [product(), product(idProduct=2, idPerformance=12, nmVenue="対象外会場")],
        {7},
        VENUES,
        selection,
    )
    assert len(candidates) == 1
    assert candidates[0]["selection_grade"] == "◎"


def test_missing_datetime_aborts_instead_of_creating_partial_baseline():
    with pytest.raises(ValueError, match="missing datetime"):
        build_rows([product(dhStart="")], {7}, VENUES)


def test_protected_write_refuses_different_same_date_snapshot(tmp_path: Path):
    target = tmp_path / "baseline.csv"
    assert protected_write(target, b"original") == "written"
    assert protected_write(target, b"original") == "unchanged"
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        protected_write(target, b"different")
    assert target.read_bytes() == b"original"


def test_zero_sessions_does_not_write_baseline(monkeypatch, tmp_path: Path):
    def fake_fetch(url):
        value = KYUOGI if "kyougi" in url else VENUES
        return b"{}", value

    monkeypatch.setattr(baseline_module, "fetch_json", fake_fetch)
    monkeypatch.setattr(baseline_module, "fetch_session_pages", lambda: ([], []))
    with pytest.raises(ValueError, match="unsafe competition session count=0"):
        baseline_module.create_baseline(tmp_path)
    assert not list(tmp_path.rglob("*"))
