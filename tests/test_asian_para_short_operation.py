from datetime import date
from pathlib import Path

import pytest

import config
import main
from scrapers.utils import google_sheet_events as sheets
from tools.event import aichi_nagoya_2026_bot as bot
from tools.event.build_asian_para_2026_sessions import COLUMNS, extract_sessions


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def para_operation(monkeypatch):
    monkeypatch.setattr(bot, "ASIAN_PARA_SHORT_OPERATION", True)
    monkeypatch.setattr(config, "ASIAN_PARA_SHORT_OPERATION", True)
    monkeypatch.setattr(bot, "ENABLE_AICHI_NAGOYA_2026", True)


def test_pinned_pdf_and_csv_preserve_all_competition_sessions():
    rows, audit = extract_sessions(ROOT / "data/asian_para_2026/raw/session_schedule_20261002.pdf")
    saved = bot.read_operational_csv(ROOT / bot.PARA_CSV_PATH)
    assert rows == saved
    assert len(rows) == 151
    assert len({r["event_name"] for r in rows}) == 19
    assert all(list(r) == COLUMNS and r["availability_status"] == "" for r in rows)
    assert {c["color"] for c in audit["cells"]} == {"competition_day", "gold_medal_day"}
    assert {r["date"] for r in rows} == {f"2026-10-{d:02d}" for d in [16, 17, 19, 20, 21, 22, 23, 24]}
    assert not any(r["event_name"] in {"開会式", "閉会式"} for r in rows)


@pytest.mark.parametrize("status", ["", None, "BUY", "SOLD_OUT", "UNKNOWN"])
def test_notice_has_existing_fields_and_no_ticket_information(status):
    row = bot.read_operational_csv(ROOT / bot.PARA_CSV_PATH)[0]
    row["availability_status"] = status
    content = "\n".join(bot.build_messages([row], date(2026, 10, 16)))
    assert content.startswith("🏟️ アジアパラ大会\n\n10月16日（金）")
    for text in ["🏟️ 本日 1件", row["venue"], row["event_name"], row["session_info"], f"{row['time']}〜{row['end_time']}"]:
        assert text in content
    for text in ["チケット", "🎟️", bot.ASIA_TICKET_FOOTER, "SOLD_OUT", "BUY", "UNKNOWN"]:
        assert text not in content


def test_six_am_entry_uses_same_sheet_and_never_posts_in_dry_run(monkeypatch, capsys):
    rows = bot.read_operational_csv(ROOT / bot.PARA_CSV_PATH)
    calls = []
    monkeypatch.setattr(bot, "load_asia_operational_google_sheet_events", lambda: calls.append("existing_sheet") or rows)
    monkeypatch.setattr(main, "DRY_RUN", True)
    monkeypatch.setattr(bot, "send_events", lambda *a, **k: pytest.fail("Discord send attempted"))
    assert main.send_asia_info(date(2026, 10, 19)) is False
    content = capsys.readouterr().out
    assert calls == ["existing_sheet"]
    assert "アジアパラ大会" in content
    assert "チケット" not in content
    assert "2026-09" not in content


def test_sheet_failure_uses_para_csv_not_previous_games(monkeypatch):
    def fail():
        raise ValueError("fixture sheet unavailable")
    monkeypatch.setattr(bot, "load_asia_operational_google_sheet_events", fail)
    monkeypatch.setattr(bot, "PARA_CSV_PATH", ROOT / bot.PARA_CSV_PATH)
    rows = bot.load_notice_events(date(2026, 10, 19))
    assert rows and all(r["date"] == "2026-10-19" for r in rows)
    assert all(r["availability_status"] == "" for r in rows)


def test_empty_status_survives_existing_sheet_reader(monkeypatch):
    class Response:
        text = ",".join(COLUMNS) + "\n2026-10-19,09:00,12:00,会場,競技,女子 / 決勝,\n"
        def raise_for_status(self):
            pass
    monkeypatch.setattr(sheets.requests, "get", lambda *a, **k: Response())
    rows = sheets.load_asia_operational_google_sheet_events()
    assert rows[0]["availability_status"] == ""
    assert "チケット" not in bot.build_messages(rows, date(2026, 10, 19))[0]


def test_all_days_fit_discord_limit():
    rows = bot.read_operational_csv(ROOT / bot.PARA_CSV_PATH)
    for day in sorted({r["date"] for r in rows}):
        selected = [r for r in rows if r["date"] == day]
        messages = bot.build_messages(selected, day)
        assert all(len(m) <= 2000 and "チケット" not in m for m in messages)
        assert sum(m.count("🎺") for m in messages) == len(selected)


def test_legacy_ajipara_sources_are_skipped(monkeypatch):
    loaded = []
    monkeypatch.setattr(config, "ENABLE_AICHI_NAGOYA_2026", True)
    monkeypatch.setattr(sheets, "EVENT_SHEET_SOURCES", ["ajipara", "spot"])
    monkeypatch.setattr(sheets, "load_google_sheet_csv", lambda url, source: loaded.append(source) or [])
    sheets.load_all_google_sheet_events()
    assert loaded == ["spot"]
    loaded.clear()
    monkeypatch.setattr(main, "load_csv_events", lambda name, source: loaded.append(name) or [])
    main.load_non_road_manual_csv_events()
    assert "ajipara.csv" not in loaded


def test_previous_opening_test_is_blocked():
    with pytest.raises(RuntimeError, match="旧アジア大会開会式テスト"):
        bot.opening_test_event()
