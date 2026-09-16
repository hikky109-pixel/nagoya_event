from tools.event import aichi_nagoya_2026_session_info_display_review as review


def source(candidate, **overrides):
    row = {
        "sheet_row_number": 2,
        "classification": "SAFE_TO_UPDATE",
        "sheet": {
            "date": "2026-09-10",
            "time": "10:00:00",
            "venue": "IGアリーナ",
            "event_name": "バスケットボール",
        },
        "current_session_info": "男子予選（4試合）",
        "candidate_session_info": candidate,
        "result_code": "M.TEAM.GPA.1",
        "is_japan_match": False,
    }
    row.update(overrides)
    return row


def test_general_group_and_pool_repairs_are_review_only():
    group = review.review_row(source("男子予選ラウンド-グループA｜日本 vs ネパール"))
    pool = review.review_row(source("女子予選ラウンドプールD｜タイ vs 中国"))
    assert group["display_classification"] == review.DISPLAY_NEEDS_FIX
    assert group["recommended_session_info"] == "男子予選グループA｜日本 vs ネパール"
    assert pool["recommended_session_info"] == "女子予選プールD｜タイ vs 中国"


def test_corruption_and_unexpected_english_require_review():
    corrupted = review.review_row(source("男子順位決定?｜日本 vs Nepal"))
    assert corrupted["display_classification"] == review.NEEDS_REVIEW
    assert "文字化け" in corrupted["display_reason"]
    assert "連続英字" in corrupted["display_reason"]


def test_clean_org_normalized_team_candidate_is_display_ok():
    row = review.review_row(source("男子準々決勝｜日本 vs 中華人民共和国", is_japan_match=True))
    assert row["display_classification"] == review.DISPLAY_OK
    assert row["team_identity_check"] == "ORG_CODE_TEAM_EVENT"
    assert row["important_round_types"] == ["準々決勝"]


def test_build_report_uses_only_safe_rows():
    safe = source("男子決勝｜日本 vs 大韓民国", is_japan_match=True)
    held = source("男子準決勝｜日本 vs タイ", classification="NEEDS_REVIEW")
    report = review.build_report({"rows": [safe, held]})
    assert report["source_safe_count"] == 1
    assert report["summary"]["japan_matches"] == 1
    assert report["summary"]["finals"] == 1
    assert report["summary"]["semifinals"] == 0
    assert report["sheet_write"] is False
