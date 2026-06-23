from tools.event.build_spot_event_candidate import structure_spot_events


def test_structure_spot_events_keeps_each_date_independent() -> None:
    ocr_text = """
2026年6月
14 11:00 15:30
15 休演日
16 -
17 11:00 貸切
18 13:00/18:00
6月19日 09:00
"""
    assert structure_spot_events(ocr_text) == [
        {"date": "2026-06-14", "day": "11:00", "night": "15:30"},
        {"date": "2026-06-15", "status": "休演日"},
        {"date": "2026-06-17", "day": "11:00", "night": "貸切"},
        {"date": "2026-06-18", "day": "13:00", "night": "18:00"},
        {"date": "2026-06-19", "day": "09:00"},
    ]


def test_structure_spot_events_does_not_infer_missing_year_month() -> None:
    assert structure_spot_events("14 11:00 15:30") == []
