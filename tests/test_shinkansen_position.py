import json
from datetime import datetime, timezone

from tools.railway.analyze_shinkansen_position import build_summary, extract_trains, summary_to_yaml
from tools.railway.fetch_shinkansen_position import build_snapshot, save_snapshot


def sample_common():
    return {
        "constant": {
            "station": {"1": "東京", "2": "品川", "10": "名古屋", "11": "岐阜羽島", "15": "新大阪", "16": "新神戸"},
            "stationOrder": ["1", "2", "10", "11", "15", "16"],
            "stationTokaido": ["1", "2", "10", "11", "15"],
            "train": {"6": "のぞみ", "2": "こだま", "1": "ひかり"},
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
    assert summary["tokaido_trains"] == 4
    assert summary["max_delay_min"] == 12
    assert summary["severity_alerts"] == []
    assert summary["terminal_connection_risks"] == []
    assert summary["delayed_trains"] == [
        {"train_no": "のぞみ288", "direction": "up", "delay_min": 12, "position": "名古屋 15番線"},
        {"train_no": "こだま800", "direction": "up", "delay_min": 3, "position": "名古屋→品川"},
    ]


def test_summary_to_yaml_outputs_gemma_candidate():
    summary = {
        "source": "shinkansen_position",
        "line": "tokaido_sanyo_shinkansen",
        "max_delay_min": 20,
        "severity_alerts": [],
        "terminal_connection_risks": [],
        "delayed_trains": [{"train_no": "のぞみ1", "direction": "down", "delay_min": 10, "position": "名古屋付近"}],
        "ignored_trains": [],
    }

    text = summary_to_yaml(summary)

    assert "source: shinkansen_position" in text
    assert '- train_no: "のぞみ1"' in text
    assert '  position: "名古屋付近"' in text


def test_summary_detects_normal_delay_severity_and_terminal_connection_risks():
    payload = {
        "trainLocationInfo": {
            "datetime": 1783632313,
            "atStation": {
                "bounds": {
                    "2": [
                        {
                            "station": "10",
                            "trains": [
                                {"track": 16, "train": "6", "trainNumber": "549", "delay": 20},
                                {"track": 17, "train": "1", "trainNumber": "669", "delay": 10},
                                {"track": 18, "train": "6", "trainNumber": "99", "delay": 30},
                            ],
                        }
                    ],
                    "1": [{"station": "10", "trains": [{"track": 14, "train": "6", "trainNumber": "108", "delay": 40}]}],
                }
            },
            "betweenStation": {"bounds": {"1": [], "2": []}},
        }
    }
    snapshot = build_snapshot(train_location=payload, common=sample_common())

    summary = build_summary(snapshot)

    assert summary["max_delay_min"] == 40
    assert [(item["train_name"], item["train_number"], item["delay_min"]) for item in summary["severity_alerts"]] == [
        ("のぞみ", "99", 30),
        ("のぞみ", "108", 40),
    ]
    assert [(item["train_name"], item["train_number"], item["risk_area"]) for item in summary["terminal_connection_risks"]] == [
        ("のぞみ", "549", "名東方面"),
        ("ひかり", "669", "名東方面"),
        ("のぞみ", "108", "名東方面"),
    ]
    assert "名古屋23:49着想定" in summary["terminal_connection_risks"][1]["reason"]


def test_terminal_connection_risk_thresholds_are_train_specific():
    payload = {
        "trainLocationInfo": {
            "datetime": 1783632313,
            "atStation": {
                "bounds": {
                    "2": [
                        {
                            "station": "10",
                            "trains": [
                                {"track": 16, "train": "6", "trainNumber": "549", "delay": 19},
                                {"track": 17, "train": "1", "trainNumber": "669", "delay": 9},
                            ],
                        }
                    ],
                    "1": [{"station": "10", "trains": [{"track": 14, "train": "6", "trainNumber": "108", "delay": 39}]}],
                }
            },
            "betweenStation": {"bounds": {"1": [], "2": []}},
        }
    }
    snapshot = build_snapshot(train_location=payload, common=sample_common())

    summary = build_summary(snapshot)

    assert summary["terminal_connection_risks"] == []
    assert summary["severity_alerts"] == [
        {
            "train_name": "のぞみ",
            "train_number": "108",
            "direction": "up",
            "delay_min": 39,
            "position": "名古屋 14番線",
            "reason": "東海道新幹線区間で30分以上の遅延",
        }
    ]


def test_sanyo_section_is_ignored_for_summary_alerts():
    payload = {
        "trainLocationInfo": {
            "datetime": 1783632313,
            "atStation": {"bounds": {"2": [{"station": "16", "trains": [{"track": 1, "train": "6", "trainNumber": "549", "delay": 60}]}]}},
            "betweenStation": {"bounds": {"1": [], "2": []}},
        }
    }
    snapshot = build_snapshot(train_location=payload, common=sample_common())

    summary = build_summary(snapshot)

    assert summary["tokaido_trains"] == 0
    assert summary["max_delay_min"] == 0
    assert summary["severity_alerts"] == []
    assert summary["terminal_connection_risks"] == []
    assert summary["ignored_trains"] == [
        {
            "train_no": "のぞみ549",
            "direction": "down",
            "position": "新神戸 1番線",
            "delay_min": 60,
            "ignored_reason": "山陽区間のため対象外",
        }
    ]


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
