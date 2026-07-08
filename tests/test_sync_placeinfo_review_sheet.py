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
