from tools.ai.output_guard import tokenize, validate_output, validate_structured_tsv_output


def test_tokenize_splits_ocr_words() -> None:
    assert tokenize("2026-06-09 13:00 御園座 花より男子II") == {
        "2026-06-09",
        "13:00",
        "御園座",
        "花より男子II",
    }


def test_validate_output_accepts_source_tokens_and_tsv_status() -> None:
    source = "2026-06-09 13:00 御園座 花より男子II"
    output = "2026-06-09\t13:00\t\t御園座\t花より男子II\tcandidate"
    assert validate_output(source, output) == (True, [])


def test_validate_output_blocks_forbidden_words() -> None:
    source = "2026-06-09 13:00 御園座 花より男子II"
    output = "2026-06-09\t13:00\t\tShibuya\t花より男子II\tcandidate"
    assert validate_output(source, output) == (False, ["Shibuya"])


def test_validate_output_blocks_times_missing_from_source() -> None:
    source = "13:00\n18:00"
    output = "13:00\n14:00"
    assert validate_output(source, output) == (False, ["14:00"])


def test_validate_output_reports_unknown_tokens_in_output_order() -> None:
    source = "2026-06-09 13:00 御園座 花より男子II"
    output = "2026-06-09\t14:00\t\tShibuya\t花より男子II\tcandidate"
    assert validate_output(source, output) == (False, ["14:00", "Shibuya"])


def test_validate_structured_tsv_output_accepts_spot_rows() -> None:
    records = [
        {"date": "2026-06-14", "day": "11:00", "night": "15:30"},
        {"date": "2026-06-15", "status": "休演日"},
        {"date": "2026-06-17", "day": "11:00", "night": "貸切"},
    ]
    output = "\n".join(
        [
            "2026-06-14\t11:00\tnull\t御園座\t花より男子II\tcandidate",
            "2026-06-14\t15:30\tnull\t御園座\t花より男子II\tcandidate",
            "2026-06-15\tnull\tnull\t御園座\t休演日\tcandidate",
            "2026-06-17\t11:00\tnull\t御園座\t花より男子II\tcandidate",
            "2026-06-17\t貸切\tnull\t御園座\t貸切\tcandidate",
        ]
    )
    assert validate_structured_tsv_output(records, output, venue="御園座", title="花より男子II") == (True, [])


def test_validate_structured_tsv_output_accepts_zero_padded_time() -> None:
    records = [{"date": "2026-06-14", "day": "9:00"}]
    output = "2026-06-14\t09:00\tnull\t御園座\t花より男子II\tcandidate"
    assert validate_structured_tsv_output(records, output, venue="御園座", title="花より男子II") == (True, [])


def test_validate_structured_tsv_output_blocks_structural_hallucinations() -> None:
    records = [{"date": "2026-06-14", "day": "11:00"}]
    output = "\n".join(
        [
            "2026-06-14\t11:00\tnull\tTokyo\t花より男子II\tcandidate",
            "2026-06-14\t15:30\tnull\t御園座\t花より男子II\tcandidate",
        ]
    )
    ok, errors = validate_structured_tsv_output(records, output, venue="御園座", title="花より男子II")
    assert ok is False
    assert errors == ["rows>1", "row1:venue:Tokyo", "row2:time:15:30"]
