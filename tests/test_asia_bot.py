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


def sheet_response(csv_text):
    class Response:
        text = csv_text
        encoding = None

        @staticmethod
        def raise_for_status():
            return None

    return Response()


def test_asia_operational_sheet_uses_export_gid_url_and_reads_seven_columns(monkeypatch):
    calls = []
    csv_text = (
        "date,time,end_time,venue,event_name,session_info,availability_status\n"
        "2026-09-03,10:00:00,12:00:00,テスト会場,当日ダミー,営業確認,BUY\n"
    )
    monkeypatch.setattr(
        sheet_events.requests,
        "get",
        lambda url, timeout: calls.append((url, timeout)) or sheet_response(csv_text),
    )

    events = sheet_events.load_asia_operational_google_sheet_events()

    assert sheet_events.ASIA_OPERATIONAL_SHEET_URL.endswith(
        "/export?format=csv&gid=272979110"
    )
    assert calls == [(sheet_events.ASIA_OPERATIONAL_SHEET_URL, 15)]
    assert events == [asia_event(
        date="2026-09-03",
        time="10:00:00",
        end_time="12:00:00",
        venue="テスト会場",
        event_name="当日ダミー",
        session_info="営業確認",
        availability_status="BUY",
    )]


def test_asia_operational_sheet_rejects_gviz_style_broken_header(monkeypatch):
    broken_csv = (
        "date,time,end_time,venue,event_name,session_info,availability_status,余剰列\n"
        "2026-09-03,10:00:00,12:00:00,テスト会場,当日ダミー,営業確認,BUY,崩れ\n"
    )
    monkeypatch.setattr(
        sheet_events.requests,
        "get",
        lambda url, timeout: sheet_response(broken_csv),
    )

    with pytest.raises(ValueError, match="アジア大会シート列不一致"):
        sheet_events.load_asia_operational_google_sheet_events()


def test_asia_sheet_fetch_failure_falls_back_to_operational_csv(monkeypatch, tmp_path):
    fallback = tmp_path / "asia.csv"
    fallback.write_text(
        "date,time,end_time,venue,event_name,session_info,availability_status\n"
        "2026-09-03,10:00:00,12:00:00,CSV会場,CSV fallback,営業確認,LIMITED\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(asia, "ASIA_CSV_PATH", fallback)
    monkeypatch.setattr(
        asia,
        "load_asia_operational_google_sheet_events",
        lambda: (_ for _ in ()).throw(RuntimeError("sheet unavailable")),
    )

    events = asia.load_notice_events(date(2026, 9, 3), csv_path=fallback)

    assert len(events) == 1
    assert events[0]["event_name"] == "CSV fallback"


def test_sheet_only_today_dummy_is_selected(monkeypatch):
    monkeypatch.setattr(
        asia,
        "load_asia_operational_google_sheet_events",
        lambda: [
            asia_event(date="2026-09-02", event_name="前日競技"),
            asia_event(date="2026-09-03", event_name="当日ダミー", availability_status="BUY"),
        ],
    )

    events = asia.load_notice_events(date(2026, 9, 3))

    assert [event["event_name"] for event in events] == ["当日ダミー"]


def test_asia_render_uses_seven_columns_and_japanese_ticket_status():
    text = asia.render_notice_item(asia_event())
    assert "📢 18:00〜20:00" in text
    assert "📍 パロマ瑞穂スタジアム" in text
    assert "🎺 開会式" in text
    assert "📝 セレモニー" in text
    assert "🎟️ チケット：予定枚数終了" in text


@pytest.mark.parametrize(
    ("status", "label"),
    [("BUY", "販売中"), ("LIMITED", "残席わずか"), ("SOLD_OUT", "予定枚数終了")],
)
def test_ticket_status_mapping(status, label):
    assert f"🎟️ チケット：{label}" in asia.render_notice_item(
        asia_event(availability_status=status)
    )


def test_unknown_ticket_status_is_kept_and_logged(caplog):
    text = asia.render_notice_item(asia_event(availability_status="WAITING"))
    assert "🎟️ チケット：WAITING" in text
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


def test_plain_text_message_has_requested_date_count_and_footer():
    messages = asia.build_messages(
        [asia_event(date="2026-09-03")], date(2026, 9, 3)
    )
    assert len(messages) == 1
    content = messages[0]
    assert content.startswith("🏟️ アジア大会情報\n\n09月03日（木）")
    assert "🏟️ 本日 1件" in content
    assert "📢 18:00〜20:00" in content
    assert content.endswith(asia.ASIA_TICKET_FOOTER)


def test_opening_force_mode_rejects_multiple_or_non_opening_events():
    with pytest.raises(ValueError, match="1件だけ"):
        asia.build_messages([asia_event(), asia_event()], date(2026, 9, 19), test_mode=True)
    with pytest.raises(ValueError, match="1件だけ"):
        asia.build_messages(
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


def test_start_time_only_and_optional_session_info():
    with_info = asia.render_notice_item(
        asia_event(time="18:00:00", end_time="", session_info="セレモニー")
    )
    without_info = asia.render_notice_item(
        asia_event(time="18:00:00", end_time="", session_info="")
    )
    assert "📢 18:00〜" in with_info
    assert "📝 セレモニー" in with_info
    assert "📝" not in without_info
    assert "\n\n\n" not in without_info


def test_discord_payload_uses_content_not_embeds_and_verifies_plain_text():
    calls = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"content": calls[0][1]["json"]["content"]}

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
    assert "content" in calls[0][1]["json"]
    assert "embeds" not in calls[0][1]["json"]
    assert calls[0][1]["json"]["content"].endswith(asia.ASIA_TICKET_FOOTER)


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
