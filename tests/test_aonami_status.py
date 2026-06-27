import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tools.ai.get_aonami_status as aonami_status  # noqa: E402

from tools.ai.get_aonami_status import (  # noqa: E402
    get_aonami_status_snapshot,
    parse_aonami_feed,
)
from tools.ai.railway_severity import detect_railway_severity  # noqa: E402
from tools.ai.run_gemma_ollama import build_railway_beta_comment  # noqa: E402


def _feed(title: str, description: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>{title}</title>
<link>https://www.aonamiline.co.jp/railinfo/1234</link>
<pubDate>Thu, 25 Jun 2026 00:30:52 +0000</pubDate>
<description>{description}</description>
</item></channel></rss>""".encode()


def test_aonami_detail_extracts_cms_fields() -> None:
    detail = """
    <html><main>
      <h3 class="top0">強風による運転見合わせ</h3>
      <p class="read">全線で運転を見合わせています。</p>
    </main></html>
    """.encode()

    records = parse_aonami_feed(
        _feed("運行情報"),
        detail_fetcher=lambda url: (detail, url, 200),
    )

    assert records[0]["detail_url"].endswith("/railinfo/1234")
    assert records[0]["detail_title"] == "強風による運転見合わせ"
    assert records[0]["detail_body"] == "全線で運転を見合わせています。"
    assert records[0]["published_at"] == "2026-06-25T00:30:52+00:00"
    assert records[0]["level"] == "critical"
    assert records[0]["severity_reason"] == "金城ふ頭方面は代替交通が少ない"
    assert len(records[0]["detail_body_hash"]) == 64


def test_aonami_normal_caution_remains_info_and_normal() -> None:
    detail = """
    <html><main>
      <h3 class="top0">平常通り運行しております。</h3>
      <p class="read">台風の状況によっては遅れが発生する恐れがあります。</p>
    </main></html>
    """.encode()

    record = parse_aonami_feed(
        _feed("平常通り運行しております。"),
        detail_fetcher=lambda url: (detail, url, 200),
    )[0]

    assert record["is_normal"] is True
    assert record["alert_candidate"] is True
    assert record["level"] == "info"
    assert record["severity_reason"] == "normal_caution"


def test_aonami_rss_normal_typhoon_caution_is_included_in_alerts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    title = (
        "平常通り運行しております。"
        "（台風7号の状況によっては、列車の運転見合わせ、"
        "遅れが発生する恐れがあります。）"
    )
    feed = _feed(title)
    detail = """
    <html><main>
      <h3 class="top0">運行情報</h3>
      <p class="read">今後の気象情報にご注意ください。</p>
    </main></html>
    """.encode()

    def fake_fetch(url: str) -> tuple[bytes, str, int]:
        if url == aonami_status.FEED_URL:
            return feed, url, 200
        return detail, url, 200

    monkeypatch.setattr(aonami_status, "_fetch", fake_fetch)
    messages, source_urls, _updated_at, levels = get_aonami_status_snapshot(
        abnormal_only=True,
        state_path=tmp_path / "state.json",
        debug_path=tmp_path / "debug.json",
    )

    assert len(messages) == 1
    assert title in messages[0]
    assert levels[messages[0]] == "info"
    assert source_urls[messages[0]].endswith("/railinfo/1234")

    debug = json.loads((tmp_path / "debug.json").read_text(encoding="utf-8"))
    record = debug["records"][0]
    assert record["is_normal"] is True
    assert record["alert_candidate"] is True
    assert record["severity_reason"] == "normal_caution"
    assert len(record["detail_body_hash"]) == 64
    assert record["detail_url"].endswith("/railinfo/1234")


def test_aonami_plain_normal_operation_is_not_an_alert_candidate() -> None:
    detail = """
    <html><main>
      <h3 class="top0">平常通り運行しております。</h3>
      <p class="read">現在、平常通り運行しております。</p>
    </main></html>
    """.encode()

    record = parse_aonami_feed(
        _feed("平常通り運行しております。"),
        detail_fetcher=lambda url: (detail, url, 200),
    )[0]

    assert record["is_normal"] is True
    assert record["alert_candidate"] is False
    assert record["level"] == "info"
    assert record["severity_reason"] == "normal"


def test_aonami_actual_stop_overrides_stale_normal_title() -> None:
    detail = """
    <html><main>
      <h3 class="top0">平常通り運行しております。</h3>
      <p class="read">強風のため、全線で運転を見合わせています。</p>
    </main></html>
    """.encode()

    record = parse_aonami_feed(
        _feed("平常通り運行しております。"),
        detail_fetcher=lambda url: (detail, url, 200),
    )[0]

    assert record["is_normal"] is False
    assert record["alert_candidate"] is True
    assert record["level"] == "critical"
    assert record["severity_reason"] == "金城ふ頭方面は代替交通が少ない"


def test_aonami_severity_is_critical_for_typhoon_incident() -> None:
    assert detect_railway_severity(
        ["あおなみ線: 台風のため運転を見合わせています。"]
    ) == "critical"


def test_aonami_notification_includes_detail_url_and_demand_reason() -> None:
    alert = "あおなみ線: 強風のため運転を見合わせています。"
    detail_url = "https://www.aonamiline.co.jp/railinfo/1234"

    comment = build_railway_beta_comment(
        [alert],
        source_url_by_alert={alert: detail_url},
    )

    assert detail_url in comment
    assert "金城ふ頭方面は代替交通が少ない" in comment
