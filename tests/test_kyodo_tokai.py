from datetime import datetime

import scrapers.kyodo_tokai as kyodo


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
        result = self.results[self.index]
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
        lambda soup: [f"selector_count={len(soup.select(kyodo.EVENT_SELECTOR))}"],
    )


def test_retries_zero_selector_then_recovers(monkeypatch):
    _disable_health_state(monkeypatch)
    page = FakePage(
        [
            {"status": 200, "html": "<html><body>temporary</body></html>"},
            {"status": 200, "html": VALID_HTML},
        ]
    )

    events, messages = kyodo.scrape_kyodo_tokai_with_health(
        page, datetime(2026, 7, 29)
    )

    assert len(events) == 1
    assert events[0]["venue"] == "Zepp Nagoya"
    assert any("fetch retried" in message for message in messages)
    assert not any("fetch diagnostics" in message for message in messages)


def test_saves_html_and_diagnostics_after_repeated_zero_selector(
    monkeypatch, tmp_path
):
    _disable_health_state(monkeypatch)
    monkeypatch.setattr(kyodo, "DEBUG_DIR", tmp_path)
    page = FakePage(
        [
            {"status": 200, "html": "<html><body>temporary 1</body></html>"},
            {"status": 503, "html": "<html><body>maintenance</body></html>"},
        ]
    )

    events, messages = kyodo.scrape_kyodo_tokai_with_health(
        page, datetime(2026, 7, 29)
    )

    assert events == []
    assert len(list(tmp_path.glob("*.html"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1
    warning = next(message for message in messages if "fetch diagnostics" in message)
    assert "status=503" in warning
    assert "response_length=" in warning
    assert "selector_count=0" in warning
    assert "saved_html=" in warning
