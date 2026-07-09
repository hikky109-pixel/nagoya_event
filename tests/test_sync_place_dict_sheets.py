from pathlib import Path

from tools.location import sync_place_dict_sheets


def test_place_override_records_are_split_by_source():
    grouped = sync_place_dict_sheets.place_override_sheet_records()

    assert len(grouped["Seeded_Taxi_Ops"]) == 4
    assert len(grouped["Landmarks"]) == 12
    assert len(grouped["Place_Label_Overrides"]) == 2
    assert grouped["Seeded_Taxi_Ops"][0]["source"] == "seeded_taxi_ops"
    assert any(
        row["id"] == "nagoya_station_taikodori_taxi_stand"
        and row["label"] == "新幹線口TP"
        and row["lat"] == "35.16998"
        and row["lon"] == "136.8808"
        and row["radius_m"] == "60"
        for row in grouped["Seeded_Taxi_Ops"]
    )
    assert grouped["Landmarks"][0]["source"] == "seeded_landmark"
    assert grouped["Place_Label_Overrides"][0]["source"] == "user_corrected"


def test_road_alias_records_are_mapped_to_road_aliases():
    records = sync_place_dict_sheets.road_alias_sheet_records()

    assert len(records) >= 15
    assert any(record["id"] == "sakuradori" and record["name"] == "桜通" for record in records)
    assert any(record["id"] == "mitsukuradori" and "31512981" in record["geometry"] for record in records)
    assert "note" not in records[0]
    assert "source_note" in records[0]


def test_merge_preserves_manual_columns_and_updates_local_columns():
    local_header = sync_place_dict_sheets.PLACE_AUTO_COLUMNS
    local_records = [
        {
            "id": "spot-1",
            "lat": "35.1",
            "lon": "136.1",
            "radius_m": "80",
            "label": "新ラベル",
            "source": "seeded_landmark",
            "confidence": "confirmed",
            "priority": "100",
        }
    ]
    sheet_header = [*sync_place_dict_sheets.PLACE_AUTO_COLUMNS, *sync_place_dict_sheets.MANUAL_COLUMNS]
    sheet_records = [
        {
            "id": "spot-1",
            "lat": "35.1",
            "lon": "136.1",
            "radius_m": "60",
            "label": "旧ラベル",
            "source": "seeded_landmark",
            "confidence": "provisional",
            "priority": "500",
            "reviewed": "TRUE",
            "note": "手動メモ",
            "enabled": "FALSE",
            "updated_by": "hide",
        }
    ]

    values = sync_place_dict_sheets.merge_sheet_records(
        local_header,
        local_records,
        sheet_header,
        sheet_records,
        key_fn=sync_place_dict_sheets.place_row_key,
    )
    row = dict(zip(values[0], values[1], strict=False))

    assert len(values) == 2
    assert row["label"] == "新ラベル"
    assert row["radius_m"] == "80"
    assert row["reviewed"] == "TRUE"
    assert row["note"] == "手動メモ"
    assert row["enabled"] == "FALSE"
    assert row["updated_by"] == "hide"


def test_merge_dedupes_existing_sheet_rows_and_keeps_manual_values():
    local_header = ["id", "name", "direction", "start", "end"]
    local_records = [{"id": "road-1", "name": "新通", "direction": "east_west", "start": "A", "end": "B"}]
    sheet_header = ["id", "name", "direction", "start", "end", "reviewed", "note", "enabled", "updated_by"]
    sheet_records = [
        {"id": "road-1", "name": "旧通", "reviewed": "", "note": "", "enabled": "TRUE", "updated_by": ""},
        {"id": "road-1", "name": "旧通 duplicate", "reviewed": "TRUE", "note": "duplicate note", "enabled": "", "updated_by": "hide"},
    ]

    values = sync_place_dict_sheets.merge_sheet_records(
        local_header,
        local_records,
        sheet_header,
        sheet_records,
        key_fn=sync_place_dict_sheets.road_row_key,
    )
    row = dict(zip(values[0], values[1], strict=False))

    assert len(values) == 2
    assert row["name"] == "新通"
    assert row["reviewed"] == "TRUE"
    assert row["note"] == "duplicate note"
    assert row["enabled"] == "TRUE"
    assert row["updated_by"] == "hide"


def test_fallback_key_dedupes_place_rows_without_id():
    local_header = ["id", "lat", "lon", "label", "source"]
    local_records = [{"id": "", "lat": "35.1", "lon": "136.1", "label": "同地点", "source": "user_corrected"}]
    sheet_header = [*local_header, "note"]
    sheet_records = [{"id": "", "lat": "35.1", "lon": "136.1", "label": "同地点", "source": "user_corrected", "note": "keep"}]

    values = sync_place_dict_sheets.merge_sheet_records(
        local_header,
        local_records,
        sheet_header,
        sheet_records,
        key_fn=sync_place_dict_sheets.place_row_key,
    )
    row = dict(zip(values[0], values[1], strict=False))

    assert len(values) == 2
    assert row["note"] == "keep"


class FakeExecute:
    def execute(self):
        return {}


class FakeValues:
    def __init__(self):
        self.updated = []
        self.cleared = []

    def update(self, **kwargs):
        self.updated.append(kwargs)
        return FakeExecute()

    def clear(self, **kwargs):
        self.cleared.append(kwargs)
        return FakeExecute()


class FakeSpreadsheets:
    def __init__(self):
        self.values_obj = FakeValues()

    def values(self):
        return self.values_obj


class FakeService:
    def __init__(self):
        self.spreadsheets_obj = FakeSpreadsheets()

    def spreadsheets(self):
        return self.spreadsheets_obj


def test_sync_records_to_sheet_does_not_clear_whole_sheet(monkeypatch):
    service = FakeService()

    monkeypatch.setattr("scrapers.utils.google_sheet_events._sheet_exists", lambda service, spreadsheet_id, sheet_name: True)
    monkeypatch.setattr("scrapers.utils.google_sheet_events._read_sheet_rows", lambda service, spreadsheet_id, sheet_name: [["id"], ["old"], ["old"]])

    count = sync_place_dict_sheets.sync_records_to_sheet(
        service,
        "spreadsheet-id",
        "Seeded_Taxi_Ops",
        ["id"],
        [{"id": "old"}],
        key_fn=lambda row: row["id"],
    )

    assert count == 1
    assert service.spreadsheets_obj.values_obj.updated
    assert all(call["range"] != "Seeded_Taxi_Ops" for call in service.spreadsheets_obj.values_obj.cleared)
    assert service.spreadsheets_obj.values_obj.cleared[0]["range"].startswith("Seeded_Taxi_Ops!A")


def test_sync_place_dict_sheets_uses_place_dict_id_and_all_target_sheets(monkeypatch, tmp_path: Path):
    service = FakeService()
    created = []
    read_sheet_names = []

    monkeypatch.setattr(sync_place_dict_sheets, "default_place_dict_spreadsheet_id", lambda: "place-dict")
    monkeypatch.setattr("scrapers.utils.google_sheet_events._sheets_service", lambda: service)
    monkeypatch.setattr("scrapers.utils.google_sheet_events._sheet_exists", lambda service, spreadsheet_id, sheet_name: True)
    monkeypatch.setattr("scrapers.utils.google_sheet_events._create_sheet", lambda service, spreadsheet_id, sheet_name: created.append(sheet_name))

    def fake_read_sheet_rows(service, spreadsheet_id, sheet_name):
        read_sheet_names.append(sheet_name)
        return []

    monkeypatch.setattr("scrapers.utils.google_sheet_events._read_sheet_rows", fake_read_sheet_rows)

    overrides_path = tmp_path / "place_label_overrides.yml"
    overrides_path.write_text(
        """version: 1
spots:
  - id: taxi
    lat: 35.1
    lon: 136.1
    radius_m: 60
    label: タクシーのりば
    source: seeded_taxi_ops
    confidence: provisional
    priority: 200

  - id: landmark
    lat: 35.2
    lon: 136.2
    radius_m: 70
    label: ランドマーク
    source: seeded_landmark
    confidence: provisional
    priority: 500

  - id: corrected
    lat: 35.3
    lon: 136.3
    radius_m: 80
    label: ユーザー補正
    source: user_corrected
    confidence: confirmed
    priority: 100
""",
        encoding="utf-8",
    )
    road_aliases_path = tmp_path / "road_aliases.yml"
    road_aliases_path.write_text(
        """version: 1
roads:
  - id: road
    name: 道路
    direction: east_west
    aliases: [道路]
    source_url: https://example.com
    start: A
    end: B
    road_numbers: []
    intersections: [A交差点]
    geometry:
    note: source note
""",
        encoding="utf-8",
    )

    results = sync_place_dict_sheets.sync_place_dict_sheets(
        overrides_path=overrides_path,
        road_aliases_path=road_aliases_path,
    )

    assert results == {
        "Seeded_Taxi_Ops": 1,
        "Landmarks": 1,
        "Place_Label_Overrides": 1,
        "Road_Aliases": 1,
    }
    assert read_sheet_names == ["Seeded_Taxi_Ops", "Landmarks", "Place_Label_Overrides", "Road_Aliases"]
    assert created == []
