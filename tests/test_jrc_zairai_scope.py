import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.get_jrc_zairai_status import _is_target_jrc_section  # noqa: E402
from tools.ai.jrc_zairai_targets import jrc_target_line_display  # noqa: E402


def test_tokaido_atami_to_toyohashi_is_out_of_scope() -> None:
    assert _is_target_jrc_section("東海道線", "熱海", "豊橋") is False


def test_tokaido_toyohashi_to_maibara_is_in_scope() -> None:
    assert _is_target_jrc_section("東海道線", "豊橋", "米原") is True


def test_tokaido_single_toyohashi_is_in_scope() -> None:
    assert _is_target_jrc_section("東海道線", "豊橋", "") is True


def test_chuo_line_display_is_plain_line_name() -> None:
    assert jrc_target_line_display("中央線(名古屋～中津川)") == "中央線"
