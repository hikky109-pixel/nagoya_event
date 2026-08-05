from datetime import datetime
from pathlib import Path

import scrapers.kyodo_tokai as kyodo

FIXTURES = Path(__file__).parent / "fixtures"


VALID_HTML = """
<html><body><div class="eventlistbox">
<dl><dt><a class="alink">公演名</a></dt>
<dd>2026年07月29日 17:00 / 18:00 【会場名】 Zepp Nagoya 【料金】 1000円</dd>
</dl>
</div></body></html>
"""


class FakeResponse:
    def __init__(self, status):
        self.status = status


class FakePage:
    def __init__(self, results):
        self.results = list(results)
        self.index = -1
        self.url = ""

    def goto(self, url, **_kwargs):
        self.index += 1
        result = self.results[min(self.index, len(self.results) - 1)]
        self.url = result.get("url", url)
        if "error" in result:
            raise result["error"]
        return FakeResponse(result["status"])

    def content(self):
        return self.results[self.index].get("html", "")


def _disable_health_state(monkeypatch):
    monkeypatch.setattr(
        kyodo,
        "_kyodo_health_messages",
        lambda soup: [f"selector_count={len(soup.select(kyodo.CALENDAR_SELECTOR))}"],
    )


def test_retries_zero_selector_then_recovers(monkeypatch):
    page = FakePage(
        [
            {"status": 200, "html": "<html><body>temporary</body></html>"},
            {"status": 200, "html": VALID_HTML},
        ]
    )

    soup, attempts, debug_paths = kyodo._fetch_page(
        page, kyodo.URL, kyodo.EVENT_SELECTOR, "events"
    )

    assert len(soup.select(kyodo.EVENT_SELECTOR)) == 1
    assert len(attempts) == 2
    assert debug_paths is None


def test_saves_html_and_diagnostics_after_repeated_zero_selector(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(kyodo, "DEBUG_DIR", tmp_path)
    page = FakePage(
        [
            {"status": 200, "html": "<html><body>temporary 1</body></html>"},
            {"status": 503, "html": "<html><body>maintenance</body></html>"},
        ]
    )

    _soup, attempts, debug_paths = kyodo._fetch_page(
        page, kyodo.URL, kyodo.EVENT_SELECTOR, "events"
    )
    messages = kyodo._diagnostic_messages(attempts, debug_paths, "events")

    assert len(list(tmp_path.glob("*.html"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1
    warning = next(message for message in messages if "fetch diagnostics" in message)
    assert "status=503" in warning
    assert "response_length=" in warning
    assert "selector_count=0" in warning
    assert "saved_html=" in warning


def test_lv17_9_1_calendar_and_details_add_august_5_events(
    monkeypatch, caplog
):
    _disable_health_state(monkeypatch)
    fixture = (FIXTURES / "kyodo_tokai_3587_case.html").read_text(encoding="utf-8")
    page = FakePage(
        [
            {"status": 200, "html": fixture},
            {
                "status": 200,
                "html": (FIXTURES / "kyodo_tokai_3588_detail.html").read_text(
                    encoding="utf-8"
                ),
            },
            {
                "status": 200,
                "html": (FIXTURES / "kyodo_tokai_3589_detail.html").read_text(
                    encoding="utf-8"
                ),
            },
        ]
    )

    with caplog.at_level("INFO"):
        events, _messages = kyodo.scrape_kyodo_tokai_with_health(
            page, datetime(2026, 8, 5)
        )

    assert [event["time"] for event in events] == ["12:00", "18:00"]
    assert all(event["venue"] == "Zepp Nagoya" for event in events)
    assert all(event["title"] == "すにすて - Sneaker Step Prod.STPR MUSIC" for event in events)
    assert "kyodo_event_found" in caplog.text
    assert "kyodo_event_skipped_reason reason=date_mismatch" in caplog.text
    assert "kyodo_event_parsed" in caplog.text
    assert "kyodo_event_added" in caplog.text
    assert "kyodo_calendar_candidates month=2026-08 count=3" in caplog.text


def test_calendar_month_url_and_candidates_cover_multiple_same_day_events():
    fixture = (FIXTURES / "kyodo_tokai_3587_case.html").read_text(encoding="utf-8")
    candidates, actual_month = kyodo._parse_calendar_candidates(
        kyodo.BeautifulSoup(fixture, "html.parser"), datetime(2026, 8, 5)
    )

    assert kyodo._calendar_url(datetime(2026, 7, 5)).endswith("/calendor/202607")
    assert kyodo._calendar_url(datetime(2026, 8, 5)).endswith("/calendor/202608")
    assert kyodo._calendar_url(datetime(2026, 9, 5)).endswith("/calendor/202609")
    assert actual_month == "2026/08"
    assert [candidate["url"].rsplit("/", 1)[-1] for candidate in candidates] == [
        "3587",
        "3588",
        "3589",
    ]
    assert [candidate["date"].day for candidate in candidates] == [4, 5, 5]


def test_falls_back_to_alphabetical_pages_when_calendar_fetch_fails(
    monkeypatch, tmp_path
):
    _disable_health_state(monkeypatch)
    monkeypatch.setattr(kyodo, "DEBUG_DIR", tmp_path)
    monkeypatch.setattr(kyodo, "INDEX_URLS", [kyodo.URL])
    page = FakePage(
        [
            {"status": 503, "html": "<html>maintenance</html>"},
            {"status": 503, "html": "<html>maintenance</html>"},
            {"status": 200, "html": VALID_HTML},
        ]
    )

    events, messages = kyodo.scrape_kyodo_tokai_with_health(
        page, datetime(2026, 7, 29)
    )

    assert len(events) == 1
    assert events[0]["venue"] == "Zepp Nagoya"
    assert any("page=calendar" in message for message in messages)
