#!/usr/bin/env python3
"""チャンネル別短期記憶から1時間ごとの運行日誌を作る。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
CHAT_MEMORY_DIR = AI_DIR / "chat_memory"
HOURLY_SUMMARY_DIR = AI_DIR / "hourly_summary"
DAILY_MEMORY_DIR = AI_DIR / "daily_memory"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"
IGNORE_CHANNELS = {"利用規約", "自己紹介"}
LISTEN_ONLY_CHANNELS = {"バーボンハウス"}

sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from tools.ai import content_filter  # noqa: E402


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc).astimezone()
    return parsed.astimezone()


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def channel_name_for(channel_id: str) -> str:
    names = getattr(config, "GEMMA_CHANNEL_NAMES", {})
    if isinstance(names, dict):
        value = names.get(channel_id) or names.get(str(channel_id))
        if value:
            return str(value)

    channels = getattr(config, "GEMMA_CHANNELS", {})
    if isinstance(channels, dict):
        for name, configured_id in channels.items():
            if str(configured_id).strip() == channel_id:
                return str(name)
    return ""


def channel_rule(channel_name: str) -> str:
    if any(name in channel_name for name in IGNORE_CHANNELS):
        return "ignore"
    if any(name in channel_name for name in LISTEN_ONLY_CHANNELS):
        return "listen_only"
    return "normal"


def recent_channel_logs(since: datetime) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not CHAT_MEMORY_DIR.exists():
        return results

    for path in sorted(CHAT_MEMORY_DIR.glob("*.json")):
        channel_id = path.stem
        channel_name = channel_name_for(channel_id)
        if channel_rule(channel_name) != "normal":
            continue

        data = load_json(path)
        if not isinstance(data, list):
            continue

        recent: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if content_filter.is_filtered(str(item.get("message", ""))):
                continue
            timestamp = parse_timestamp(item.get("timestamp"))
            if timestamp is not None and timestamp >= since:
                recent.append(item)

        if recent:
            results.append(
                {
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "messages": recent,
                }
            )
    return results


def build_prompt(logs: list[dict[str, Any]]) -> str:
    source_json = json.dumps(logs, ensure_ascii=False, indent=2)
    return f"""あなたはジェンマ課長です。

Discord各チャンネルの直近1時間ログを、1日分の運行日誌へ追加するため短く要約してください。

ルール:
- 3〜5行
- 箇条書き中心
- 不明なことは断定しない
- candidate を利用
- ツッコミは最大1回
- ログが少ない時は異常なしと断定しない

直近1時間ログ:
{source_json}
"""


def call_ollama(prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 220},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None

    data = json.loads(response_body)
    if not isinstance(data, dict):
        return ""
    return str(data.get("response", "")).strip()


def normalize_summary(text: str) -> str:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith(("了解しました", "本日運行日誌"))
    ]
    if not lines:
        return "・直近1時間の要約対象ログは未確認です。"
    if len(lines) < 3:
        lines.extend(["・詳細は未確認です。"] * (3 - len(lines)))
    normalized = [line if line.startswith(("・", "-", "*")) else f"・{line}" for line in lines[:5]]
    return "\n".join(normalized)


def empty_log_summary() -> str:
    return "\n".join(
        [
            "・直近1時間の要約対象ログはありません。",
            "・チャンネル会話の変化は未確認です。",
            "・candidate: 次回ログ発生時に日誌へ追記します。",
        ]
    )


def append_daily_memory(date_key: str, summary_item: dict[str, Any]) -> None:
    DAILY_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_MEMORY_DIR / f"{date_key}.json"
    data = load_json(path)
    if not isinstance(data, dict):
        data = {"date": date_key, "summaries": []}
    summaries = data.get("summaries")
    if not isinstance(summaries, list):
        summaries = []
        data["summaries"] = summaries
    summaries.append(summary_item)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    current = now_local()
    since = current - timedelta(hours=1)
    logs = recent_channel_logs(since)

    if not logs:
        if call_ollama("起動確認") is None:
            print("Gemma4B未起動")
            return 0
        summary_text = empty_log_summary()
    else:
        prompt = build_prompt(logs)
        summary = call_ollama(prompt)
        if summary is None:
            print("Gemma4B未起動")
            return 0
        summary_text = normalize_summary(summary)

    if summary_text is None:
        print("Gemma4B未起動")
        return 0

    channel_ids = [item["channel_id"] for item in logs]
    channel_names = [item["channel_name"] for item in logs if item["channel_name"]]
    summary_item = {
        "timestamp": current.isoformat(timespec="seconds"),
        "channel_id": ",".join(channel_ids) if channel_ids else "",
        "channel_name": ",".join(channel_names) if channel_names else "",
        "summary": summary_text,
    }

    HOURLY_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    date_key = current.strftime("%Y-%m-%d")
    hour_key = current.strftime("%Y-%m-%d_%H")
    hourly_path = HOURLY_SUMMARY_DIR / f"{hour_key}.json"
    with hourly_path.open("w", encoding="utf-8") as f:
        json.dump(summary_item, f, ensure_ascii=False, indent=2)
        f.write("\n")

    append_daily_memory(date_key, summary_item)

    print(f"wrote: {hourly_path.relative_to(ROOT)}")
    print(f"wrote: {(DAILY_MEMORY_DIR / f'{date_key}.json').relative_to(ROOT)}")
    print(f"channels: {len(logs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
