#!/usr/bin/env python3
"""話題ごとの投稿可能チャンネルを判定する軽量スコープ管理。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOPIC_SCOPE_PATH = ROOT / "data" / "ai" / "topic_scope.yml"


def load_topic_scope(path: Path = TOPIC_SCOPE_PATH) -> dict[str, dict[str, list[str]]]:
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return load_simple_topic_scope(path)

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return normalize_topic_scope(data)


def load_simple_topic_scope(path: Path) -> dict[str, dict[str, list[str]]]:
    scope: dict[str, dict[str, list[str]]] = {}
    current_topic: str | None = None
    in_channels = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not raw_line.startswith((" ", "\t")) and stripped.endswith(":"):
            current_topic = stripped[:-1].strip()
            scope[current_topic] = {"channels": []}
            in_channels = False
            continue

        if current_topic is None:
            continue

        if stripped == "channels:":
            in_channels = True
            continue

        if in_channels and stripped.startswith("- "):
            channel_name = stripped[2:].strip()
            if channel_name:
                scope[current_topic]["channels"].append(channel_name)

    return scope


def normalize_topic_scope(data: Any) -> dict[str, dict[str, list[str]]]:
    if not isinstance(data, dict):
        return {}

    scope: dict[str, dict[str, list[str]]] = {}
    for topic, config in data.items():
        if not isinstance(topic, str) or not isinstance(config, dict):
            continue

        channels = config.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        scope[topic] = {
            "channels": [channel for channel in channels if isinstance(channel, str)]
        }
    return scope


def topic_allowed(topic: str, channel_name: str) -> bool:
    scope = load_topic_scope()
    config = scope.get(topic)
    if config is None:
        return True
    return channel_name in config.get("channels", [])
