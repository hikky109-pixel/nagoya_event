import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai import railway_status_normalizer as normalizer  # noqa: E402


def _kintetsu_snapshot() -> dict:
    return {
        "records": [
            {
                "title": "奈良線 運転見合わせ",
                "main_line": "奈良線",
                "affected_lines": ["奈良線", "名古屋線"],
                "body_text": (
                    "奈良線は大雨のため運転を見合わせています。 "
                    "影響線区：名古屋線で一部の列車が運休しています。 "
                    "名古屋線 近鉄名古屋～伊勢中川間で遅れています。"
                ),
            }
        ]
    }


def test_kintetsu_detail_record_adds_nagoya_line_alert(capsys) -> None:
    alerts = normalizer._normalize_kintetsu_result([], _kintetsu_snapshot())

    assert len(alerts) == 1
    assert alerts[0].startswith("近鉄 名古屋線:")
    assert "運休" in alerts[0]
    assert (
        "railway_normalized: operator=近鉄 line=名古屋線 "
        "status=運休 accepted=true"
    ) in capsys.readouterr().out


def test_kintetsu_detail_record_rejects_non_target_line(capsys) -> None:
    snapshot = _kintetsu_snapshot()
    snapshot["records"][0]["affected_lines"] = ["奈良線"]

    assert normalizer._normalize_kintetsu_result([], snapshot) == []
    assert "accepted=false reason=target_line_not_affected" in capsys.readouterr().out


def test_all_railway_snapshot_keeps_other_operators_and_adds_kintetsu(monkeypatch) -> None:
    monkeypatch.setattr(normalizer, "normalize_johoku_status", lambda: ["城北線: 遅れ"])
    monkeypatch.setattr(normalizer, "normalize_aonami_status_snapshot", lambda: ([], {}, {}, {}))
    monkeypatch.setattr(normalizer, "normalize_jrc_zairai_status_snapshot", lambda: (["JR東海在来線 中央線: 遅れ"], {}))
    monkeypatch.setattr(normalizer, "normalize_kintetsu_status", lambda: ["近鉄 名古屋線: 一部列車が運休"])
    monkeypatch.setattr(normalizer, "normalize_linimo_status", lambda: [])
    monkeypatch.setattr(normalizer, "normalize_nagoya_subway_status", lambda: ["名古屋市営地下鉄 東山線: 遅れ"])
    monkeypatch.setattr(normalizer, "normalize_yutorito_status", lambda: [])
    monkeypatch.setattr(normalizer, "normalize_meitetsu_status_snapshot", lambda: (["名鉄 名古屋本線: 遅れ"], {}, {}, {}))
    monkeypatch.setattr(normalizer, "normalize_jrc_shinkansen_status_snapshot", lambda: ([], {}))

    alerts, _updated, _urls, _levels = normalizer.get_all_railway_alerts_snapshot()

    assert "近鉄 名古屋線: 一部列車が運休" in alerts
    assert "JR東海在来線 中央線: 遅れ" in alerts
    assert "名鉄 名古屋本線: 遅れ" in alerts
    assert "名古屋市営地下鉄 東山線: 遅れ" in alerts
