import csv
import json
from urllib.parse import parse_qs, urlparse

from tools.location import export_placeinfo_review
from tools.location.export_placeinfo_review import export_review_tsv, parse_placeinfo_content, rows_from_messages


SAMPLE_CONTENT = """🚕 現在地テスト結果

📍 中村区沖田町

推定:
畑江通八交差点付近

座標:
35.158953, 136.856430

候補:
1. ケーズデンキ岩塚店
2. 畑江通八交差点
3. 鈍池町3交差点
4. 岩塚駅
5. 岩塚駅前交差点

結果が違う場合は、この投稿にリプライで正解を教えてください😇
"""


def test_parse_placeinfo_content():
    parsed = parse_placeinfo_content(SAMPLE_CONTENT)

    assert parsed is not None
    assert parsed["address"] == "中村区沖田町"
    assert parsed["current_guess"] == "畑江通八交差点付近"
    assert parsed["lat"] == "35.158953"
    assert parsed["lon"] == "136.856430"
    assert parsed["candidate1"] == "ケーズデンキ岩塚店"
    assert parsed["candidate5"] == "岩塚駅前交差点"
    assert parsed["google_maps_url"] == "https://www.google.com/maps?q=35.158953,136.856430"


def test_export_review_tsv_dedupes_by_message_id(tmp_path):
    source = tmp_path / "discord.jsonl"
    output = tmp_path / "placeinfo_review.tsv"
    rows = [
        {"timestamp": "2026-07-06T00:00:00+00:00", "message_id": "abc", "content": SAMPLE_CONTENT},
        {"timestamp": "2026-07-06T00:00:01+00:00", "message_id": "abc", "content": SAMPLE_CONTENT},
        {"timestamp": "2026-07-06T00:00:02+00:00", "message_id": "def", "content": "雑談"},
    ]
    source.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    exported = export_review_tsv(source, output)

    assert len(exported) == 1
    with output.open(encoding="utf-8", newline="") as f:
        tsv_rows = list(csv.DictReader(f, delimiter="\t"))
    assert len(tsv_rows) == 1
    assert tsv_rows[0]["message_id"] == "abc"
    assert tsv_rows[0]["candidate2"] == "畑江通八交差点"
    assert tsv_rows[0]["my_comment"] == ""


def test_export_review_tsv_dedupes_by_location_timestamp_without_message_id(tmp_path):
    source = tmp_path / "discord.jsonl"
    output = tmp_path / "placeinfo_review.tsv"
    rows = [
        {"timestamp": "2026-07-06T00:00:00+00:00", "content": SAMPLE_CONTENT},
        {"timestamp": "2026-07-06T00:00:00+00:00", "content": SAMPLE_CONTENT},
    ]
    source.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    exported = export_review_tsv(source, output)

    assert len(exported) == 1
    assert exported[0]["message_id"] == ""


def test_rows_from_discord_api_messages():
    rows = rows_from_messages(
        [
            {
                "id": "151234567890",
                "timestamp": "2026-07-06T00:00:00.000000+00:00",
                "content": SAMPLE_CONTENT,
            }
        ]
    )

    assert len(rows) == 1
    assert rows[0]["message_id"] == "151234567890"
    assert rows[0]["timestamp"] == "2026-07-06T00:00:00.000000+00:00"
    assert rows[0]["address"] == "中村区沖田町"


def test_fetch_discord_messages_uses_rest_api_and_clamps_limit(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps([{"id": "1", "timestamp": "2026-07-06T00:00:00+00:00", "content": "x"}]).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(export_placeinfo_review, "urlopen", fake_urlopen)

    messages = export_placeinfo_review.fetch_discord_messages("channel-1", "token-1", limit=999)

    parsed = urlparse(captured["url"])
    assert parsed.path == "/api/v10/channels/channel-1/messages"
    assert parse_qs(parsed.query)["limit"] == ["100"]
    assert captured["authorization"] == "Bot token-1"
    assert captured["timeout"] == 20
    assert messages[0]["id"] == "1"
