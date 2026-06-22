#!/usr/bin/env python3
"""Gemma課長へ渡す軽量コンテキストを読む。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
SUMMARY_PATH = AI_DIR / "summary.txt"
FEEDBACK_SUMMARY_PATH = AI_DIR / "feedback_summary.txt"


def load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_light_context() -> str:
    summary = load_text(SUMMARY_PATH)
    feedback = load_text(FEEDBACK_SUMMARY_PATH)
    sections: list[str] = []
    if summary:
        sections.append(f"課長用虎の巻:\n{summary}")
    if feedback:
        sections.append(f"フィードバック要約:\n{feedback}")
    return "\n\n".join(sections) if sections else "軽量コンテキストなし"
