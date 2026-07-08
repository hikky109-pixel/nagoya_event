from tools.location import sync_placeinfo_review_sheet


def test_default_place_dict_spreadsheet_id_prefers_place_dict(monkeypatch):
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "PLACE_DICT_SHEET_ID", "place-dict", raising=False)
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "LOCATION_SHEET_ID", "location", raising=False)
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "EVENT_SHEET_ID", "event", raising=False)

    assert sync_placeinfo_review_sheet.default_place_dict_spreadsheet_id() == "place-dict"


def test_default_place_dict_spreadsheet_id_uses_location_alias(monkeypatch):
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "PLACE_DICT_SHEET_ID", "", raising=False)
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "LOCATION_SHEET_ID", "location", raising=False)
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "EVENT_SHEET_ID", "event", raising=False)

    assert sync_placeinfo_review_sheet.default_place_dict_spreadsheet_id() == "location"


def test_default_place_dict_spreadsheet_id_falls_back_to_event(monkeypatch):
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "PLACE_DICT_SHEET_ID", "", raising=False)
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "LOCATION_SHEET_ID", "", raising=False)
    monkeypatch.setattr(sync_placeinfo_review_sheet.config, "EVENT_SHEET_ID", "event", raising=False)

    assert sync_placeinfo_review_sheet.default_place_dict_spreadsheet_id() == "event"


def test_place_dict_sheet_names_are_configured():
    expected = [
        "PlaceInfo_Review",
        "TB_TP",
        "Landmarks",
        "Road_Overrides",
        "Seeded_Taxi_Ops",
    ]

    assert sync_placeinfo_review_sheet.SHEET_NAME == "PlaceInfo_Review"
    assert sync_placeinfo_review_sheet.config.PLACE_DICT_SHEET_NAMES == expected


def test_merge_review_records_preserves_sheet_manual_review_columns():
    tsv_header = [
        "timestamp",
        "message_id",
        "lat",
        "lon",
        "address",
        "current_guess",
        "candidate1",
        "google_maps_url",
        "my_comment",
        "expected",
    ]
    tsv_records = [
        {
            "timestamp": "2026-07-09T06:00:01+09:00",
            "message_id": "msg-1",
            "lat": "35.1",
            "lon": "136.1",
            "address": "中区栄3丁目",
            "current_guess": "新しい推定",
            "candidate1": "新候補",
            "google_maps_url": "https://www.google.com/maps?q=35.1,136.1",
            "my_comment": "",
            "expected": "",
        }
    ]
    sheet_header = [
        "timestamp",
        "message_id",
        "lat",
        "lon",
        "address",
        "current_guess",
        "candidate1",
        "google_maps_url",
        "my_comment",
        "expected",
        "reviewed",
        "correct_address",
        "correct_road",
        "note",
    ]
    sheet_records = [
        {
            "timestamp": "2026-07-09T06:00:00+09:00",
            "message_id": "msg-1",
            "lat": "35.1",
            "lon": "136.1",
            "address": "中区栄3丁目",
            "current_guess": "古い推定",
            "candidate1": "旧候補",
            "google_maps_url": "https://www.google.com/maps?q=35.1,136.1",
            "my_comment": "手動コメント",
            "expected": "正解ラベル",
            "reviewed": "TRUE",
            "correct_address": "中区栄三丁目",
            "correct_road": "大津通",
            "note": "Sheetsだけのメモ",
        }
    ]

    values = sync_placeinfo_review_sheet.merge_review_records(tsv_header, tsv_records, sheet_header, sheet_records)
    header = values[0]
    row = dict(zip(header, values[1], strict=False))

    assert len(values) == 2
    assert row["current_guess"] == "新しい推定"
    assert row["candidate1"] == "新候補"
    assert row["reviewed"] == "TRUE"
    assert row["correct_address"] == "中区栄三丁目"
    assert row["correct_road"] == "大津通"
    assert row["note"] == "Sheetsだけのメモ"
    assert row["my_comment"] == "手動コメント"
    assert row["expected"] == "正解ラベル"


def test_merge_review_records_uses_fallback_key_and_avoids_duplicates():
    tsv_header = ["timestamp", "message_id", "lat", "lon", "address", "current_guess"]
    tsv_records = [
        {
            "timestamp": "2026-07-09T06:00:00+09:00",
            "message_id": "",
            "lat": "35.2",
            "lon": "136.2",
            "address": "中村区名駅1丁目",
            "current_guess": "新しい推定",
        }
    ]
    sheet_header = ["timestamp", "message_id", "lat", "lon", "address", "current_guess", "reviewed", "note"]
    sheet_records = [
        {
            "timestamp": "2026-07-09T06:00:00+09:00",
            "message_id": "",
            "lat": "35.2",
            "lon": "136.2",
            "address": "中村区名駅1丁目",
            "current_guess": "古い推定",
            "reviewed": "TRUE",
            "note": "fallback key保持",
        }
    ]

    values = sync_placeinfo_review_sheet.merge_review_records(tsv_header, tsv_records, sheet_header, sheet_records)
    row = dict(zip(values[0], values[1], strict=False))

    assert len(values) == 2
    assert row["current_guess"] == "新しい推定"
    assert row["reviewed"] == "TRUE"
    assert row["note"] == "fallback key保持"
