import csv

from scrapers.shiki import dedupe_events, merge_existing_rows, parse_shiki_events, write_shiki_csv


def test_parse_shiki_events_from_calendar_ids():
    html = """
    <html><body>
      <div id="mor20260720">
        <span class="cal-time">13:00</span>
        <span class="cal-mark">○</span>
      </div>
    </body></html>
    """

    events = parse_shiki_events(html, today="2026-07-01")

    assert len(events) == 1
    assert events[0]["date"] == "2026-07-20"
    assert events[0]["time"] == "13:00"
    assert events[0]["end_time"] == "15:40"
    assert events[0]["availability_mark"] == "○"


def test_dedupe_events_merges_missing_fields():
    events = [
        {"source": "劇団四季", "venue": "ＭＴＧ名古屋四季劇場", "title": "オペラ座の怪人", "date": "2026-07-20", "time": "13:00"},
        {
            "source": "劇団四季",
            "venue": "ＭＴＧ名古屋四季劇場",
            "title": "オペラ座の怪人",
            "date": "2026-07-20",
            "time": "13:00",
            "availability_mark": "○",
        },
    ]

    deduped = dedupe_events(events)

    assert len(deduped) == 1
    assert deduped[0]["availability_mark"] == "○"


def test_merge_existing_rows_preserves_manual_rows():
    scraped = [
        {
            "date": "2026-07-20",
            "time": "13:00",
            "end_time": "15:40",
            "venue": "ＭＴＧ名古屋四季劇場",
            "title": "オペラ座の怪人",
            "source": "劇団四季",
            "status": "confirmed",
            "url": "https://www.shiki.jp/stage_schedule/?aj=0&rid=0019&ggc=0977",
        }
    ]
    existing = [
        {
            "date": "2026-07-21",
            "time": "18:30",
            "venue": "ＭＴＧ名古屋四季劇場",
            "title": "手動補完",
            "source": "劇団四季",
            "status": "manual",
        }
    ]

    merged = merge_existing_rows(scraped, existing, today="2026-07-01")

    assert [row["title"] for row in merged] == ["オペラ座の怪人", "手動補完"]
    assert merged[1]["status"] == "manual"


def test_write_shiki_csv_uses_tmp_path_without_network(tmp_path):
    output_path = tmp_path / "shiki.csv"
    events = parse_shiki_events(
        """
        <html><body>
          <div id="eve20260720">
            <span class="cal-time">17:30</span>
            <span class="cal-mark">△</span>
          </div>
        </body></html>
        """,
        today="2026-07-01",
    )

    write_shiki_csv(events, output_path, today="2026-07-01")

    with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert len(rows) == 1
    assert rows[0]["date"] == "2026-07-20"
    assert rows[0]["time"] == "17:30"
