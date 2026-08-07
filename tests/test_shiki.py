import csv
from datetime import datetime, timezone
import json
from pathlib import Path

import scrapers.shiki as shiki
from scrapers.shiki import dedupe_events, merge_existing_rows, parse_shiki_events, write_shiki_csv
from tools.health.build_scraper_dashboard import evaluate_dashboard


FIXTURES = Path(__file__).parent / "fixtures"


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
          <div id="mor20260721">
            <span class="cal-time">13:00</span>
            <span class="cal-mark">○</span>
          </div>
        </body></html>
        """,
        today="2026-07-01",
    )

    write_shiki_csv(events, output_path, today="2026-07-01")

    with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert len(rows) == 2
    assert rows[0]["date"] == "2026-07-20"
    assert rows[0]["time"] == "17:30"


def test_parse_current_api_fixture_keeps_day_night_private_and_dedupes():
    payload = json.loads(
        (FIXTURES / "shiki_calendar_api_202608.json").read_text(encoding="utf-8")
    )

    events, metrics, skips = shiki._api_event_candidates(
        [("202608", payload)],
        today=shiki.date(2026, 8, 8),
        requested_month=None,
        title=shiki.TITLE,
        venue=shiki.VENUE,
    )

    assert len(events) == 4
    assert [(event["date"], event["time"]) for event in events] == [
        ("2026-08-20", "13:30"),
        ("2026-08-22", "13:00"),
        ("2026-08-22", "17:30"),
        ("2026-08-23", ""),
    ]
    assert events[-1]["note"] == "貸切公演"
    assert events[0]["venue"] == "ＭＴＧ名古屋四季劇場"
    assert metrics["raw_candidates"] == 6
    assert metrics["detail_urls"] == 0
    assert metrics["filtered_events"] == 4
    assert skips == []


class FakeResponse:
    def __init__(self, status_code, text, url):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url
        self.history = []

    def json(self):
        return json.loads(self.text)


def test_one_event_api_result_is_rejected_and_debug_is_saved(monkeypatch, tmp_path):
    stage_html = (FIXTURES / "shiki_stage_page.html").read_text(encoding="utf-8")
    one_event = {
        "results": {
            "calendar": [
                {
                    "id": "20260820",
                    "koen_day": "20260820",
                    "daily_disp_flg": "0",
                    "mor": {"time": "13:30", "dispstr": "", "seat_rest": "seat"},
                    "aft": {"time": "", "dispstr": "", "seat_rest": ""},
                }
            ]
        }
    }

    def fake_fetch(url, *, params=None):
        if url == shiki.URL:
            return FakeResponse(200, stage_html, url)
        if url == shiki.MONTHS_API_URL:
            return FakeResponse(
                200,
                json.dumps({"results": [{"id": "202608", "past": "0"}]}),
                url,
            )
        return FakeResponse(200, json.dumps(one_event), url)

    monkeypatch.setattr(shiki, "_fetch", fake_fetch)
    monkeypatch.setattr(shiki, "DEBUG_DIR", tmp_path)
    monkeypatch.setattr(shiki, "_shiki_health_messages", lambda events, calendars: [])

    events, messages = shiki.scrape_shiki_with_health(None, today="2026-08-08")

    assert events == []
    assert any("invalid result" in message for message in messages)
    assert len(list(tmp_path.glob("*.html"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_write_blocks_zero_or_large_drop_and_preserves_existing_file(tmp_path):
    output = tmp_path / "shiki.csv"
    existing = parse_shiki_events(
        """
        <div id="mor20260820"><span class="cal-time">13:30</span></div>
        <div id="aft20260820"><span class="cal-time">18:30</span></div>
        <div id="mor20260821"><span class="cal-time">13:30</span></div>
        <div id="aft20260821"><span class="cal-time">18:30</span></div>
        """,
        today="2026-08-08",
    )
    assert write_shiki_csv(existing, output, today="2026-08-08") is True
    before = output.read_bytes()

    assert write_shiki_csv([], output, today="2026-08-08") is False
    assert output.read_bytes() == before
    assert write_shiki_csv(existing[:1], output, today="2026-08-08") is False
    assert output.read_bytes() == before


def test_dashboard_keeps_fifty_percent_drop_warning():
    previous = {
        "scrapers": {"shiki": {"counts": {"events": {"count": 354}}}}
    }
    snapshots = {
        "shiki": {
            "updated_at": "2026-08-08T06:00:00+09:00",
            "counts": {"events": 1},
            "hashes": {},
            "sequences": {},
        }
    }

    dashboard = evaluate_dashboard(
        snapshots, previous, datetime(2026, 8, 8, tzinfo=timezone.utc)
    )

    assert "shiki: events 前回比50%以上減少 previous=354 current=1" in dashboard[
        "warnings"
    ]
