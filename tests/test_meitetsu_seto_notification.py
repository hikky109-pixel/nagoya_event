import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.get_meitetsu_status import parse_meitetsu_status  # noqa: E402
from tools.ai.run_gemma_ollama import build_railway_beta_comment  # noqa: E402


JST = timezone(timedelta(hours=9))


SETOSEN_20260802_HTML = """
<html><body>
  <div class="emInfo emLv01">
    <h2>運転見合わせ</h2>
    <table>
      <tr><th>路線</th><td><ul><li>瀬戸線</li></ul></td></tr>
      <tr><th>区間</th><td><dl><dd>栄町～尾張瀬戸</dd></dl></td></tr>
      <tr><th>理由</th><td><dl><dd>大雨による運転規制</dd></dl></td></tr>
      <tr><th>備考</th><td>
        <dl><dd>現在、雨量が規制値を下回ったため点検作業の準備をしています。</dd></dl>
        <p>小幡～瀬戸市役所前駅間の踏切通行不可</p>
        <p>振替輸送を実施しています。</p>
      </td></tr>
    </table>
  </div>
</body></html>
"""


def test_august_2_seto_line_keeps_important_remarks() -> None:
    alerts = parse_meitetsu_status(SETOSEN_20260802_HTML)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.startswith("名鉄 瀬戸線: 運転見合わせ / 区間: 栄町～尾張瀬戸 / 理由: 大雨による運転規制")
    assert "点検作業の準備" in alert
    assert "小幡～瀬戸市役所前駅間の踏切通行不可" in alert
    assert "振替輸送を実施" in alert


def test_august_2_seto_line_discord_priority_order() -> None:
    alerts = parse_meitetsu_status(SETOSEN_20260802_HTML)
    comment = build_railway_beta_comment(
        alerts,
        checked_at=datetime(2026, 8, 2, 19, 30, tzinfo=JST),
    )

    status_index = comment.index("運転見合わせ")
    section_index = comment.index("区間: 栄町～尾張瀬戸")
    reason_index = comment.index("理由: 大雨による運転規制")
    remarks_index = comment.index("備考:")
    assert status_index < section_index < reason_index < remarks_index
    assert "踏切通行不可" in comment
    assert "点検作業の準備" in comment
    assert "振替輸送" in comment
