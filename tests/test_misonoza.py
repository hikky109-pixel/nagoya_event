import csv

from scrapers.misonoza import dedupe_events, normalize_misonoza_event, write_misonoza_csv


def test_dedupe_events_merges_missing_fields():
    events = [
        {
            "date": "2026/07/20",
            "time": "11:00",
            "venue": "御園座",
            "title": "テスト公演",
            "url": "https://example.invalid/show",
        },
        {
            "date": "2026/07/20",
            "time": "11:00",
            "venue": "御園座",
            "title": "テスト公演",
            "url": "https://example.invalid/show",
            "end_time": "14:00",
        },
    ]

    deduped = dedupe_events(events)

    assert len(deduped) == 1
    assert deduped[0]["end_time"] == "14:00"


def test_normalize_misonoza_event_converts_date_and_defaults():
    event = normalize_misonoza_event(
        {
            "date": "2026/07/20",
            "time": "11:00",
            "venue": "御園座",
            "title": "テスト公演",
            "url": "https://example.invalid/show",
        }
    )

    assert event["date"] == "2026-07-20"
    assert event["source"] == "lineup"
    assert event["status"] == "confirmed"


def test_write_misonoza_csv_preserves_manual_rows(tmp_path):
    output_path = tmp_path / "misonoza.csv"
    output_path.write_text(
        "\n".join(
            [
                "date,time,end_time,venue,title,source,status,note,url",
                "2026-07-21,13:00,,御園座,手動補完公演,lineup,manual,手動補完,https://example.invalid/manual",
            ]
        ),
        encoding="utf-8",
    )
    events = [
        {
            "date": "2026/07/20",
            "time": "11:00",
            "venue": "御園座",
            "title": "テスト公演",
            "source": "lineup",
            "url": "https://example.invalid/show",
        }
    ]

    write_misonoza_csv(events, str(output_path))

    with output_path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert [row["title"] for row in rows] == ["テスト公演", "手動補完公演"]
    assert rows[1]["status"] == "manual"
