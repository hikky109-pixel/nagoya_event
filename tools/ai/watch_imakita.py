#!/usr/bin/env python3
"""今北産業/読めねー案件候補を検知して管理用チャンネルへ通知する。"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "logs" / "event_bot.log"
TODAY_CSV_PATH = ROOT / "logs" / "today.csv"
CHAT_MEMORY_DIR = ROOT / "data" / "ai" / "chat_memory"
NOTIFIED_PATH = ROOT / "data" / "ai" / "imakita_notified.json"

KEYWORDS = [
    "今北産業",
    "今来た",
    "三行で",
    "3行で",
    "読めねー案件",
    "OCR失敗",
    "手動確認",
]

sys.path.insert(0, str(ROOT))
import config  # noqa: E402


def get_setting(name: str) -> str:
    value = getattr(config, name, os.getenv(name, ""))
    return value.strip() if isinstance(value, str) else str(value).strip()


def load_notified() -> set[str]:
    if not NOTIFIED_PATH.exists():
        return set()
    try:
        with NOTIFIED_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def save_notified(keys: set[str]) -> None:
    NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NOTIFIED_PATH.open("w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, ensure_ascii=False, indent=2)
        f.write("\n")


def find_keyword(text: str) -> str:
    return next((keyword for keyword in KEYWORDS if keyword in text), "")


def digest_key(source: str, line_id: str, text: str) -> str:
    digest = hashlib.sha256(f"{source}\n{line_id}\n{text}".encode("utf-8")).hexdigest()
    return f"{source}:{line_id}:{digest[:16]}"


def scan_text_lines(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    matches: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for index, line in enumerate(lines, start=1):
        keyword = find_keyword(line)
        if keyword:
            source = str(path.relative_to(ROOT))
            matches.append(
                {
                    "source": source,
                    "line_id": str(index),
                    "keyword": keyword,
                    "content": line,
                    "key": digest_key(source, str(index), line),
                }
            )
    return matches


def scan_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    matches: list[dict[str, str]] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for index, row in enumerate(reader, start=2):
                text = "\n".join(str(value) for value in row.values() if value)
                keyword = find_keyword(text)
                if keyword:
                    source = str(path.relative_to(ROOT))
                    matches.append(
                        {
                            "source": source,
                            "line_id": str(index),
                            "keyword": keyword,
                            "content": text,
                            "key": digest_key(source, str(index), text),
                        }
                    )
    except (OSError, csv.Error):
        return []
    return matches


def scan_chat_memory(directory: Path) -> list[dict[str, str]]:
    if not directory.exists():
        return []
    matches: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, list):
            continue
        for index, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("message", ""))
            keyword = find_keyword(text)
            if not keyword:
                continue
            source = str(path.relative_to(ROOT))
            line_id = str(item.get("timestamp") or index)
            matches.append(
                {
                    "source": source,
                    "line_id": line_id,
                    "keyword": keyword,
                    "content": text,
                    "key": digest_key(source, line_id, text),
                }
            )
    return matches


def build_message(match: dict[str, str]) -> str:
    bot_id = get_setting("DISCORD_BOT_ID") or "1518154055455871036"
    return "\n".join(
        [
            f"<@{bot_id}>",
            "",
            "今北産業",
            "",
            "source:",
            match["source"],
            "",
            "keyword:",
            match["keyword"],
            "",
            "内容:",
            match["content"][:1200],
            "",
            "確認お願いします😇",
        ]
    )


def target_channel_id() -> str:
    test_channel = get_setting("GEMMA_CHANNEL_TEST")
    admin_channel = get_setting("GEMMA_CHANNEL_ADMIN")
    if platform.system() == "Darwin":
        return test_channel or admin_channel
    return admin_channel or test_channel


def post_discord(content: str) -> tuple[bool, str]:
    token = get_setting("DISCORD_BOT_TOKEN")
    channel_id = target_channel_id()
    if not token or not channel_id:
        return False, "Gemma課長TEST/管理用Discord設定未完了"

    import requests

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json={"content": content}, timeout=15)
    except requests.RequestException as exc:
        return False, str(exc)
    if 200 <= response.status_code < 300:
        return True, "sent"
    return False, f"HTTP{response.status_code} {response.text}"


def collect_matches() -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    matches.extend(scan_text_lines(LOG_PATH))
    matches.extend(scan_csv(TODAY_CSV_PATH))
    matches.extend(scan_chat_memory(CHAT_MEMORY_DIR))
    return matches


def main() -> int:
    notified = load_notified()
    matches = [match for match in collect_matches() if match["key"] not in notified]
    if not matches:
        print("今北産業検知なし")
        return 0

    sent = 0
    for match in matches:
        ok, status = post_discord(build_message(match))
        if ok:
            sent += 1
            notified.add(match["key"])
        else:
            print(status)
            break

    save_notified(notified)
    print(f"今北産業検知: {len(matches)}")
    print(f"通知成功: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
