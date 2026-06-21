#!/usr/bin/env python3
"""Gemma投入用プロンプトを標準出力に表示する。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
PROFILE_PATH = AI_DIR / "gemma_profile.yml"
CONTEXT_PATH = AI_DIR / "daily_context.json"
PROMPT_PATH = AI_DIR / "prompts" / "daily_brief.txt"


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return load_simple_yaml(path)

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.relative_to(ROOT)} is not a YAML mapping.")
    return data


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Read the small profile YAML subset used by this project."""
    data: dict[str, Any] = {}
    current_list: str | None = None

    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- "):
                if current_list is None:
                    raise ValueError(f"List item without a key in {path.relative_to(ROOT)}.")
                data[current_list].append(stripped[2:])
                continue
            if ":" not in stripped:
                raise ValueError(f"Unsupported YAML line in {path.relative_to(ROOT)}: {stripped}")
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                data[key] = value
                current_list = None
            else:
                data[key] = []
                current_list = key
    return data


def load_context(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path.relative_to(ROOT)} is not a JSON object.")
    return data


def main() -> int:
    profile = load_yaml(PROFILE_PATH)
    context = load_context(CONTEXT_PATH)
    brief = PROMPT_PATH.read_text(encoding="utf-8").strip()

    print(brief)
    print()
    print("## profile")
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    print()
    print("## daily_context.json")
    print(json.dumps(context, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        pass
