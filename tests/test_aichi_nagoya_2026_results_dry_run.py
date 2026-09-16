import time

import pytest

import tools.event.aichi_nagoya_2026_results_dry_run as dry_run


def sheet_row(**overrides):
    value = {
        "date": "2026-09-16",
        "time": "10:00:00",
        "end_time": "21:15:00",
        "venue": "IGアリーナ",
        "event_name": "バスケットボール",
        "session_info": "男子準々決勝 （4試合）",
        "availability_status": "LIMITED",
    }
    value.update(overrides)
    return value


def result_unit(**overrides):
    value = {
        "source_language": "ja",
        "discipline_code": "BKB",
        "discipline_name": "バスケットボール",
        "date": "2026-09-16",
        "time": "10:00:00",
        "venue_name": "愛知国際アリーナ",
        "event_name": "男子",
        "phase_name": "男子 準々決勝",
        "round_name": "準々決勝",
        "session_name": "男子 準々決勝 試合 3",
        "is_head_to_head": True,
        "matchup": "ヨルダン vs 大韓民国",
    }
    value.update(overrides)
    return value


def test_sheet_reader_is_get_only_and_bounds_live_sheet_to_fixed_a_through_g():
    calls = []

    class Response:
        encoding = None
        text = (
            "date,time,end_time,venue,event_name,session_info,availability_status\n"
            "2026-09-16,10:00:00,21:15:00,IGアリーナ,"
            "バスケットボール,男子準々決勝 （4試合）,LIMITED\n"
        )

        @staticmethod
        def raise_for_status():
            return None

    rows = dry_run.load_asia_sheet_rows_read_only(
        http_get=lambda url, **kwargs: calls.append((url, kwargs)) or Response()
    )

    assert calls == [
        (
            dry_run.ASIA_DRY_RUN_SHEET_URL,
            {"timeout": dry_run.SHEET_REQUEST_TIMEOUT},
        )
    ]
    assert dry_run.ASIA_DRY_RUN_SHEET_URL.endswith(
        "/export?format=csv&gid=272979110&range=A:G"
    )
    assert rows == [sheet_row()]


def test_sheet_reader_logs_start_and_done_with_explicit_timeouts():
    progress = []

    class Response:
        encoding = None
        text = (
            "date,time,end_time,venue,event_name,session_info,availability_status\n"
            "2026-09-16,10:00:00,21:15:00,IGアリーナ,"
            "バスケットボール,男子準々決勝 （4試合）,LIMITED\n"
        )

        @staticmethod
        def raise_for_status():
            return None

    dry_run.load_asia_sheet_rows_read_only(
        http_get=lambda *args, **kwargs: Response(),
        progress=progress.append,
    )

    assert "external_http_start source=google_sheet" in progress[0]
    assert "connect_timeout_s=5" in progress[0]
    assert "read_timeout_s=15" in progress[0]
    assert "hard_timeout_s=20" in progress[0]
    assert "external_http_done source=google_sheet" in progress[1]


def test_sheet_reader_hard_timeout_stops_wait_and_logs_failure():
    progress = []

    def hanging_get(*args, **kwargs):
        time.sleep(1)
        raise AssertionError("hard timeout did not interrupt the GET")

    started = time.monotonic()
    with pytest.raises(dry_run.ExternalRequestTimeout, match="Google Sheets"):
        dry_run.load_asia_sheet_rows_read_only(
            http_get=hanging_get,
            hard_timeout=0.02,
            progress=progress.append,
        )

    assert time.monotonic() - started < 0.5
    assert "external_http_error source=google_sheet" in progress[-1]
    assert "ExternalRequestTimeout" in progress[-1]


def test_known_venue_aliases_are_bidirectional_and_normalized():
    alias_pairs = [
        ("Aichi International Arena", "IGアリーナ"),
        ("Aichi International Arena", "愛知国際アリーナ"),
        ("名古屋市総合体育館［レインボープール］", "NGKアリーナ"),
        ("名古屋市総合体育館［レインボーホール］", "NGKホール"),
        ("名古屋市瑞穂公園陸上競技場", "パロマ瑞穂スタジアム"),
        ("名古屋市瑞穂公園ラグビー場", "パロマ瑞穂ラグビー場"),
        ("名古屋市瑞穂公園体育館", "パロマ瑞穂アリーナ"),
        ("名古屋市東山公園テニスセンター", "東山公園テニスセンター"),
        ("名古屋市中小企業振興会館", "吹上ホール"),
        ("名古屋市港サッカー場", "CSアセット港サッカー場"),
    ]
    for official, sheet in alias_pairs:
        assert dry_run.normalize_venue(official) == dry_run.normalize_venue(sheet)


def test_match_uses_date_time_venue_and_sport_aliases_without_mutating_sheet_row():
    original = sheet_row()
    before = dict(original)

    reconciled = dry_run.reconcile_sheet_row(original, [result_unit()])

    assert reconciled["classification"] == dry_run.MATCH
    assert reconciled["candidate_count"] == 1
    assert reconciled["session_info_candidate"] == (
        "男子準々決勝｜ヨルダン vs 大韓民国"
    )
    assert reconciled["results_candidates"][0]["phase"] == "男子 準々決勝"
    assert reconciled["results_candidates"][0]["source_language"] == "ja"
    assert original == before
    assert original["session_info"] == "男子準々決勝 （4試合）"
    assert original["availability_status"] == "LIMITED"


def test_individual_session_candidate_uses_official_japanese_phase():
    candidate = dry_run.build_session_info_candidate(
        result_unit(
            discipline_code="MPN",
            discipline_name="近代五種",
            event_name="女子個人",
            phase_name="女子個人フェンシング・ランキングラウンド",
            round_name="フェンシング・ランキングラウンド",
            session_name="女子フェンシング-ランキングラウンド",
            is_head_to_head=False,
            matchup="",
        )
    )
    assert candidate == "女子個人フェンシング・ランキングラウンド"


def test_individual_head_to_head_candidate_does_not_include_player_names():
    candidate = dry_run.build_session_info_candidate(
        result_unit(
            event_name="女子個人",
            phase_name="女子個人 準々決勝",
            session_name="選手A vs 選手B",
            is_head_to_head=True,
            is_team_event=False,
            matchup="選手A vs 選手B",
        )
    )
    assert candidate == "女子個人準々決勝"


def test_group_round_candidate_compacts_official_japanese_phase():
    candidate = dry_run.build_session_info_candidate(
        result_unit(
            discipline_code="FBL",
            discipline_name="サッカー",
            phase_name="男子 一次ラウンド\u00a0- グループA",
            round_name="グループA",
            session_name="男子 一次ラウンド - グループA",
            matchup="タイ vs キルギス",
        )
    )
    assert candidate == "男子グループA｜タイ vs キルギス"


def test_pool_candidate_prefers_valid_phase_over_malformed_unit_desc():
    candidate = dry_run.build_session_info_candidate(
        result_unit(
            discipline_code="VVO",
            discipline_name="バレーボール",
            event_name="女子",
            phase_name="女子予選ラウンド - プールA",
            round_name="予選ラウンド - プールA",
            session_name="予選ラウンド - プ?ルA",
            matchup="日本 vs ネパール",
        )
    )

    assert candidate == "女子予選プールA｜日本 vs ネパール"


@pytest.mark.parametrize(
    ("phase_name", "expected"),
    [
        ("男子予選ラウンドグループB", "男子予選グループB"),
        ("男子予選ラウンド-グループA", "男子予選グループA"),
        ("女子予選ラウンド プールA", "女子予選プールA"),
        ("女子予選ラウンドプールB", "女子予選プールB"),
    ],
)
def test_preliminary_group_and_pool_labels_are_compacted(phase_name, expected):
    candidate = dry_run.build_session_info_candidate(
        result_unit(
            phase_name=phase_name,
            matchup="日本 vs ネパール",
        )
    )

    assert candidate == f"{expected}｜日本 vs ネパール"


@pytest.mark.parametrize(
    "phase_name",
    ["男子準々決勝", "女子準決勝", "男子3位決定戦", "女子決勝", "男子順位決定戦", "女子メダルセッション"],
)
def test_non_preliminary_round_labels_are_unchanged(phase_name):
    candidate = dry_run.build_session_info_candidate(
        result_unit(phase_name=phase_name, matchup="日本 vs ネパール")
    )

    assert candidate == f"{phase_name}｜日本 vs ネパール"


def test_multiple_full_key_candidates_are_ambiguous_and_not_auto_selected():
    records = [result_unit(), result_unit(session_name="Duplicate", matchup="Other vs Team")]

    reconciled = dry_run.reconcile_sheet_row(sheet_row(), records)

    assert reconciled["classification"] == dry_run.AMBIGUOUS
    assert reconciled["candidate_count"] == 2
    assert reconciled["session_info_candidate"] == ""
    assert len(reconciled["results_candidates"]) == 2


def test_not_found_reason_identifies_first_failed_key_stage():
    reconciled = dry_run.reconcile_sheet_row(
        sheet_row(time="11:00"), [result_unit()]
    )

    assert reconciled["classification"] == dry_run.NOT_FOUND
    assert reconciled["candidate_count"] == 0
    assert "time did not match" in reconciled["reason"]
    assert reconciled["results_candidates"] == []
    assert len(reconciled["nearby_results"]) == 1
    assert reconciled["nearby_results"][0]["time"] == "10:00:00"


def test_sport_alias_is_exact_and_does_not_mix_3x3_with_basketball():
    reconciled = dry_run.reconcile_sheet_row(
        sheet_row(event_name="3x3 バスケットボール"), [result_unit()]
    )

    assert reconciled["classification"] == dry_run.NOT_FOUND
    assert "sport alias did not match" in reconciled["reason"]


@pytest.mark.parametrize(
    ("discipline_code", "sheet_name"),
    [
        ("CKT", "クリケット（T20）"),
        ("RU7", "ラグビー（ラグビー7s）"),
        ("SPK", "セパタクロー"),
        ("TST", "ソフトテニス"),
    ],
)
def test_official_matrix_discipline_codes_match_sheet_sport_aliases(
    discipline_code, sheet_name
):
    assert dry_run.normalize_sport("", discipline_code) == dry_run.normalize_sport(
        sheet_name
    )


def test_fetch_normalized_day_uses_overview_codes_then_every_daily_feed():
    calls = []

    def fetch_day(day):
        calls.append(("day", day))
        return [{"Disc": "BKB"}, {"Disc": "FBL"}, {"Disc": "BKB"}]

    def fetch_daily(discipline, day):
        calls.append((discipline, day))
        return [result_unit(discipline_code=discipline)]

    records = dry_run.fetch_normalized_day(
        "2026-09-16", day_fetcher=fetch_day, daily_fetcher=fetch_daily
    )

    assert len(records) == 2
    assert calls == [
        ("day", "2026-09-16"),
        ("BKB", "2026-09-16"),
        ("FBL", "2026-09-16"),
    ]


def test_fetch_normalized_day_rejects_empty_discipline_daily_as_partial_data():
    try:
        dry_run.fetch_normalized_day(
            "2026-09-16",
            day_fetcher=lambda day: [{"Disc": "BKB"}],
            daily_fetcher=lambda discipline, day: [],
        )
    except ValueError as exc:
        assert "daily has no records" in str(exc)
    else:
        raise AssertionError("empty discipline daily must not become NOT_FOUND")


def test_run_dry_run_reads_only_and_reports_all_three_classifications():
    sheet_rows = [
        sheet_row(),
        sheet_row(time="13:00:00"),
        sheet_row(time="15:00:00"),
    ]
    records = [
        result_unit(),
        result_unit(time="13:00:00"),
        result_unit(time="13:00:00", matchup="Other vs Team"),
    ]
    loader_calls = []
    progress = []

    report = dry_run.run_dry_run(
        "2026-09-16",
        sheet_loader=lambda: loader_calls.append("GET") or sheet_rows,
        day_fetcher=lambda day: [{"Disc": "BKB"}],
        daily_fetcher=lambda discipline, day: records,
        progress=progress.append,
    )

    assert loader_calls == ["GET"]
    assert report["dry_run"] is True
    assert report["sheet_write"] is False
    assert report["sheet_schema"] == dry_run.ASIA_OPERATIONAL_COLUMNS
    assert report["summary"] == {
        dry_run.MATCH: 1,
        dry_run.AMBIGUOUS: 1,
        dry_run.NOT_FOUND: 1,
    }
    assert [row["classification"] for row in report["rows"]] == [
        dry_run.MATCH,
        dry_run.AMBIGUOUS,
        dry_run.NOT_FOUND,
    ]
    assert progress[0].startswith("dry_run_progress stage=start")
    assert any("stage=sheet_fetch_start" in line for line in progress)
    assert any("stage=results_overview_start" in line for line in progress)
    assert any(
        "stage=results_daily_start" in line and "index=1/1" in line
        for line in progress
    )
    assert progress[-1].startswith("dry_run_progress stage=complete")


def test_run_dry_run_overall_deadline_stops_before_next_external_stage():
    day_called = []

    def slow_sheet_loader():
        time.sleep(0.03)
        return [sheet_row()]

    with pytest.raises(dry_run.ExternalRequestTimeout, match="results_overview"):
        dry_run.run_dry_run(
            "2026-09-16",
            sheet_loader=slow_sheet_loader,
            day_fetcher=lambda day: day_called.append(day) or [{"Disc": "BKB"}],
            daily_fetcher=lambda discipline, day: [result_unit()],
            overall_timeout=0.01,
        )

    assert day_called == []


def test_text_output_contains_sheet_results_reason_phase_matchup_and_candidate():
    report = {
        "date": "2026-09-16",
        "summary": {dry_run.MATCH: 1, dry_run.AMBIGUOUS: 0, dry_run.NOT_FOUND: 0},
        "rows": [dry_run.reconcile_sheet_row(sheet_row(), [result_unit()])],
    }

    text = dry_run.render_text(report)

    assert "SUMMARY MATCH=1 AMBIGUOUS=0 NOT_FOUND=0" in text
    assert "Sheet: date=2026-09-16 time=10:00:00 venue=IGアリーナ" in text
    assert "Results[1]: date=2026-09-16 time=10:00:00" in text
    assert "phase=男子 準々決勝 round=準々決勝" in text
    assert "matchup=ヨルダン vs 大韓民国" in text
    assert "session_info_candidate=男子準々決勝｜ヨルダン vs 大韓民国" in text
