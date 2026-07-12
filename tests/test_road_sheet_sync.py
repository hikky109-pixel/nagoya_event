from scrapers.utils.google_sheet_events import (
    ROAD_COLUMNS,
    _merge_road_records,
    _road_sync_key,
    _write_road_sheet_values,
)
from scrapers.utils.road_validation import SPRING_TRAFFIC_SAFETY_TITLE


def road_record(**overrides):
    record = {
        "date": "2026-07-12",
        "time": "未定",
        "end_time": "",
        "venue": "愛知県内",
        "title": "交通取締予定",
        "source": "愛知県警",
        "status": "confirmed",
        "note": "取締",
        "url": "https://example.invalid/road.pdf",
    }
    record.update(overrides)
    return record


def test_road_sync_adds_new_csv_rows():
    merged, stats = _merge_road_records([road_record()], [])

    assert len(merged) == 1
    assert merged[0]["sync_key"].startswith("road_")
    assert stats["added"] == 1


def test_road_sync_updates_existing_auto_row_and_preserves_extra_columns():
    csv_row = road_record(title="交通取締予定（更新）")
    sheet_row = road_record(title="交通取締予定", actual_place="中区錦", sync_key=_road_sync_key(csv_row))

    merged, stats = _merge_road_records([csv_row], [sheet_row])

    assert merged[0]["title"] == "交通取締予定（更新）"
    assert merged[0]["actual_place"] == "中区錦"
    assert stats["updated"] == 1


def test_road_sync_preserves_manual_override_row_values():
    csv_row = road_record(title="OCR由来タイトル")
    sheet_row = road_record(
        title="人間が直したタイトル",
        sync_key=_road_sync_key(csv_row),
        manual_override="TRUE",
        memo="手動修正",
    )

    merged, stats = _merge_road_records([csv_row], [sheet_row])

    assert merged[0]["title"] == "人間が直したタイトル"
    assert merged[0]["memo"] == "手動修正"
    assert stats["protected"] == 1


def test_road_sync_keeps_secret_sheet_only_rows():
    secret_row = road_record(
        date="2026-07-13",
        title="秘密ルート取締情報",
        source="秘密ルート",
        source_detail="secret",
        manual_override="TRUE",
    )

    merged, stats = _merge_road_records([], [secret_row])

    assert len(merged) == 1
    assert merged[0]["title"] == "秘密ルート取締情報"
    assert stats["kept_sheet_only"] == 1


def test_road_sync_does_not_duplicate_same_csv_on_second_sync():
    csv_row = road_record()

    first, _first_stats = _merge_road_records([csv_row], [])
    second, stats = _merge_road_records([csv_row], first)

    assert len(second) == 1
    assert stats["updated"] == 1


def test_road_sync_rejects_seasonal_mismatch_and_removes_unprotected_sheet_row():
    bad_row = road_record(
        title=SPRING_TRAFFIC_SAFETY_TITLE,
        note="重点取締",
    )

    merged, stats = _merge_road_records([bad_row], [bad_row])

    assert merged == []
    assert stats["seasonal_rejected"] == 1
    assert stats["removed_invalid_sheet_rows"] == 1


class FakeExecute:
    def __init__(self, calls, name, kwargs):
        self.calls = calls
        self.name = name
        self.kwargs = kwargs

    def execute(self):
        self.calls.append((self.name, self.kwargs))
        return {}


class FakeValues:
    def __init__(self):
        self.calls = []

    def update(self, **kwargs):
        return FakeExecute(self.calls, "update", kwargs)

    def clear(self, **kwargs):
        return FakeExecute(self.calls, "clear", kwargs)


class FakeSpreadsheets:
    def __init__(self, values):
        self._values = values

    def values(self):
        return self._values


class FakeService:
    def __init__(self):
        self.values_api = FakeValues()

    def spreadsheets(self):
        return FakeSpreadsheets(self.values_api)


def test_road_sheet_write_does_not_clear_whole_sheet():
    service = FakeService()
    values = [ROAD_COLUMNS, ["" for _column in ROAD_COLUMNS]]

    _write_road_sheet_values(service, "sheet-id", "道路情報", values, previous_row_count=5)

    clear_calls = [kwargs for name, kwargs in service.values_api.calls if name == "clear"]
    assert clear_calls
    assert clear_calls[0]["range"] != "道路情報"
    assert clear_calls[0]["range"].startswith("道路情報!A3:")
