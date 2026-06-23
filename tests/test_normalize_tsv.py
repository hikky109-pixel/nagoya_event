from tools.ai.normalize_tsv import normalize_tsv_with_stats


def test_normalize_tsv_corrects_closed_day_time() -> None:
    result = normalize_tsv_with_stats(
        "2026-06-15\t11:00\t18:00\tTokyo\t休演日\tconfirmed",
        source_times={"11:00"},
        venue="御園座",
    )
    assert result.text == "2026-06-15\tnull\tnull\t御園座\t休演日\tcandidate"
    assert (result.rows_in, result.rows_out, result.dropped) == (1, 1, 0)


def test_normalize_tsv_forces_end_time_null() -> None:
    result = normalize_tsv_with_stats(
        "2026-06-14\t11:00\t15:30\tTokyo\t花より男子II\tconfirmed",
        source_times={"11:00"},
        venue="御園座",
    )
    assert result.text == "2026-06-14\t11:00\tnull\t御園座\t花より男子II\tcandidate"


def test_normalize_tsv_dedupes_same_date_time_title() -> None:
    result = normalize_tsv_with_stats(
        "\n".join(
            [
                "2026-06-14\t11:00\tnull\t御園座\t花より男子II\tcandidate",
                "2026-06-14\t11:00\tnull\t御園座\t花より男子II\tcandidate",
            ]
        ),
        source_times={"11:00"},
        venue="御園座",
    )
    assert result.text == "2026-06-14\t11:00\tnull\t御園座\t花より男子II\tcandidate"
    assert (result.rows_in, result.rows_out, result.dropped) == (2, 1, 1)


def test_normalize_tsv_drops_dash_time() -> None:
    result = normalize_tsv_with_stats(
        "2026-06-14\t-\tnull\t御園座\t花より男子II\tcandidate",
        source_times={"11:00"},
        venue="御園座",
    )
    assert result.text == ""
    assert (result.rows_in, result.rows_out, result.dropped) == (1, 0, 1)


def test_normalize_tsv_drops_time_missing_from_source() -> None:
    result = normalize_tsv_with_stats(
        "2026-06-14\t14:00\tnull\t御園座\t花より男子II\tcandidate",
        source_times={"11:00"},
        venue="御園座",
    )
    assert result.text == ""
    assert (result.rows_in, result.rows_out, result.dropped) == (1, 0, 1)


def test_normalize_tsv_corrects_reserved_private_row() -> None:
    result = normalize_tsv_with_stats(
        "2026-06-17\t11:00\t18:00\tTokyo\t貸切\tconfirmed",
        source_times={"11:00"},
        venue="御園座",
    )
    assert result.text == "2026-06-17\t貸切\tnull\t御園座\t貸切\tcandidate"
