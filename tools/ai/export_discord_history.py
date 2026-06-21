#!/usr/bin/env python3
"""Discordの過去ログをGemma/Oracle用素材としてJSONL保存する。"""

from __future__ import annotations

import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "data" / "ai" / "discord_history"
DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_MESSAGES_PER_CHANNEL = 1000

TARGET_CHANNEL_KEYWORDS = (
    "管理用",
    "イベント",
    "道路交通",
    "公共交通",
    "名古屋駅入構",
    "おすすめご飯",
    "test",
)
IGNORE_CHANNEL_KEYWORDS = ("利用規約", "自己紹介")
LISTEN_ONLY_CHANNEL_KEYWORDS = ("バーボンハウス",)

sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from tools.ai import content_filter  # noqa: E402
from tools.ai.build_case_memory import is_gemma_generated  # noqa: E402


def get_setting(name: str) -> str:
    value = getattr(config, name, "")
    return value.strip() if isinstance(value, str) else str(value).strip()


def today_key() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }


def channel_is_ignored(name: str) -> bool:
    return any(keyword in name for keyword in IGNORE_CHANNEL_KEYWORDS + LISTEN_ONLY_CHANNEL_KEYWORDS)


def channel_is_target(name: str) -> bool:
    return any(keyword in name for keyword in TARGET_CHANNEL_KEYWORDS)


def get_json(url: str, token: str, params: dict[str, Any] | None = None) -> tuple[Any, str]:
    import requests

    try:
        response = requests.get(url, headers=headers(token), params=params, timeout=20)
    except requests.RequestException as exc:
        return None, str(exc)
    if not (200 <= response.status_code < 300):
        return None, f"HTTP{response.status_code} {response.text}"
    try:
        return response.json(), ""
    except ValueError as exc:
        return None, str(exc)


def fetch_channels(token: str, guild_id: str, all_normal: bool = False) -> list[dict[str, Any]]:
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/channels"
    data, error = get_json(url, token)
    if error or not isinstance(data, list):
        print(f"Discordチャンネル取得失敗: {error}")
        return []

    channels: list[dict[str, Any]] = []
    for channel in data:
        if not isinstance(channel, dict):
            continue
        name = str(channel.get("name", ""))
        if channel.get("type") != 0:
            continue
        if channel_is_ignored(name):
            continue
        if all_normal or channel_is_target(name):
            channels.append(channel)
    return channels


def fetch_messages(token: str, channel_id: str, limit: int = MAX_MESSAGES_PER_CHANNEL) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    before: str | None = None
    while len(messages) < limit:
        batch_limit = min(100, limit - len(messages))
        params: dict[str, Any] = {"limit": batch_limit}
        if before:
            params["before"] = before
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        data, error = get_json(url, token, params=params)
        if error:
            print(f"Discordメッセージ取得失敗 channel={channel_id}: {error}")
            break
        if not isinstance(data, list) or not data:
            break
        messages.extend(item for item in data if isinstance(item, dict))
        before = str(data[-1].get("id", ""))
        if len(data) < batch_limit:
            break
    return messages


def normalize_message(message: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any] | None:
    content = str(message.get("content", ""))
    author = message.get("author", {})
    author_name = str(author.get("username", "")) if isinstance(author, dict) else ""
    if is_gemma_generated(author_name, content):
        return None
    if content_filter.is_filtered(content):
        return None

    referenced = message.get("referenced_message")
    attachments = message.get("attachments", [])
    if not isinstance(attachments, list):
        attachments = []

    return {
        "timestamp": message.get("timestamp", ""),
        "channel_id": str(channel.get("id", "")),
        "channel_name": str(channel.get("name", "")),
        "author": author_name,
        "content": content,
        "attachments": [
            {
                "filename": str(item.get("filename", "")),
                "url": str(item.get("url", "")),
                "content_type": str(item.get("content_type", "")),
            }
            for item in attachments
            if isinstance(item, dict)
        ],
        "message_id": str(message.get("id", "")),
        "reply_to": str(referenced.get("id", "")) if isinstance(referenced, dict) and referenced else "",
    }


def write_jsonl(channel: dict[str, Any], rows: list[dict[str, Any]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{today_key()}_{channel.get('id', '')}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discordの過去ログをGemma/Oracle用素材としてJSONL保存する。")
    parser.add_argument("--all-normal", action="store_true", help="ignore/listen_only以外の全テキストチャンネルを対象にする。")
    parser.add_argument("--limit", type=int, default=MAX_MESSAGES_PER_CHANNEL, help="各チャンネルの取得件数。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = get_setting("DISCORD_BOT_TOKEN")
    guild_id = get_setting("GEMMA_GUILD_ID")
    if not token or not guild_id:
        print("Discord履歴取得設定未完了")
        return 0

    channels = fetch_channels(token, guild_id, all_normal=args.all_normal)
    if not channels:
        print("Discord履歴対象チャンネルなし")
        return 0

    exported = 0
    for channel in channels:
        messages = fetch_messages(token, str(channel.get("id", "")), limit=max(1, args.limit))
        rows = [
            row
            for message in messages
            if (row := normalize_message(message, channel)) is not None
        ]
        path = write_jsonl(channel, rows)
        exported += 1
        print(f"wrote: {path.relative_to(ROOT)} rows={len(rows)}")

    print(f"discord_history_channels: {exported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
