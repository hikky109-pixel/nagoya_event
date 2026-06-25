import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.get_jrc_shinkansen_plan_notice import parse_plan_notice_payload  # noqa: E402


def test_parse_plan_notice_extracts_next_update_text() -> None:
    result = parse_plan_notice_payload(
        {
            "screen": {
                "message": (
                    "台風接近に伴う今後の運転計画について<br><br>"
                    "次回のお知らせは、６月２６日（金）１３時００分頃を"
                    "予定しています。<br><br>きっぷ等の取扱い"
                )
            }
        }
    )

    assert result["next_update_text"] == (
        "次回のお知らせは、６月２６日（金）１３時００分頃を予定しています。"
    )
    assert "台風接近に伴う今後の運転計画" in result["message_text"]
    assert len(result["content_hash"]) == 64
