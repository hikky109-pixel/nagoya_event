#!/usr/bin/env python3
"""ジェンマ課長日報パイプラインを一発実行する。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [
    ROOT / "tools" / "ai" / "build_daily_context.py",
    ROOT / "tools" / "ai" / "build_gemma_brief.py",
    ROOT / "tools" / "ai" / "render_gemma_report.py",
    ROOT / "tools" / "ai" / "send_gemma_report_api.py",
]


def run_step(script: Path) -> None:
    print(f"=== {script.relative_to(ROOT)} ===", flush=True)
    subprocess.run([sys.executable, str(script)], cwd=ROOT, check=True)


def main() -> int:
    for script in SCRIPTS:
        run_step(script)
    print("Gemma課長パイプライン完了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
