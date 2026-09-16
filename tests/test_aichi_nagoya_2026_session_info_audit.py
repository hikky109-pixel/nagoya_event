from tools.event import aichi_nagoya_2026_session_info_audit as audit


def sheet(**overrides):
    row = {
        "date": "2026-09-16",
        "time": "10:00:00",
        "end_time": "12:00:00",
        "venue": "IGアリーナ",
        "event_name": "バスケットボール",
        "session_info": "男子準々決勝（4試合）",
        "availability_status": "BUY",
    }
    row.update(overrides)
    return row


def candidate(**overrides):
    value = {
        "result_code": "BKB-QF-3",
        "session_info_candidate": "男子準々決勝｜ヨルダン vs 大韓民国",
        "is_head_to_head": True,
        "is_team_event": True,
        "matchup": "ヨルダン vs 大韓民国",
        "competitors": {
            "home": {"organization": "JOR"},
            "away": {"organization": "KOR"},
        },
    }
    value.update(overrides)
    return value


def results_row(classification="EXACT_MATCH", **overrides):
    value = {
        "classification": classification,
        "candidate_count": 1,
        "sheet": sheet(),
        "results_candidates": [candidate()],
    }
    value.update(overrides)
    return value


def test_unique_exact_team_candidate_is_safe_and_uses_org_normalized_matchup():
    row = audit.classify_row(9, results_row(), "CONTENT_MATCH")
    assert row["classification"] == audit.SAFE_TO_UPDATE
    assert row["candidate_session_info"] == "男子準々決勝｜ヨルダン vs 大韓民国"
    assert row["result_code"] == "BKB-QF-3"


def test_equivalent_current_session_is_unchanged():
    source = results_row()
    source["sheet"] = sheet(session_info="男子 準々決勝｜ヨルダン vs 大韓民国")
    row = audit.classify_row(9, source, "AGGREGATED_OK")
    assert row["classification"] == audit.UNCHANGED


def test_every_results_mismatch_maps_to_specific_hold():
    expected = {
        "TIME_MISMATCH": audit.HOLD_TIME_MISMATCH,
        "DATE_MISMATCH": audit.HOLD_DATE_MISMATCH,
        "VENUE_MISMATCH": audit.HOLD_VENUE_MISMATCH,
        "MULTIPLE_CANDIDATES": audit.HOLD_MULTIPLE_CANDIDATES,
        "RESULTS_NOT_FOUND": audit.HOLD_RESULTS_NOT_FOUND,
    }
    for state, classification in expected.items():
        row = audit.classify_row(2, results_row(state), "CONTENT_MATCH")
        assert row["classification"] == classification
        assert row["candidate_session_info"] == ""
        if state == "MULTIPLE_CANDIDATES":
            assert row["aggregation_state"] == "MULTIPLE_RESULTS_NOT_COMBINED"


def test_content_outdated_and_unresolved_content_never_become_safe():
    outdated = audit.classify_row(44, results_row(), "CONTENT_OUTDATED")
    insufficient = audit.classify_row(139, results_row(), "INSUFFICIENT_SHEET_INFO")
    review = audit.classify_row(146, results_row(), "NEEDS_REVIEW")
    assert outdated["classification"] == audit.HOLD_CONTENT_OUTDATED
    assert outdated["candidate_session_info"] == "男子準々決勝｜ヨルダン vs 大韓民国"
    assert insufficient["classification"] == audit.NEEDS_REVIEW
    assert review["classification"] == audit.NEEDS_REVIEW


def test_team_matchup_and_rescode_are_required_for_safe_generation():
    no_matchup = results_row(results_candidates=[candidate(matchup="")])
    no_code = results_row(results_candidates=[candidate(result_code="")])
    assert audit.classify_row(2, no_matchup, "CONTENT_MATCH")["classification"] == audit.NEEDS_REVIEW
    assert audit.classify_row(2, no_code, "CONTENT_MATCH")["classification"] == audit.NEEDS_REVIEW


def test_ceremonies_and_test_rows_are_never_candidates():
    for event_name in ("開会式", "閉会式", "【発火テスト】バスケットボール"):
        source = results_row()
        source["sheet"] = sheet(event_name=event_name)
        row = audit.classify_row(2, source, "NOT_APPLICABLE")
        assert row["classification"] == audit.HOLD_RESULTS_NOT_FOUND
        assert row["candidate_session_info"] == ""


def test_content_index_uses_data_rows_but_output_uses_physical_sheet_rows():
    rows = audit.audit_session_info_rows(
        [results_row(), results_row()],
        {1: "CONTENT_MATCH", 2: "CONTENT_OUTDATED"},
    )
    assert [row["sheet_row_number"] for row in rows] == [2, 3]
    assert rows[0]["classification"] == audit.SAFE_TO_UPDATE
    assert rows[1]["classification"] == audit.HOLD_CONTENT_OUTDATED


def test_summary_counts_priority_candidates_without_final_overlap():
    labels = [
        "男子準々決勝｜日本 vs 中国",
        "女子準決勝｜韓国 vs 中国",
        "男子3位決定戦｜日本 vs 韓国",
        "女子決勝｜中国 vs 韓国",
    ]
    rows = []
    for index, label in enumerate(labels):
        source = results_row(results_candidates=[candidate(
            result_code=f"R{index}",
            session_info_candidate=label,
            competitors={
                "home": {"organization": "JPN" if "日本" in label else "CHN"},
                "away": {"organization": "KOR"},
            },
        )])
        rows.append(audit.classify_row(index + 2, source, "CONTENT_MATCH"))
    summary = audit.summarize(rows)
    assert summary["japan_match_candidates"] == 2
    assert summary["quarterfinal_candidates"] == 1
    assert summary["semifinal_candidates"] == 1
    assert summary["bronze_match_candidates"] == 1
    assert summary["final_candidates"] == 1
