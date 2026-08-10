from datetime import date

import pytest

import main
import tools.event.aichi_nagoya_2026_bot as asia
import config
import scrapers.utils.google_sheet_events as sheet_events


def asia_event(**overrides):
    event = {
        "date": "2026-09-19",
        "time": "18:00:00",
        "end_time": "20:00:00",
        "venue": "パロマ瑞穂スタジアム",
        "event_name": "開会式",
        "session_info": "セレモニー",
        "availability_status": "SOLD_OUT",
    }
    event.update(overrides)
    return event


def test_asia_render_uses_seven_columns_and_japanese_ticket_status():
    text = asia.render_notice_item(asia_event())
    assert "📢 18:00〜20:00" in text
    assert "📍 パロマ瑞穂スタジアム" in text
    assert "🎺 開会式" in text
    assert "📝 セレモニー" in text
    assert "🎫 チケット：予定枚数終了" in text


@pytest.mark.parametrize(
    ("status", "label"),
    [("BUY", "販売中"), ("LIMITED", "残席わずか"), ("SOLD_OUT", "予定枚数終了")],
)
def test_ticket_status_mapping(status, label):
    assert f"🎫 チケット：{label}" in asia.render_notice_item(
        asia_event(availability_status=status)
    )


def test_unknown_ticket_status_is_kept_and_logged(caplog):
    text = asia.render_notice_item(asia_event(availability_status="WAITING"))
    assert "🎫 チケット：WAITING" in text
    assert "asia_ticket_status_unknown=WAITING" in caplog.text


def test_sold_out_event_is_not_filtered(monkeypatch):
    monkeypatch.setattr(
        asia,
        "load_asia_operational_google_sheet_events",
        lambda: [asia_event(availability_status="SOLD_OUT")],
    )
    events = asia.load_notice_events(date(2026, 9, 19))
    assert len(events) == 1
    assert events[0]["availability_status"] == "SOLD_OUT"


def test_opening_and_closing_are_both_loaded(monkeypatch):
    monkeypatch.setattr(
        asia,
        "load_asia_operational_google_sheet_events",
        lambda: [
            asia_event(),
            asia_event(
                date="2026-10-04",
                time="18:00:00",
                end_time="19:30:00",
                event_name="閉会式",
            ),
        ],
    )
    assert asia.load_notice_events(date(2026, 9, 19))[0]["event_name"] == "開会式"
    assert asia.load_notice_events(date(2026, 10, 4))[0]["event_name"] == "閉会式"


def test_opening_force_embed_is_one_record_and_has_required_footer():
    embed = asia.build_embed([asia_event()], date(2026, 9, 19), test_mode=True)
    assert "テスト投稿" in embed["title"]
    assert "🏟️ 1件" in embed["description"]
    assert embed["footer"]["text"] == asia.ASIA_TICKET_FOOTER


def test_opening_force_mode_rejects_multiple_or_non_opening_events():
    with pytest.raises(ValueError, match="1件だけ"):
        asia.build_embed([asia_event(), asia_event()], date(2026, 9, 19), test_mode=True)
    with pytest.raises(ValueError, match="1件だけ"):
        asia.build_embed(
            [asia_event(event_name="バスケットボール")],
            date(2026, 9, 19),
            test_mode=True,
        )


def test_long_session_info_is_only_trimmed_in_display():
    original = "長文" * 1000
    event = asia_event(session_info=original)
    rendered = asia.render_notice_item(event)
    assert len(rendered) < len(original)
    assert event["session_info"] == original


def test_asia_embed_footer_coexists_with_existing_footer():
    embed = {"footer": {"text": "既存footer"}}
    asia.combine_embed_footer(embed, asia.ASIA_TICKET_FOOTER)
    assert embed["footer"]["text"].startswith("既存footer｜")
    assert asia.ASIA_TICKET_FOOTER in embed["footer"]["text"]


def test_opening_send_uses_wait_readback_and_verifies_footer():
    calls = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"embeds": [{"footer": {"text": asia.ASIA_TICKET_FOOTER}}]}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    assert asia.send_events(
        [asia_event()],
        date(2026, 9, 19),
        test_mode=True,
        webhook_url="https://example.test/webhook",
        http_post=post,
    )
    assert calls[0][0].endswith("?wait=true")
    assert calls[0][1]["json"]["embeds"][0]["footer"]["text"] == asia.ASIA_TICKET_FOOTER


def test_feature_flag_disables_read_render_footer_and_test_path(monkeypatch):
    monkeypatch.setattr(asia, "ENABLE_AICHI_NAGOYA_2026", False)
    assert asia.send_daily_notice(date(2026, 9, 19)) is False
    with pytest.raises(RuntimeError, match="大会専用機能は無効"):
        asia.read_operational_csv()
    with pytest.raises(RuntimeError, match="大会専用機能は無効"):
        asia.render_notice_item(asia_event())
    with pytest.raises(RuntimeError, match="大会専用機能は無効"):
        asia.opening_test_event()


def test_feature_flag_skips_ajipara_sheet(monkeypatch):
    loaded = []
    monkeypatch.setattr(config, "ENABLE_AICHI_NAGOYA_2026", False)
    monkeypatch.setattr(sheet_events, "EVENT_SHEET_SOURCES", ["ajipara", "spot"])
    monkeypatch.setattr(
        sheet_events,
        "load_google_sheet_csv",
        lambda url, source: loaded.append(source) or [],
    )
    sheet_events.load_all_google_sheet_events()
    assert loaded == ["spot"]


def test_feature_flag_skips_ajipara_manual_csv(monkeypatch):
    loaded = []
    monkeypatch.setattr(main, "aichi_nagoya_2026_enabled", lambda: False)
    monkeypatch.setattr(
        main,
        "load_csv_events",
        lambda filename, source: loaded.append(filename) or [],
    )
    main.load_non_road_manual_csv_events()
    assert "ajipara.csv" not in loaded


def test_other_notice_renderer_is_unchanged():
    rendered = main.render_cruise_notice_item(
        {"title": "入港", "venue": "名古屋港", "time": "09:00", "end_time": ""}
    )
    assert rendered == "🚢 入港\n📍 名古屋港\n🕐 09:00〜"
