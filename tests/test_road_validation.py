from pathlib import Path

import main
from main import load_road_events
from scrapers.road_pdf import classify_focus_text
from scrapers.utils.road_validation import SPRING_TRAFFIC_SAFETY_TITLE, is_road_event_seasonally_valid


def test_rejects_spring_campaign_outside_period_without_replacing_to_summer(capsys):
    title = classify_focus_text(
        "春の全国交通安全運動期間中の交通指導取締り",
        event_dates=["2026-07-12"],
        year=2026,
    )

    assert title is None
    assert "夏" not in (title or "")
    assert "road_ocr: rejected seasonal mismatch" in capsys.readouterr().out


def test_accepts_spring_campaign_inside_period():
    title = classify_focus_text(
        "春の全国交通安全運動期間中の交通指導取締り 4月6日〜4月15日",
        event_dates=["2026-04-10"],
        year=2026,
    )

    assert title == SPRING_TRAFFIC_SAFETY_TITLE
    assert is_road_event_seasonally_valid({"date": "2026-04-10", "title": title})


def test_load_road_events_filters_existing_invalid_csv_rows(tmp_path: Path):
    csv_path = tmp_path / "road.csv"
    csv_path.write_text(
        "\n".join(
            [
                "date,time,end_time,venue,title,source,status,note,url",
                f"2026-07-12,未定,,愛知県内,{SPRING_TRAFFIC_SAFETY_TITLE},愛知県警,confirmed,重点取締,http://example.invalid",
                "2026-07-12,未定,,中区,交通取締予定,愛知県警,confirmed,取締,http://example.invalid",
            ]
        ),
        encoding="utf-8",
    )

    events = load_road_events("2026-07-12", csv_path=csv_path)

    assert [event["title"] for event in events] == ["交通取締予定"]


def test_load_road_events_prefers_google_sheet_for_default_source(monkeypatch):
    monkeypatch.setattr(
        main,
        "load_road_google_sheet_events",
        lambda: [
            {
                "date": "2026-07-12",
                "time": "未定",
                "end_time": "",
                "venue": "秘密地点",
                "title": "秘密ルート取締情報",
                "source": "秘密ルート",
                "status": "manual",
                "note": "重点取締",
                "url": "",
            }
        ],
    )

    events = load_road_events("2026-07-12")

    assert [event["title"] for event in events] == ["秘密ルート取締情報"]
