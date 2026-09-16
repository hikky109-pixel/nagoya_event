import json
import time
import zlib
from datetime import date

import pytest

import tools.event.aichi_nagoya_2026_results as results


def wire_payload(value):
    json_bytes = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return zlib.compress(json_bytes).decode("latin-1").encode("utf-8")


def daily_unit(**overrides):
    value = {
        "Orgs": ["JOR", "KOR"],
        "IsPhase": False,
        "ResCode": "M.TEAM5-------------.QFNL.000300--",
        "Disc": "BKB",
        "DiscDesc": "Basketball",
        "Key": "M.TEAM5-------------.QFNL.000300--",
        "isH2H": True,
        "Status": "SCHEDULED",
        "StatusDesc": "Scheduled",
        "DateTimeRaw": "2026-09-16T10:00:00+09:00",
        "Venue": "AIA",
        "VenueDesc": "Aichi International Arena",
        "VenueDescS": "Aichi International Arena",
        "Loc": "001",
        "LocDesc": "Aichi International Arena",
        "Event": "M.TEAM5-------------",
        "EventDesc": "Men",
        "Phase": "M.TEAM5-------------.QFNL",
        "PhaseDesc": "Men Quarterfinals",
        "PhaseDescS": "Men 1/4",
        "PhaseDescA": "Quarterfinals",
        "UnitDesc": "Men Quarterfinals Game 3",
        "UnitDescS": "Men 1/4 G 3",
        "UnitDescA": "Game 3",
        "UnitNum": "22",
        "Home": {"Name": "Jordan", "Org": "JOR"},
        "Away": {"Name": "Republic of Korea", "Org": "KOR"},
    }
    value.update(overrides)
    return value


class Response:
    def __init__(self, value):
        self.content = wire_payload(value)
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True


def test_decode_reverses_utf8_latin1_zlib_and_keeps_unicode():
    value = [{"DiscDesc": "水泳", "VenueDesc": "名古屋会場"}]
    assert results.decode_results_payload(wire_payload(value)) == value


def test_decode_rejects_invalid_zlib_and_invalid_json():
    with pytest.raises(results.ResultsPayloadError, match="zlib"):
        results.decode_results_payload(b"plain text")
    invalid_json = zlib.compress(b"not-json").decode("latin-1").encode("utf-8")
    with pytest.raises(results.ResultsPayloadError, match="valid UTF-8 JSON"):
        results.decode_results_payload(invalid_json)


def test_fetch_endpoints_use_exact_paths_and_minimal_headers():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response([])

    assert results.fetch_schedule_matrix(http_get=get) == []
    assert results.fetch_day_schedule(date(2026, 9, 16), http_get=get) == []
    assert results.fetch_discipline_daily("bkb", "2026-09-16", http_get=get) == []

    assert [call[0] for call in calls] == [
        f"{results.RESULTS_API_BASE_URL}/ALL/schedule/matrix",
        f"{results.RESULTS_API_BASE_URL}/ALL/schedule/day/2026-09-16",
        f"{results.RESULTS_API_BASE_URL}/BKB/schedule/daily/2026-09-16",
    ]
    assert results.RESULTS_API_BASE_URL.endswith("/ja")
    assert all(call[1] == {
        "headers": results.RESULTS_REQUEST_HEADERS,
        "timeout": results.RESULTS_REQUEST_TIMEOUT,
    } for call in calls)
    assert results.RESULTS_REQUEST_HEADERS == {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://results.asiangames2026.org",
        "Referer": "https://results.asiangames2026.org/",
        "User-Agent": "Mozilla/5.0",
    }


def test_results_request_logs_start_and_done_with_explicit_timeouts():
    progress = []

    value = results.fetch_results_payload(
        "/ALL/schedule/day/2026-09-16",
        http_get=lambda *args, **kwargs: Response([]),
        progress=progress.append,
    )

    assert value == []
    assert "external_http_start source=results" in progress[0]
    assert "language=ja" in progress[0]
    assert "connect_timeout_s=5" in progress[0]
    assert "read_timeout_s=15" in progress[0]
    assert "hard_timeout_s=20" in progress[0]
    assert "external_http_done source=results" in progress[1]


def test_results_request_hard_timeout_logs_endpoint_and_stops_wait():
    progress = []

    def hanging_get(*args, **kwargs):
        time.sleep(1)
        return Response([])

    started = time.monotonic()
    with pytest.raises(results.ExternalRequestTimeout, match="Results API"):
        results.fetch_results_payload(
            "/ALL/schedule/day/2026-09-16",
            http_get=hanging_get,
            hard_timeout=0.02,
            progress=progress.append,
        )

    assert time.monotonic() - started < 0.5
    assert "external_http_error source=results" in progress[-1]
    assert "ExternalRequestTimeout" in progress[-1]


def test_extract_discipline_codes_is_recursive_unique_and_ordered():
    payload = {
        "sports": [
            {"Disc": "BKB"},
            {"children": [{"Disc": "VVO"}, {"Disc": "BKB"}]},
            {"Disc": "ALL"},
        ]
    }
    assert results.extract_discipline_codes(payload) == ["BKB", "VVO"]


def test_head_to_head_daily_unit_has_structured_matchup_and_round():
    normalized = results.normalize_discipline_daily(
        [daily_unit()], requested_discipline="BKB"
    )[0]

    assert normalized["discipline_code"] == "BKB"
    assert normalized["discipline_name"] == "Basketball"
    assert normalized["date"] == "2026-09-16"
    assert normalized["time"] == "10:00:00"
    assert normalized["venue_name"] == "Aichi International Arena"
    assert normalized["round_name"] == "Quarterfinals"
    assert normalized["session_name"] == "Men Quarterfinals Game 3"
    assert normalized["competition_kind"] == "head_to_head"
    assert normalized["competitors"] == {
        "home": {
            "name": "Jordan",
            "organization": "JOR",
            "display_name": "ヨルダン",
            "display_name_source": "org_code",
        },
        "away": {
            "name": "Republic of Korea",
            "organization": "KOR",
            "display_name": "大韓民国",
            "display_name_source": "org_code",
        },
    }
    assert normalized["matchup"] == "ヨルダン vs 大韓民国"


def test_non_head_to_head_unit_keeps_round_and_session_without_opponents():
    unit = daily_unit(
        Disc="SWM",
        DiscDesc="Swimming",
        isH2H=False,
        EventDesc="Women 50m Freestyle",
        PhaseDesc="Heats",
        PhaseDescA="Heats",
        UnitDesc="Women 50m Freestyle Heats",
        UnitDescA="Session 1",
        Home=None,
        Away=None,
    )
    normalized = results.normalize_daily_unit(unit, requested_discipline="SWM")

    assert normalized["competition_kind"] == "session"
    assert normalized["round_name"] == "Heats"
    assert normalized["session_name"] == "Women 50m Freestyle Heats"
    assert normalized["session_label"] == "Session 1"
    assert normalized["competitors"] is None
    assert normalized["matchup"] == ""


def test_individual_head_to_head_keeps_athlete_names_even_with_known_org_codes():
    unit = daily_unit(
        Event="M.INDIVIDUAL--------",
        EventDesc="男子個人",
        Home={"Name": "YAMADA Taro", "Org": "JPN"},
        Away={"Name": "KIM Minjun", "Org": "KOR"},
    )

    normalized = results.normalize_daily_unit(unit, requested_discipline="BKB")

    assert normalized["is_team_event"] is False
    assert normalized["matchup"] == "YAMADA Taro vs KIM Minjun"
    assert normalized["competitors"]["home"]["display_name_source"] == (
        "api_name_fallback"
    )


def test_unknown_team_org_code_falls_back_to_api_name_without_translation():
    unit = daily_unit(Home={"Name": "Example Team", "Org": "ZZZ"})

    normalized = results.normalize_daily_unit(unit, requested_discipline="BKB")

    assert normalized["competitors"]["home"] == {
        "name": "Example Team",
        "organization": "ZZZ",
        "display_name": "Example Team",
        "display_name_source": "api_name_fallback",
    }
    assert normalized["matchup"].startswith("Example Team vs ")


def test_team_org_code_jpn_is_always_normalized_to_japan():
    unit = daily_unit(Away={"Name": "Japan", "Org": "JPN"})

    normalized = results.normalize_daily_unit(unit, requested_discipline="BKB")

    assert normalized["competitors"]["away"]["display_name"] == "日本"
    assert normalized["competitors"]["away"]["display_name_source"] == "org_code"


def test_volleyball_english_api_names_use_org_codes_for_japanese_matchup():
    unit = daily_unit(
        Disc="VVO",
        Event="W.TEAM6-------------",
        EventDesc="女子",
        Home={"Name": "Japan", "Org": "JPN"},
        Away={"Name": "Nepal", "Org": "NEP"},
    )

    normalized = results.normalize_daily_unit(unit, requested_discipline="VVO")

    assert normalized["matchup"] == "日本 vs ネパール"
    assert normalized["competitors"]["home"]["name"] == "Japan"
    assert normalized["competitors"]["away"]["name"] == "Nepal"


def test_fetch_normalized_daily_runs_fetch_decode_and_normalize():
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return Response([daily_unit()])

    normalized = results.fetch_normalized_discipline_daily(
        "BKB", "2026-09-16", http_get=get
    )
    assert len(normalized) == 1
    assert normalized[0]["matchup"] == "ヨルダン vs 大韓民国"
    assert normalized[0]["source_language"] == "ja"
    assert calls == [
        f"{results.RESULTS_API_BASE_URL}/BKB/schedule/daily/2026-09-16"
    ]


def test_explicit_english_language_uses_en_endpoint_and_is_recorded():
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return Response([daily_unit()])

    normalized = results.fetch_normalized_discipline_daily(
        "BKB", "2026-09-16", language="en", http_get=get
    )

    assert calls == [
        f"{results.RESULTS_API_ROOT_URL}/en/BKB/schedule/daily/2026-09-16"
    ]
    assert normalized[0]["source_language"] == "en"


def test_unsupported_results_language_is_rejected_before_request():
    with pytest.raises(ValueError, match="language"):
        results.fetch_schedule_matrix(
            language="fr", http_get=lambda *args, **kwargs: None
        )


@pytest.mark.parametrize("bad_date", ["2026/09/16", "2026-9-16", "not-a-date"])
def test_invalid_schedule_date_is_rejected_before_request(bad_date):
    with pytest.raises(ValueError, match="date"):
        results.fetch_day_schedule(bad_date, http_get=lambda *args, **kwargs: None)


def test_daily_root_and_discipline_mismatch_are_rejected():
    with pytest.raises(results.ResultsPayloadError, match="root must be a list"):
        results.normalize_discipline_daily({"items": []})
    with pytest.raises(results.ResultsPayloadError, match="mismatch"):
        results.normalize_discipline_daily(
            [daily_unit(Disc="VVO")], requested_discipline="BKB"
        )
