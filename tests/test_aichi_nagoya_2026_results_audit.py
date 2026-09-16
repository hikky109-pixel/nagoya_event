import time

import pytest

import tools.event.aichi_nagoya_2026_results_audit as audit


def sheet_row(**overrides):
    value = {
        "date": "2026-09-16",
        "time": "10:00:00",
        "end_time": "21:15:00",
        "venue": "IGアリーナ",
        "event_name": "バスケットボール",
        "session_info": "既存値",
        "availability_status": "LIMITED",
    }
    value.update(overrides)
    return value


def result_unit(**overrides):
    value = {
        "source_language": "ja",
        "result_code": "BKB-1",
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
        "competitors": {
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
        },
        "matchup": "ヨルダン vs 大韓民国",
    }
    value.update(overrides)
    return value


def test_classifies_exact_match_and_never_marks_candidate_auto_selected():
    original = sheet_row()
    before = dict(original)

    classified = audit.classify_audit_row(original, [result_unit()])

    assert classified["classification"] == audit.EXACT_MATCH
    assert classified["candidate_count"] == 1
    assert classified["auto_selected"] is False
    assert classified["results_candidates"][0]["session_info_candidate"] == (
        "男子準々決勝｜ヨルダン vs 大韓民国"
    )
    assert original == before


def test_multiple_exact_units_are_multiple_candidates():
    classified = audit.classify_audit_row(
        sheet_row(),
        [result_unit(), result_unit(result_code="BKB-2")],
    )

    assert classified["classification"] == audit.MULTIPLE_CANDIDATES
    assert classified["candidate_count"] == 2


def test_time_mismatch_returns_every_same_date_venue_sport_candidate():
    records = [
        result_unit(time="13:00:00", result_code="VVO-1"),
        result_unit(time="16:00:00", result_code="VVO-2"),
        result_unit(time="19:20:00", result_code="VVO-3"),
        result_unit(time="12:00:00", venue_name="別会場", result_code="VVO-4"),
    ]

    classified = audit.classify_audit_row(sheet_row(), records)

    assert classified["classification"] == audit.TIME_MISMATCH
    assert classified["candidate_count"] == 3
    assert [item["time"] for item in classified["results_candidates"]] == [
        "13:00:00",
        "16:00:00",
        "19:20:00",
    ]
    assert all(item["venue_matches"] for item in classified["results_candidates"])


def test_venue_mismatch_requires_same_date_time_and_sport():
    classified = audit.classify_audit_row(
        sheet_row(), [result_unit(venue_name="岡崎中央総合公園総合体育館")]
    )

    assert classified["classification"] == audit.VENUE_MISMATCH
    assert classified["results_candidates"][0]["venue_matches"] is False


def test_empty_official_venue_is_reported_as_unverifiable_venue_mismatch():
    classified = audit.classify_audit_row(
        sheet_row(), [result_unit(venue_name="")]
    )

    assert classified["classification"] == audit.VENUE_MISMATCH
    assert "VenueDesc is empty" in classified["reason"]


def test_date_mismatch_uses_only_the_nearest_different_date():
    records = [
        result_unit(date="2026-09-14", result_code="old"),
        result_unit(date="2026-09-17", result_code="near"),
        result_unit(date="2026-09-20", result_code="far"),
    ]

    classified = audit.classify_audit_row(sheet_row(), records)

    assert classified["classification"] == audit.DATE_MISMATCH
    assert classified["candidate_count"] == 1
    assert classified["results_candidates"][0]["date"] == "2026-09-17"
    assert classified["results_candidates"][0]["date_delta_days"] == 1


def test_results_not_found_shows_at_most_five_nearest_same_sport_records():
    records = [
        result_unit(
            date=f"2026-09-{day:02d}",
            time="12:00:00",
            venue_name="別会場",
            result_code=f"BKB-{day}",
        )
        for day in range(17, 24)
    ]

    classified = audit.classify_audit_row(sheet_row(), records)

    assert classified["classification"] == audit.RESULTS_NOT_FOUND
    assert classified["same_sport_candidate_count"] == 7
    assert classified["candidate_count"] == audit.NEAREST_RESULTS_LIMIT
    assert classified["results_candidates"][0]["date"] == "2026-09-17"


def test_unknown_sheet_sport_has_no_invented_candidate():
    classified = audit.classify_audit_row(
        sheet_row(event_name="開会式"), [result_unit()]
    )

    assert classified["classification"] == audit.RESULTS_NOT_FOUND
    assert classified["candidate_count"] == 0


def test_full_period_fetch_uses_matrix_dates_and_only_sheet_relevant_disciplines():
    calls = []

    def fetch_day(target_date):
        calls.append(("day", target_date))
        return [{"Disc": "BKB"}, {"Disc": "VVO"}]

    def fetch_daily(discipline, target_date):
        calls.append((discipline, target_date))
        return [result_unit(date=target_date, result_code=f"{discipline}-{target_date}")]

    dates, records = audit.fetch_full_results_period(
        [sheet_row()],
        matrix_fetcher=lambda: {"dates": ["2026-09-16", "2026-09-17"]},
        day_fetcher=fetch_day,
        daily_fetcher=fetch_daily,
    )

    assert dates == ["2026-09-16", "2026-09-17"]
    assert len(records) == 2
    assert calls == [
        ("day", "2026-09-16"),
        ("BKB", "2026-09-16"),
        ("day", "2026-09-17"),
        ("BKB", "2026-09-17"),
    ]


def test_full_audit_preserves_schema_and_reports_all_classifications():
    rows = [sheet_row(), sheet_row(time="11:00:00")]

    report = audit.run_full_audit(
        sheet_loader=lambda: rows,
        matrix_fetcher=lambda: {"dates": ["2026-09-16"]},
        day_fetcher=lambda target_date: [{"Disc": "BKB"}],
        daily_fetcher=lambda discipline, target_date: [result_unit()],
    )

    assert report["dry_run"] is True
    assert report["sheet_write"] is False
    assert report["results_language"] == "ja"
    assert report["sheet_schema"] == [
        "date",
        "time",
        "end_time",
        "venue",
        "event_name",
        "session_info",
        "availability_status",
    ]
    assert report["summary"][audit.EXACT_MATCH] == 1
    assert report["summary"][audit.TIME_MISMATCH] == 1


def test_full_audit_hard_timeout_interrupts_custom_sheet_loader():
    def hanging_loader():
        time.sleep(1)
        return [sheet_row()]

    started = time.monotonic()
    with pytest.raises(audit.ExternalRequestTimeout, match="full-period audit"):
        audit.run_full_audit(
            sheet_loader=hanging_loader,
            overall_timeout=0.02,
        )

    assert time.monotonic() - started < 0.5


def test_text_report_lists_only_non_exact_rows_and_diagnostic_candidates():
    report = audit.run_full_audit(
        sheet_loader=lambda: [sheet_row(), sheet_row(time="11:00:00")],
        matrix_fetcher=lambda: {"dates": ["2026-09-16"]},
        day_fetcher=lambda target_date: [{"Disc": "BKB"}],
        daily_fetcher=lambda discipline, target_date: [result_unit()],
    )

    text = audit.render_text(report)

    assert "EXACT_MATCH=1 TIME_MISMATCH=1" in text
    assert "classification=TIME_MISMATCH" in text
    assert "classification=EXACT_MATCH" not in text
    assert "diagnostic_only" in text
    assert "session_info_candidate=男子準々決勝｜ヨルダン vs 大韓民国" in text


def test_markdown_report_lists_every_mismatch_row_and_summary():
    report = audit.run_full_audit(
        sheet_loader=lambda: [sheet_row(), sheet_row(time="11:00:00")],
        matrix_fetcher=lambda: {"dates": ["2026-09-16"]},
        day_fetcher=lambda target_date: [{"Disc": "BKB"}],
        daily_fetcher=lambda discipline, target_date: [result_unit()],
    )

    markdown = audit.render_markdown(report)

    assert "| EXACT_MATCH | 1 |" in markdown
    assert "## TIME_MISMATCH (1件)" in markdown
    assert "| 2 | 2026-09-16 11:00:00 |" in markdown
    assert "男子準々決勝｜ヨルダン vs 大韓民国" in markdown
    assert "auto_selected=false" in markdown
