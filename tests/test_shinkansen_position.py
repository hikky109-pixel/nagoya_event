import json
from datetime import datetime, timezone

from tools.railway.analyze_shinkansen_position import build_summary, extract_trains, summary_to_yaml
from tools.railway.fetch_shinkansen_position import build_snapshot, save_snapshot


def sample_common():
    return {
        "constant": {
            "station": {"1": "東京", "2": "品川", "10": "名古屋", "11": "岐阜羽島"},
            "stationOrder": ["1", "2", "10", "11"],
            "train": {"6": "のぞみ", "2": "こだま"},
        }
    }


def sample_payload():
    return {
        "trainLocationInfo": {
            "datetime": 1783632313,
            "atStation": {
                "bounds": {
                    "1": [{"station": "10", "trains": [{"track": 15, "train": "6", "trainNumber": "288", "delay": 12, "sot": True}]}],
                    "2": [{"station": "1", "trains": [{"track": 18, "train": "6", "trainNumber": "5", "delay": 0}]}],
                }
            },
            "betweenStation": {
                "bounds": {
                    "1": [{"station": "10", "trains": [{"train": "2", "trainNumber": "800", "delay": 3}]}],
                    "2": [{"station": "10", "trains": [{"train": "6", "trainNumber": "99", "delay": 0}]}],
                }
            },
        }
    }


def test_extract_trains_normalizes_delay_direction_and_position():
    snapshot = build_snapshot(
        train_location=sample_payload(),
        common=sample_common(),
        fetched_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
    )

    trains = extract_trains(snapshot)

    assert len(trains) == 4
    assert trains[0]["train_no"] == "のぞみ288"
    assert trains[0]["direction"] == "up"
    assert trains[0]["position"] == "名古屋 15番線"
    assert trains[0]["delay_min"] == 12
    assert trains[2]["position"] == "名古屋→品川"


def test_build_summary_extracts_max_delay_and_delayed_trains():
    snapshot = build_snapshot(train_location=sample_payload(), common=sample_common())

    summary = build_summary(snapshot)

    assert summary["source"] == "shinkansen_position"
    assert summary["line"] == "tokaido_shinkansen"
    assert summary["total_trains"] == 4
    assert summary["max_delay_min"] == 12
    assert summary["delayed_trains"] == [
        {"train_no": "のぞみ288", "direction": "up", "delay_min": 12, "position": "名古屋 15番線"},
        {"train_no": "こだま800", "direction": "up", "delay_min": 3, "position": "名古屋→品川"},
    ]


def test_summary_to_yaml_outputs_gemma_candidate():
    summary = {
        "source": "shinkansen_position",
        "line": "tokaido_sanyo_shinkansen",
        "max_delay_min": 20,
        "delayed_trains": [{"train_no": "のぞみ1", "direction": "down", "delay_min": 10, "position": "名古屋付近"}],
    }

    text = summary_to_yaml(summary)

    assert "source: shinkansen_position" in text
    assert '- train_no: "のぞみ1"' in text
    assert '  position: "名古屋付近"' in text


def test_analyzer_tolerates_missing_structure():
    summary = build_summary({"payload": {"unexpected": True}, "common": {}})

    assert summary["total_trains"] == 0
    assert summary["max_delay_min"] == 0
    assert summary["delayed_trains"] == []


def test_save_snapshot_uses_timestamped_filename(tmp_path):
    snapshot = build_snapshot(
        train_location=sample_payload(),
        common=sample_common(),
        fetched_at=datetime(2026, 7, 10, 1, 2, 3, tzinfo=timezone.utc),
    )

    path = save_snapshot(snapshot, tmp_path)

    assert path.name == "20260710_010203_shinkansen_position.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["payload"]["trainLocationInfo"]["datetime"] == 1783632313
