#!/usr/bin/env python3
"""自然言語をGemmaで分類し、担当班チャンネルへ投稿するルーター。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
DATA_DIR = ROOT / "data"
CONTEXT_PATH = AI_DIR / "daily_context.json"
REPORT_PATH = AI_DIR / "gemma_report.txt"
WEATHER_PATH = AI_DIR / "weather_summary.json"
RAILWAY_PATH = AI_DIR / "railway_summary.json"
DRAGONS_PATH = AI_DIR / "dragons_log.yml"
INCIDENTS_DIR = DATA_DIR / "incidents"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

CATEGORIES = {"weather", "road", "railway", "dragons", "event", "food", "chat", "unknown"}
DEFAULT_CHANNELS = {
    "railway": "",
    "road": "",
    "event": "",
    "nagoya": "",
    "food": "",
    "main": "",
}
CATEGORY_TO_CHANNEL = {
    "weather": "main",
    "road": "road",
    "railway": "railway",
    "dragons": "event",
    "event": "event",
    "food": "food",
    "chat": "main",
    "unknown": "main",
}
IGNORE_CHANNELS = {"利用規約", "自己紹介"}
LISTEN_ONLY_CHANNELS = {"バーボンハウス🥃"}

sys.path.insert(0, str(ROOT))
import config  # noqa: E402


def get_setting(name: str) -> str:
    value = getattr(config, name, os.getenv(name, ""))
    return value.strip() if isinstance(value, str) else str(value).strip()


def get_token() -> str:
    return get_setting("DISCORD_BOT_TOKEN")


def get_channels() -> dict[str, str]:
    channels = dict(DEFAULT_CHANNELS)
    configured = getattr(config, "GEMMA_CHANNELS", None) or getattr(config, "CHANNELS", None)
    if isinstance(configured, dict):
        for key, value in configured.items():
            if key in channels and value:
                channels[key] = str(value).strip()

    env_names = {
        "railway": "GEMMA_CHANNEL_RAILWAY",
        "road": "GEMMA_CHANNEL_ROAD",
        "event": "GEMMA_CHANNEL_EVENT",
        "nagoya": "GEMMA_CHANNEL_NAGOYA",
        "food": "GEMMA_CHANNEL_FOOD",
        "main": "GEMMA_CHANNEL_MAIN",
    }
    for key, name in env_names.items():
        value = get_setting(name)
        if value:
            channels[key] = value

    if not channels["main"]:
        channels["main"] = get_setting("GEMMA_DISCORD_CHANNEL_ID")
    return channels


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return load_simple_yaml(path)

    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_simple_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped == "[]":
        return []
    if stripped == "{}":
        return {}

    data: dict[str, Any] = {}
    current_list: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            if current_list is not None:
                data[current_list].append(line[2:])
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if value:
            data[key] = value
            current_list = None
        else:
            data[key] = []
            current_list = key
    return data


def load_incidents() -> list[dict[str, Any]]:
    if not INCIDENTS_DIR.exists():
        return []
    incidents: list[dict[str, Any]] = []
    for path in sorted(INCIDENTS_DIR.glob("*.yml")):
        data = load_yaml(path)
        if data is not None:
            incidents.append({"source_file": str(path.relative_to(ROOT)), "data": data})
    return incidents


def call_ollama(prompt: str, num_predict: int = 160) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": num_predict},
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


def classify_message(message: str) -> str | None:
    prompt = f"""あなたはDiscord運行管理部長の分類器です。
次の発言を1語だけで分類してください。

分類:
weather, road, railway, dragons, event, food, chat, unknown

基準:
- 天気、雨、気温: weather
- 事故、通行止め、渋滞、オービス、可搬式: road
- JR、新幹線、名鉄、地下鉄、あおなみ線、バス: railway
- ドラゴンズ、中日、バンテリンの試合: dragons
- ライブ、IGアリーナ、御園座、相撲、人流、需要: event
- ご飯、店、飯、かつや、ラーメン: food
- 雑談、相談、あいさつ: chat
- 判断不能: unknown

発言:
{message}

分類だけ:
"""
    response = call_ollama(prompt, num_predict=8)
    if response is None:
        return None
    normalized = response.strip().lower().split()[0].strip("。、.・`\"'")
    return normalized if normalized in CATEGORIES else "unknown"


def category_source(category: str) -> dict[str, Any]:
    context = load_json(CONTEXT_PATH)
    if category == "weather":
        return {"weather": load_json(WEATHER_PATH)}
    if category == "road":
        road_events = context.get("road_events", [])
        orbis = context.get("orbis", [])
        return {
            "road_events_count": len(road_events) if isinstance(road_events, list) else 0,
            "orbis_count": len(orbis) if isinstance(orbis, list) else 0,
        }
    if category == "railway":
        return {"railway": load_json(RAILWAY_PATH), "incidents": load_incidents()}
    if category == "dragons":
        return {"dragons": load_yaml(DRAGONS_PATH) or "ドラゴンズ関連ログはありません"}
    if category == "event":
        events = context.get("events", [])
        return {"events_count": len(events) if isinstance(events, list) else 0, "gemma_report": load_text(REPORT_PATH)}
    if category == "food":
        return {"note": "飯テロ班。おすすめ候補は断定せずcandidate扱い。"}
    return {"daily_context": context, "gemma_report": load_text(REPORT_PATH)}


def build_reply(message: str, category: str, source: dict[str, Any]) -> str | None:
    source_json = json.dumps(source, ensure_ascii=False, indent=2)
    prompt = f"""あなたはジェンマ課長です。
Discordの自然言語発言に、担当班として短く返答してください。

分類: {category}

ルール:
- 3〜5行
- 箇条書き中心
- 自信がない内容は断定しない
- 候補は candidate とする
- 本番データを勝手に確定しない
- 運転再開≠復旧
- ツッコミは最大1回
- スギケツバットは毎回出さない

発言:
{message}

参照データ:
{source_json}
"""
    response = call_ollama(prompt, num_predict=180)
    return normalize_reply(response) if response is not None else None


def build_main_summary(message: str, category: str, reply: str) -> str:
    label = CATEGORY_TO_CHANNEL.get(category, "main")
    return f"🤖 ジェンマ課長: {category}班へ振り分けました（{label}）。\n{reply}"


def normalize_reply(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "・未確認です。"
    if len(lines) < 3:
        lines.extend(["・詳細は未確認です。"] * (3 - len(lines)))
    return "\n".join(lines[:5])


def trim_discord_message(text: str) -> str:
    text = text.strip() or "未確認です。"
    if len(text) <= 1900:
        return text
    return text[:1897].rstrip() + "..."


def post_discord_message(token: str, channel_id: str, content: str) -> tuple[bool, int, str]:
    import requests

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    payload = {"content": trim_discord_message(content)}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
    except requests.RequestException as exc:
        return False, 0, str(exc)
    return 200 <= response.status_code < 300, response.status_code, response.text


def route_message(message: str, source_channel_name: str = "") -> dict[str, Any]:
    if source_channel_name in IGNORE_CHANNELS or source_channel_name in LISTEN_ONLY_CHANNELS:
        return {
            "status": "ignored",
            "reason": "ignore_or_listen_only_channel",
            "category": "unknown",
            "reply": "",
        }

    category = classify_message(message)
    if category is None:
        return {"status": "gemma_not_running", "category": "unknown", "reply": ""}

    source = category_source(category)
    reply = build_reply(message, category, source)
    if reply is None:
        return {"status": "gemma_not_running", "category": category, "reply": ""}

    token = get_token()
    channels = get_channels()
    target_key = CATEGORY_TO_CHANNEL.get(category, "main")
    target_channel_id = channels.get(target_key, "")
    main_channel_id = channels.get("main", "")

    result: dict[str, Any] = {
        "status": "rendered",
        "category": category,
        "target": target_key,
        "reply": reply,
        "posted": [],
    }
    if not token or not target_channel_id:
        result["reason"] = "discord_not_configured"
        return result

    ok, status_code, body = post_discord_message(token, target_channel_id, reply)
    result["posted"].append({"channel": target_key, "ok": ok, "status_code": status_code, "body": body})

    if main_channel_id and main_channel_id != target_channel_id:
        summary = build_main_summary(message, category, reply)
        ok, status_code, body = post_discord_message(token, main_channel_id, summary)
        result["posted"].append({"channel": "main", "ok": ok, "status_code": status_code, "body": body})

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自然言語をジェンマ課長の各班へルーティングする。")
    parser.add_argument("message", nargs="*", help="分類したい自然言語メッセージ")
    parser.add_argument("--source-channel", default="", help="発言元チャンネル名")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    message = " ".join(args.message).strip()
    if not message:
        message = sys.stdin.read().strip()
    if not message:
        print("Gemma課長ルーター入力なし")
        return 0

    result = route_message(message, args.source_channel)
    if result["status"] == "gemma_not_running":
        print("Gemma4B未起動")
        return 0
    if result["status"] == "ignored":
        print("Gemma課長ルーター沈黙")
        return 0

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
