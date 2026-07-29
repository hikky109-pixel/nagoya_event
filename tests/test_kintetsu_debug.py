import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.get_kintetsu_status import (  # noqa: E402
    collect_kintetsu_debug,
    extract_kintetsu_detail_urls,
    extract_kintetsu_top_page_entries,
    parse_kintetsu_detail,
)


JST = timezone(timedelta(hours=9))
TOP_HTML = """
<html><body>
<table><tbody><tr>
<td>名古屋線</td><td>一部運休</td><td>車両故障</td>
<td><input type="image" onclick="window.open('./files/905901.html')"></td>
</tr></tbody></table>
</body></html>
"""
DETAIL_HTML = """
<html><body>
<font size="+2">【奈良線　運転見合わせ】</font>
<p id="tran"><br>
６月２６日 ８時０６分 現在<br>
奈良線は、枚岡－生駒間で発生した大雨のため、
瓢箪山～大和西大寺間の上下線で運転を見合わせています。<br>
運転見合わせ区間：奈良線　瓢箪山～大和西大寺間<br>
影響線区：京都線、橿原線、大阪線、名古屋線で遅れと
一部の列車が運休しています。<br>
名古屋線　近鉄名古屋～伊勢中川間で遅れています。<br>
名阪特急にも遅れが発生しています。<br>
振替輸送：大阪地下鉄との振替輸送を行っています。
</p>
</body></html>
"""
NARA_TO_NAGOYA_DETAIL_HTML = """
<html><body>
<font size="+2">【奈良線　一部運休】</font>
<p id="tran"><br>
７月２９日 １９時０７分 現在<br>
奈良線は、富雄駅構内で発生した人身事故のため、
大阪難波～近鉄奈良間の上下線で遅れと一部の列車が運休しています。<br>
一部列車運休区間：奈良線　大阪難波～近鉄奈良間<br>
影響線区：<br>
京都線　高の原～大和西大寺間で遅れと一部の列車が運休しています。<br>
大阪線　河内国分～伊勢中川間で遅れが出ています。<br>
名古屋線　近鉄名古屋～伊勢中川間で遅れが出ています。<br>
振替輸送：実施していません。
</p>
</body></html>
"""


def test_extract_kintetsu_detail_url_deduplicates_and_adds_anchor() -> None:
    assert extract_kintetsu_detail_urls(TOP_HTML) == [
        "https://www.kintetsu.jp/unkou/files/905901.html#tran"
    ]


def test_extract_kintetsu_top_page_entry_keeps_primary_line() -> None:
    assert extract_kintetsu_top_page_entries(TOP_HTML) == [
        {
            "detail_url": "https://www.kintetsu.jp/unkou/files/905901.html#tran",
            "top_page_line": "名古屋線",
            "top_page_lines": ["名古屋線"],
            "top_page_status": "一部運休",
            "top_page_cause": "車両故障",
        }
    ]


def test_extract_kintetsu_top_page_entry_accepts_anchor_link() -> None:
    top_html = TOP_HTML.replace(
        '<input type="image" onclick="window.open(\'./files/905901.html\')">',
        '<a href="./files/905901.html#tran">詳細</a>',
    )

    assert extract_kintetsu_top_page_entries(top_html)[0]["detail_url"] == (
        "https://www.kintetsu.jp/unkou/files/905901.html#tran"
    )


def test_parse_kintetsu_detail_extracts_affected_lines_and_body() -> None:
    detail_url = "https://www.kintetsu.jp/unkou/files/905901.html#tran"
    record = parse_kintetsu_detail(DETAIL_HTML, detail_url)

    assert record["title"] == "奈良線 運転見合わせ"
    assert record["updated_at_text"] == "６月２６日 ８時０６分 現在"
    assert record["cause"] == "大雨"
    assert record["origin_line"] == "奈良線"
    assert record["main_line"] == "奈良線"
    assert record["affected_lines"] == [
        "名古屋線",
        "大阪線",
        "奈良線",
        "京都線",
        "橿原線",
    ]
    assert "近鉄名古屋～伊勢中川" in record["body_text"]
    assert "名阪特急" in record["body_text"]
    assert "名古屋線 近鉄名古屋～伊勢中川" in record["affected_sections"]
    assert all("大阪地下鉄" not in section for section in record["affected_sections"])
    assert "振替輸送" in record["transfer_info"]
    assert record["detail_url"] == detail_url
    assert record["content_hash"] == hashlib.sha256(
        record["body_text"].encode("utf-8")
    ).hexdigest()


def test_parse_kintetsu_detail_structures_real_nara_to_nagoya_case() -> None:
    record = parse_kintetsu_detail(
        NARA_TO_NAGOYA_DETAIL_HTML,
        "https://www.kintetsu.jp/unkou/files/example.html#tran",
    )

    assert record["origin_line"] == "奈良線"
    assert record["origin_location"] == "富雄駅構内"
    assert record["cause"] == "人身事故"
    assert record["status"] == "遅れ"
    assert record["affected_statuses"]["奈良線"] == "遅れ・運休"
    assert record["affected_statuses"]["名古屋線"] == "遅れ"
    assert record["direct"] is False
    assert "名古屋線" in record["affected_lines"]


def test_collect_kintetsu_debug_saves_latest_and_history(tmp_path: Path) -> None:
    detail_raw = DETAIL_HTML.encode("cp932")

    snapshot = collect_kintetsu_debug(
        TOP_HTML,
        detail_fetcher=lambda url: (detail_raw, url, 200),
        debug_dir=tmp_path,
        now=datetime(2026, 6, 26, 9, 30, tzinfo=JST),
    )

    latest = tmp_path / "kintetsu_latest.json"
    history = tmp_path / "kintetsu_20260626_093000.json"
    assert latest.exists()
    assert history.exists()
    assert snapshot["detail_urls"] == [
        "https://www.kintetsu.jp/unkou/files/905901.html#tran"
    ]
    saved = json.loads(latest.read_text(encoding="utf-8"))
    assert saved["records"][0]["top_page_lines"] == ["名古屋線"]
    assert saved["records"][0]["affected_lines"] == [
        "名古屋線",
        "大阪線",
        "奈良線",
        "京都線",
        "橿原線",
    ]
    assert saved["records"][0]["status_code"] == 200


def test_collect_skips_non_nagoya_detail_but_saves_debug_record(tmp_path: Path) -> None:
    top_html = TOP_HTML.replace("名古屋線", "大阪線")
    fetched_urls: list[str] = []

    snapshot = collect_kintetsu_debug(
        top_html,
        detail_fetcher=lambda url: fetched_urls.append(url),
        debug_dir=tmp_path,
        now=datetime(2026, 7, 28, 9, 30, tzinfo=JST),
    )

    assert fetched_urls == []
    assert snapshot["records"][0]["top_page_lines"] == ["大阪線"]
    assert snapshot["records"][0]["affected_lines"] == []
    assert (
        snapshot["records"][0]["detail_skipped_reason"]
        == "top_page_target_line_not_found"
    )
    saved = json.loads((tmp_path / "kintetsu_latest.json").read_text(encoding="utf-8"))
    assert saved["records"] == snapshot["records"]
