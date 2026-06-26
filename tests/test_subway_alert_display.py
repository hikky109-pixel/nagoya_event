import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.get_nagoya_subway_status import save_subway_debug_dump  # noqa: E402
from tools.ai.run_gemma_ollama import build_railway_beta_comment  # noqa: E402


JST = timezone(timedelta(hours=9))


def test_subway_alert_body_meitetsu_reference_does_not_change_provider() -> None:
    alert = (
        "名古屋市営地下鉄 鶴舞線: 遅延 / 全線 / その他 / "
        "名鉄犬山線からの到着遅れにより、一部列車に遅れが発生しています。"
    )

    comment = build_railway_beta_comment(
        [alert],
        checked_at=datetime(2026, 6, 26, 9, 30, tzinfo=JST),
    )

    assert "名古屋市営地下鉄 鶴舞線" in comment
    assert "🔗 名古屋市営地下鉄" in comment
    assert "https://www.kotsu.city.nagoya.jp/rp/emergency/" in comment
    assert "🔵 名鉄" not in comment
    assert "https://top.meitetsu.co.jp/em/" not in comment
    assert "名鉄犬山線からの到着遅れ" in comment


def test_meitetsu_alert_still_uses_meitetsu_source() -> None:
    alert = "名鉄 犬山線: 遅延 / 犬山線で列車に遅れが発生しています。"

    comment = build_railway_beta_comment(
        [alert],
        checked_at=datetime(2026, 6, 26, 9, 30, tzinfo=JST),
    )

    assert "名鉄" in comment
    assert "対象路線:" in comment
    assert "・犬山線" in comment
    assert "https://top.meitetsu.co.jp/em/" in comment
    assert "www.kotsu.city.nagoya.jp" not in comment


def test_subway_debug_dump_saves_latest_and_history(tmp_path: Path) -> None:
    raw_status_dict = {
        "鶴舞線": {
            "status": "遅延",
            "section": "全線",
            "cause": "その他",
            "message": "名鉄犬山線からの到着遅れ",
        },
        "東山線": {
            "status": "平常運行",
            "section": "",
            "cause": "",
            "message": "",
        },
    }
    abnormal_records = {"鶴舞線": raw_status_dict["鶴舞線"]}

    snapshot = save_subway_debug_dump(
        raw_status_dict,
        abnormal_records,
        debug_dir=tmp_path,
        now=datetime(2026, 6, 26, 9, 30, tzinfo=JST),
    )

    latest = tmp_path / "latest.json"
    history = tmp_path / "20260626_093000.json"
    assert latest.exists()
    assert history.exists()
    assert len(snapshot["hash"]) == 64

    saved = json.loads(latest.read_text(encoding="utf-8"))
    assert saved["raw_status_dict"] == raw_status_dict
    assert saved["abnormal_records"] == abnormal_records
    assert saved["hash"] == snapshot["hash"]
