from tools.ai.run_qwen_ollama import (
    extract_json_object,
    fallback_comment,
    normalize_comment_lines,
    render_comment,
)


EMPTY_CONTEXT = {
    "events": [],
    "railway": {},
    "road": [],
    "weather": {},
    "cruise": [],
    "asia_games": [],
    "busy_reports": [],
}


def test_extract_json_object_rejects_raw_list_response() -> None:
    data, reason = extract_json_object('["・有効そうな行"]')

    assert data == {}
    assert reason == "raw_response_type_list"


def test_extract_json_object_rejects_raw_string_response() -> None:
    data, reason = extract_json_object('"・有効そうな行"')

    assert data == {}
    assert reason == "raw_response_type_str"


def test_render_comment_requires_comment_lines() -> None:
    comment, reason = render_comment({}, EMPTY_CONTEXT)

    assert comment == ""
    assert reason == "comment_lines_missing"


def test_normalize_comment_lines_rejects_over_40_chars() -> None:
    lines, reason = normalize_comment_lines(["あ" * 40], EMPTY_CONTEXT)

    assert lines == []
    assert reason == "comment_line_too_long chars=41"


def test_normalize_comment_lines_rejects_internal_message() -> None:
    lines, reason = normalize_comment_lines(["入力あり: events"], EMPTY_CONTEXT)

    assert lines == []
    assert reason == "internal_message"


def test_insufficient_material_allowed_only_when_all_data_zero() -> None:
    active_context = dict(EMPTY_CONTEXT)
    active_context["events"] = [{"title": "test"}]

    comment, reason = render_comment({"comment_lines": ["判断材料不足"]}, active_context)

    assert comment == ""
    assert reason == "insufficient_material_with_data"
    assert render_comment({"comment_lines": ["判断材料不足"]}, EMPTY_CONTEXT) == ("・判断材料不足", "")


def test_fallback_comment_avoids_internal_message_with_data() -> None:
    active_context = dict(EMPTY_CONTEXT)
    active_context["railway"] = {"status": "normal"}

    comment = fallback_comment(active_context)

    assert "入力あり" not in comment
    assert "判断材料不足" not in comment
    assert comment == "・鉄道情報を確認中"
