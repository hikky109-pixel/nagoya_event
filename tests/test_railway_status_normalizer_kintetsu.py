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
                "cause": "大雨",
                "top_page_lines": ["名古屋線"],
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
    assert alerts[0] == (
        "近鉄 名古屋線: 奈良線の大雨の影響で、"
        "近鉄名古屋線の一部列車に遅れ・運休が発生しています。"
    )
    assert (
        "railway_normalized: operator=近鉄 line=名古屋線 "
        "status=遅れ・運休 accepted=true"
    ) in capsys.readouterr().out


def test_kintetsu_detail_record_rejects_non_target_line(capsys) -> None:
    snapshot = _kintetsu_snapshot()
    snapshot["records"][0]["top_page_lines"] = ["奈良線"]

    assert normalizer._normalize_kintetsu_result([], snapshot) == []
    assert (
        "accepted=false reason=top_page_target_line_not_found"
        in capsys.readouterr().out
    )


def test_kintetsu_rejects_nagoya_text_when_top_page_line_is_osaka(capsys) -> None:
    snapshot = {
        "records": [
            {
                "title": "大阪線 一部運休",
                "top_page_lines": ["大阪線"],
                "main_line": "大阪線",
                "affected_lines": ["名古屋線", "大阪線", "奈良線"],
                "cause": "停電",
                "body_text": (
                    "大阪線は、名古屋線で発生した停電の影響により、"
                    "大阪上本町～大和八木間で遅れと一部の列車が運休しています。"
                ),
            }
        ]
    }

    assert normalizer._normalize_kintetsu_result([], snapshot) == []
    assert (
        "line=大阪線 status=遅れ・運休 accepted=false "
        "reason=top_page_target_line_not_found"
    ) in capsys.readouterr().out


def test_kintetsu_direct_incident_mentions_location_and_cause() -> None:
    snapshot = {
        "records": [
            {
                "top_page_lines": ["名古屋線"],
                "top_page_status": "一部運休",
                "origin_line": "名古屋線",
                "origin_location": "江戸橋駅構内",
                "cause": "車両故障",
                "status": "一部運休",
                "direct": True,
                "body_text": (
                    "名古屋線は、江戸橋駅構内で発生した車両故障のため、"
                    "近鉄名古屋～津新町間で一部の列車が運休しています。"
                ),
            }
        ]
    }

    assert normalizer._normalize_kintetsu_result([], snapshot) == [
        "近鉄 名古屋線: 近鉄名古屋線の江戸橋駅構内で車両故障が発生し、"
        "列車に運休が発生しています。"
    ]


def test_kintetsu_indirect_real_nara_case_mentions_origin_line() -> None:
    snapshot = {
        "records": [
            {
                "top_page_lines": ["名古屋線"],
                "top_page_status": "遅延",
                "origin_line": "奈良線",
                "origin_location": "富雄駅構内",
                "cause": "人身事故",
                "direct": False,
                "affected_lines": ["奈良線", "京都線", "大阪線", "名古屋線"],
                "body_text": (
                    "奈良線は、富雄駅構内で発生した人身事故のため、"
                    "遅れと一部の列車が運休しています。 "
                    "名古屋線 近鉄名古屋～伊勢中川間で遅れが出ています。"
                ),
            }
        ]
    }

    assert normalizer._normalize_kintetsu_result([], snapshot) == [
        "近鉄 名古屋線: 奈良線の人身事故の影響で、"
        "近鉄名古屋線の一部列車に遅れが発生しています。"
    ]


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
