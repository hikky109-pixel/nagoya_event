#!/usr/bin/env python3
"""DiscordコマンドからGemma 4Bのジェンマ課長返答を行うBot。"""

from __future__ import annotations

import json
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
DRAGONS_PATH = AI_DIR / "dragons_log.yml"
RAILWAY_PATH = AI_DIR / "railway_summary.json"
INCIDENTS_DIR = DATA_DIR / "incidents"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"
COMMANDS = {"!brief", "!weather", "!dragons", "!incident", "!road"}
IGNORE_CHANNELS = {"利用規約", "自己紹介"}
LISTEN_ONLY_CHANNELS = {"バーボンハウス"}
CHAT_CLASSIFICATIONS = {"weather", "road", "railway", "event", "food", "unknown"}

sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from tools.ai import chat_memory  # noqa: E402
from tools.ai import content_filter  # noqa: E402


def get_token() -> str:
    token = getattr(config, "DISCORD_BOT_TOKEN", "")
    return token.strip() if isinstance(token, str) else str(token).strip()


def get_guild_id() -> int | None:
    value = getattr(config, "GEMMA_GUILD_ID", "")
    value = value.strip() if isinstance(value, str) else str(value).strip()
    return int(value) if value.isdigit() else None


def gemma_is_running() -> bool:
    payload = {
        "model": MODEL,
        "prompt": "起動確認",
        "stream": False,
        "options": {"num_predict": 1},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


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


def load_incidents() -> list[Any]:
    if not INCIDENTS_DIR.exists():
        return []
    incidents: list[Any] = []
    for path in sorted(INCIDENTS_DIR.glob("*.yml")):
        data = load_yaml(path)
        if data is not None:
            incidents.append({"source_file": str(path.relative_to(ROOT)), "data": data})
    return incidents


def build_prompt(command: str, source: Any, history_text: str = "") -> str:
    source_json = json.dumps(source, ensure_ascii=False, indent=2)
    return f"""あなたはジェンマ課長です。

Discordコマンド {command} への短い返答を作ってください。

ルール:
- 3〜5行
- 箇条書き中心
- 自信がない内容は断定しない
- 候補は candidate とする
- 本番データを勝手に確定しない
- 運転再開≠復旧
- ツッコミは最大1回
- スギケツバットは毎回出さない

入力:
{source_json}

現在のチャンネルの直近20件:
{history_text or "履歴なし"}
"""


def call_ollama(prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
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


def classify_channel_mode(channel_name: str) -> str:
    name = channel_name.lower()
    if "公共交通" in channel_name:
        return "railway"
    if "道路交通" in channel_name:
        return "road"
    if "イベント" in channel_name or "利用者需要" in channel_name or "ドラゴンズ" in channel_name:
        return "event"
    if "名古屋駅" in channel_name or "入構" in channel_name:
        return "nagoya"
    if "ご飯" in channel_name or "飯屋" in channel_name:
        return "food"
    if "トイレ" in channel_name or "施設" in channel_name or "付け場" in channel_name:
        return "facility"
    if "業務" in channel_name:
        return "work"
    if "test" in name:
        return "test"
    if "雑談" in channel_name:
        return "chat"
    return "chat"


def channel_rule(channel_name: str) -> str:
    if any(name in channel_name for name in IGNORE_CHANNELS):
        return "ignore"
    if any(name in channel_name for name in LISTEN_ONLY_CHANNELS):
        return "listen_only"
    return "normal"


def classify_message_text(message_text: str) -> str | None:
    prompt = f"""あなたはジェンマ課長の分類器です。
次のDiscord発言を1語だけで分類してください。

分類:
weather, road, railway, event, food, unknown

基準:
- 天気、雨、気温: weather
- 事故、通行止め、渋滞、オービス、可搬式: road
- JR、新幹線、名鉄、地下鉄、あおなみ線、バス: railway
- ライブ、イベント、ドラゴンズ、バンテリン、IGアリーナ、御園座、相撲、人流、需要: event
- ご飯、飯屋、店、かつや、ラーメン: food
- 判断不能: unknown

発言:
{message_text}

分類だけ:
"""
    response = call_ollama(prompt)
    if response is None:
        return None
    category = response.strip().lower().split()[0].strip("。、.・`\"'")
    return category if category in CHAT_CLASSIFICATIONS else "unknown"


def source_for_command(command: str) -> Any:
    if command == "!brief":
        return {
            "daily_context": load_json(CONTEXT_PATH),
            "gemma_report": load_text(REPORT_PATH),
        }
    if command == "!weather":
        return load_json(WEATHER_PATH)
    if command == "!dragons":
        dragons = load_yaml(DRAGONS_PATH)
        return dragons if dragons else {"message": "ドラゴンズ関連ログはありません"}
    if command == "!incident":
        return {"incidents": load_incidents()}
    if command == "!road":
        context = load_json(CONTEXT_PATH)
        road_events = context.get("road_events", [])
        orbis = context.get("orbis", [])
        return {
            "road_events_count": len(road_events) if isinstance(road_events, list) else 0,
            "orbis_count": len(orbis) if isinstance(orbis, list) else 0,
        }
    return {}


def source_for_mode(mode: str) -> Any:
    context = load_json(CONTEXT_PATH)
    if mode == "weather":
        return load_json(WEATHER_PATH)
    if mode == "road":
        road_events = context.get("road_events", [])
        orbis = context.get("orbis", [])
        return {
            "road_events_count": len(road_events) if isinstance(road_events, list) else 0,
            "orbis_count": len(orbis) if isinstance(orbis, list) else 0,
        }
    if mode == "railway":
        return {
            "railway": load_json(RAILWAY_PATH),
            "incidents": load_incidents(),
        }
    if mode == "event":
        events = context.get("events", [])
        return {
            "events_count": len(events) if isinstance(events, list) else 0,
            "dragons": load_yaml(DRAGONS_PATH) or {},
            "gemma_report": load_text(REPORT_PATH),
        }
    if mode == "food":
        return {"note": "飯テロ班。おすすめ候補はcandidate扱い。"}
    if mode == "nagoya":
        return {"note": "名古屋駅入構状況。現場ログは未接続。", "gemma_report": load_text(REPORT_PATH)}
    if mode == "facility":
        return {"note": "施設、トイレ、付け場関連。未確認情報はcandidate扱い。"}
    if mode == "work":
        return {"note": "業務チャンネル。断定せず短く補助。"}
    if mode == "test":
        return {"note": "testチャンネル。短く動作確認。"}
    return {
        "daily_context": context,
        "gemma_report": load_text(REPORT_PATH),
    }


def build_natural_prompt(message_text: str, mode: str, source: Any, history_text: str = "") -> str:
    source_json = json.dumps(source, ensure_ascii=False, indent=2)
    return f"""あなたはジェンマ課長です。

Discordの通常発言へ、担当班モードに合わせて短く返答してください。

mode: {mode}

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
{message_text}

現在のチャンネルの直近20件:
{history_text or "履歴なし"}

参照データ:
{source_json}
"""


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


def main() -> int:
    if not gemma_is_running():
        print("Gemma4B未起動")
        return 0

    token = get_token()
    if not token:
        print("Gemma課長Discord Bot設定未完了")
        return 0

    try:
        import discord
    except ImportError:
        print("discord.py未インストール")
        return 0

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    channel_modes: dict[int, dict[str, str]] = {}

    @client.event
    async def on_ready() -> None:
        user = client.user
        print(f"Gemma課長Discord Bot起動: {user}")
        guild_id = get_guild_id()
        guild = client.get_guild(guild_id) if guild_id is not None else None
        if guild is None and guild_id is not None:
            print(f"GEMMA_GUILD_IDのサーバーが見つかりません: {guild_id}")
            return
        if guild is None:
            print("GEMMA_GUILD_ID未設定: サーバー全体管理は未有効")
            return

        channel_modes.clear()
        text_channels = list(guild.text_channels)
        print(f"サーバー名: {guild.name}")
        print(f"取得チャンネル数: {len(text_channels)}")
        for channel in text_channels:
            mode = classify_channel_mode(channel.name)
            rule = channel_rule(channel.name)
            channel_modes[channel.id] = {"name": channel.name, "mode": mode, "rule": rule}
            print(f"- {channel.name}: mode={mode}, rule={rule}")

    @client.event
    async def on_message(message: Any) -> None:
        if message.author == client.user:
            return

        content = message.content.strip()
        if not content:
            return
        if content_filter.is_filtered(content):
            return

        channel_name = getattr(message.channel, "name", "")
        channel_info = channel_modes.get(
            getattr(message.channel, "id", 0),
            {
                "name": channel_name,
                "mode": classify_channel_mode(channel_name),
                "rule": channel_rule(channel_name),
            },
        )
        if channel_info["rule"] == "ignore":
            return
        if channel_info["rule"] == "listen_only":
            # TODO: 将来ここで傍聴席ログを保存する。
            return

        channel_id = getattr(message.channel, "id", "unknown")
        user_name = getattr(message.author, "display_name", str(message.author))
        history = chat_memory.load_history(channel_id)
        history_text = chat_memory.format_history(history)

        command = content.split(maxsplit=1)[0]
        if command in COMMANDS:
            if command == "!dragons" and not load_yaml(DRAGONS_PATH):
                reply = "ドラゴンズ関連ログはありません"
                chat_memory.append_message(channel_id, user_name, content, "user")
                chat_memory.append_message(channel_id, "ジェンマ課長", reply, "assistant")
                await message.channel.send(reply)
                return

            source = source_for_command(command)
            prompt = build_prompt(command, source, history_text)
            response = call_ollama(prompt)
            if response is None:
                await message.channel.send("Gemma4B未起動")
                return
            reply = trim_discord_message(normalize_reply(response))
            chat_memory.append_message(channel_id, user_name, content, "user")
            chat_memory.append_message(channel_id, "ジェンマ課長", reply, "assistant")
            await message.channel.send(reply)
            return

        mode = channel_info["mode"]
        if mode == "chat":
            classified = classify_message_text(content)
            if classified is None:
                await message.channel.send("Gemma4B未起動")
                return
            mode = classified

        source = source_for_mode(mode)
        prompt = build_natural_prompt(content, mode, source, history_text)
        response = call_ollama(prompt)
        if response is None:
            await message.channel.send("Gemma4B未起動")
            return
        reply = trim_discord_message(normalize_reply(response))
        chat_memory.append_message(channel_id, user_name, content, "user")
        chat_memory.append_message(channel_id, "ジェンマ課長", reply, "assistant")
        await message.channel.send(reply)

    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
