#!/usr/bin/env python3
"""JR東海在来線の運行情報を複数理由対応で取得する。"""

from __future__ import annotations

import sys
from pathlib import Path


AI_DIR = Path(__file__).resolve().parents[1] / "ai"
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from get_jrc_zairai_status import get_jrc_zairai_status  # noqa: E402


def get_jr_central_alerts(line_name: str | None = None) -> dict[str, list[str]] | list[str] | None:
    return get_jrc_zairai_status(line_name)


if __name__ == "__main__":
    print(get_jr_central_alerts())
