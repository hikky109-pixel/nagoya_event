#!/usr/bin/env python3
"""DiscordコマンドからGemma 4Bのジェンマ課長返答を行うBot。"""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
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
BOT_NAME_MENTION_TOKENS = (
    "@ジェンマ課長",
    "ジェンマ課長",
    "<@1518154055455871036>",
    "<@!1518154055455871036>",
)

sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from tools.ai import chat_memory  # noqa: E402
from tools.ai import content_filter  # noqa: E402
from tools.ai import image_memory  # noqa: E402
from tools.ai import image_router  # noqa: E402
from tools.ai import ocr_worker  # noqa: E402
from tools.ai import build_tsv_candidate  # noqa: E402
from tools.ai import check_tsv_candidate  # noqa: E402
from tools.ai.meieki_busy_buttons import build_meieki_busy_view  # noqa: E402
from tools.ai.oracle_memory import format_oracle_memory, oracle_log_values  # noqa: E402
from tools.ai.entity_dictionary import classify_by_dictionary  # noqa: E402
from tools.ai.entity_resolver import entity_system_prompt  # noqa: E402
from tools.ai.search_router import needs_research  # noqa: E402


def get_token() -> str:
    token = getattr(config, "DISCORD_BOT_TOKEN", "")
    return token.strip() if isinstance(token, str) else str(token).strip()


def get_guild_id() -> int | None:
    value = getattr(config, "GEMMA_GUILD_ID", "")
    value = value.strip() if isinstance(value, str) else str(value).strip()
    return int(value) if value.isdigit() else None



def get_admin_channel_id() -> str:
    value = getattr(config, "GEMMA_CHANNEL_ADMIN", "")
    return value.strip() if isinstance(value, str) else str(value).strip()


def get_admin_like_channel_ids() -> set[str]:
    ids: set[str] = set()
    for name in ("GEMMA_CHANNEL_ADMIN", "GEMMA_CHANNEL_TEST"):
        value = getattr(config, name, "")
        value = value.strip() if isinstance(value, str) else str(value).strip()
        if value:
            ids.add(value)
    return ids


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
    entity_prompt = entity_system_prompt(command)
    oracle_text = format_oracle_memory(command)
    oracle_count, oracle_titles = oracle_log_values(command)
    print(f"oracle_matches={oracle_count}")
    print(f"oracle_titles={oracle_titles}")
    return f"""あなたはジェンマ課長です。

Discordコマンド {command} への短い返答を作ってください。

{entity_prompt}

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

過去事例:
{oracle_text}
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
    dictionary_category = classify_by_dictionary(message_text)
    if dictionary_category in {"food", "road", "railway"}:
        return dictionary_category
    if dictionary_category == "dragons":
        return "event"
    if dictionary_category == "facility":
        return "event"
    if dictionary_category == "place":
        return "unknown"

    entity_prompt = entity_system_prompt(message_text)
    prompt = f"""あなたはジェンマ課長の分類器です。
次のDiscord発言を1語だけで分類してください。

{entity_prompt}

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
    entity_prompt = entity_system_prompt(message_text)
    oracle_text = format_oracle_memory(message_text)
    oracle_count, oracle_titles = oracle_log_values(message_text)
    print(f"oracle_matches={oracle_count}")
    print(f"oracle_titles={oracle_titles}")
    return f"""あなたはジェンマ課長です。

Discordの通常発言へ、担当班モードに合わせて短く返答してください。

mode: {mode}

{entity_prompt}

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

過去事例:
{oracle_text}

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


def dedupe_reply_lines(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    detail_seen = False
    for line in lines:
        if line == "・詳細は未確認です。":
            if detail_seen:
                continue
            detail_seen = True
        elif line in seen:
            continue
        deduped.append(line)
        seen.add(line)

    while len(deduped) > 1 and deduped[-1] == "・詳細は未確認です。" and deduped[-2] == "・詳細は未確認です。":
        deduped.pop()
    return "\n".join(deduped)


def trim_discord_message(text: str) -> str:
    text = dedupe_reply_lines(text.strip()) or "未確認です。"
    if len(text) <= 1900:
        return text
    return text[:1897].rstrip() + "..."


def is_mention_to_me(message: Any, client: Any) -> bool:
    user = getattr(client, "user", None)
    if user is None:
        return False
    if user in getattr(message, "mentions", []):
        return True
    reference = getattr(message, "reference", None)
    resolved = getattr(reference, "resolved", None)
    author = getattr(resolved, "author", None)
    return author == user



def strip_bot_mentions(content: str, client: Any) -> str:
    user = getattr(client, "user", None)
    cleaned = content
    if user is not None:
        user_id = getattr(user, "id", "")
        cleaned = cleaned.replace(f"<@{user_id}>", "").replace(f"<@!{user_id}>", "")
    for token in BOT_NAME_MENTION_TOKENS:
        cleaned = cleaned.replace(token, "")
    return cleaned.strip()


def is_name_mention(content: str) -> bool:
    return any(token in content for token in BOT_NAME_MENTION_TOKENS)


def log_attachment_debug(message: Any) -> None:
    attachments = getattr(message, "attachments", [])
    print(f"attachments={len(attachments)}")
    for attachment in attachments:
        filename = getattr(attachment, "filename", "")
        content_type = getattr(attachment, "content_type", "")
        url = getattr(attachment, "url", "")
        print(f"attachment filename={filename}")
        print(f"attachment content_type={content_type}")
        print(f"attachment url={url}")


def search_history_reply(query: str) -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ai" / "search_history.py"), query],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return "未確認です。"
    return result.stdout.strip() or "未確認です。"


def recent_history_text(history: list[dict[str, Any]], limit: int = 4) -> str:
    parts: list[str] = []
    for item in history[-limit:]:
        user_name = item.get("user_name", "")
        message = item.get("message", "")
        if message:
            parts.append(f"{user_name}: {message}")
    return "\n".join(parts)


def search_router_reply(query: str) -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ai" / "search_router.py"), query],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return "error"
    return result.stdout.strip() or "error"


def should_use_search_router(content: str, history: list[dict[str, Any]]) -> bool:
    if needs_research(content):
        return True
    context = f"{recent_history_text(history)}\n{content}".strip()
    return needs_research(context)


def build_attachment_reply(
    image_cases: list[dict[str, Any]],
    ocr_case: dict[str, Any] | None,
    tsv_result: dict[str, Any] | None,
    quality_result: dict[str, Any] | None = None,
) -> str:
    if ocr_case is None:
        ocr_line = "・OCRは未実行または失敗しました。"
        warning_line = ""
        empty_line = ""
    elif str(ocr_case.get("ocr_text", "")).strip():
        ocr_line = "・OCR結果を取得しました。"
        warning_line = "・日本語OCR辞書(jpn)が未導入のため、英語OCRで処理しました。" if ocr_case.get("warning") == "japanese_language_not_installed" else ""
        empty_line = ""
    else:
        ocr_line = "・OCRを実行しました。"
        warning_line = "・日本語OCR辞書(jpn)が未導入のため、英語OCRで処理しました。" if ocr_case.get("warning") == "japanese_language_not_installed" else ""
        empty_line = "・文字は抽出できませんでした。"
    if tsv_result is not None and not tsv_result.get("error") and int(tsv_result.get("rows", 0)) > 0:
        tsv_line = f"・{tsv_result.get('rows', 0)}件のイベント候補を生成しました。"
    else:
        tsv_line = "・TSV候補は生成されていません。"
    case_type = image_cases[0].get("type", "unknown") if image_cases else "unknown"
    lines = [
        "画像/PDF案件を受け付けました😇",
        "・ファイル案件として保存しました。",
        f"・種別は {case_type} の可能性があります。",
        ocr_line,
    ]
    if warning_line:
        lines.append(warning_line)
    if empty_line:
        lines.append(empty_line)
    lines.append(tsv_line)
    if quality_result is not None:
        lines.append(f"・案件種別: {quality_result.get('case_type', 'unknown')}")
        if quality_result.get("road_candidate"):
            lines.append("・交通規制情報も検出しました。")
        lines.append(f"・信頼度: {quality_result.get('confidence', 'unknown')}")
    lines.append("・OCR誤認識の可能性があるため、人手確認をお願いします。")
    return "\n".join(lines)


async def save_attachments_locally(message: Any) -> dict[str, str]:
    local_paths: dict[str, str] = {}
    for attachment in getattr(message, "attachments", []) or []:
        filename = str(getattr(attachment, "filename", "") or "")
        if not filename:
            continue
        path = image_memory.attachment_path(getattr(message, "id", "unknown"), filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await attachment.save(path)
        except Exception as exc:
            print(f"attachment_save_failed={filename}: {exc}")
            continue
        local_paths[filename] = str(path.relative_to(ROOT))
    return local_paths


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

    class GemmaDiscordClient(discord.Client):
        async def setup_hook(self) -> None:
            self.add_view(build_meieki_busy_view(discord))
            print("persistent_view_registered=meieki_busy", flush=True)

    client = GemmaDiscordClient(intents=intents)
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
        try:
            attachments = getattr(message, "attachments", [])
            print("raw_message:", repr(getattr(message, "content", "")))
            print("channel:", getattr(message.channel, "name", ""))
            print("author:", message.author)
            print("mentions:", [m.id for m in getattr(message, "mentions", [])])
            print("attachments:", len(attachments))

            if message.author == client.user:
                print("ignore_reason=self_bot")
                return

            if getattr(message.author, "bot", False):
                print("ignore_reason=bot")
                return

            content = message.content.strip()
            if not content and not attachments:
                return

            blocked = bool(content and content_filter.is_filtered(content))
            print("content_filter_blocked=", blocked)
            if blocked:
                print("return_reason=content_filter")
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
                print("return_reason=ignore_channel")
                return
            if channel_info["rule"] == "listen_only":
                print("return_reason=listen_only_channel")
                # TODO: 将来ここで傍聴席ログを保存する。
                return

            channel_id = getattr(message.channel, "id", "unknown")
            user_name = getattr(message.author, "display_name", str(message.author))
            history = chat_memory.load_history(channel_id)
            history_text = chat_memory.format_history(history)
            command = content.split(maxsplit=1)[0]
            direct_addressed_to_me = is_mention_to_me(message, client)
            name_mention_detected = is_name_mention(content)
            addressed_to_me = direct_addressed_to_me or name_mention_detected
            print("name_mention_detected=", name_mention_detected)
            admin_like_channel_ids = get_admin_like_channel_ids()
            is_admin_channel = str(channel_id) in admin_like_channel_ids
            if attachments:
                log_attachment_debug(message)
            attachment_local_paths = await save_attachments_locally(message) if attachments and (addressed_to_me or is_admin_channel) else {}
            image_cases = image_router.save_message_image_cases(message, attachment_local_paths) if addressed_to_me or is_admin_channel else []
            if attachments:
                print(f"image_case_saved={bool(image_cases)}")
            is_command = command in COMMANDS
            if direct_addressed_to_me:
                reply_reason = "mention" if getattr(client, "user", None) in getattr(message, "mentions", []) else "reply"
            elif name_mention_detected:
                reply_reason = "name_mention"
            elif is_command:
                reply_reason = "command"
            else:
                reply_reason = "none"
            should_reply = addressed_to_me or is_command

            if content:
                chat_memory.append_message(channel_id, user_name, content, "user")
            print("should_reply=", should_reply)
            print("reply_reason=", reply_reason)

            if not should_reply:
                return

            if addressed_to_me:
                if image_cases:
                    query = "添付ファイル案件です。"
                    ocr_case = None
                    tsv_result = None
                    quality_result = None
                    saved_path = image_cases[0].get("saved_path")
                    if saved_path:
                        ocr_case = ocr_worker.process_image_case(ROOT / str(saved_path))
                        if ocr_case is not None:
                            tsv_result = build_tsv_candidate.process_ocr_case(ROOT / str(ocr_case["saved_path"]))
                            if tsv_result is not None and not tsv_result.get("error") and tsv_result.get("tsv_path"):
                                quality_result = check_tsv_candidate.check_tsv_candidate(ROOT / str(tsv_result["tsv_path"]))
                    print(f"ocr_case_created={ocr_case is not None}")
                    print(f"tsv_created={tsv_result is not None}")
                    reply = trim_discord_message(build_attachment_reply(image_cases, ocr_case, tsv_result, quality_result))
                    chat_memory.append_message(channel_id, "ジェンマ課長", reply, "assistant")
                    await message.channel.send(reply)
                    return

                query = strip_bot_mentions(content, client) or content or "未確認です。"
                print("cleaned_input=", query)
                if should_use_search_router(query, history):
                    search_query = query
                    print(f"search_router_input={search_query}")
                    reply = trim_discord_message(search_router_reply(search_query))
                else:
                    reply = "no_search"
                if reply in {"no_search", "not_applicable", "error"}:
                    reply = trim_discord_message(search_history_reply(query))
                if reply not in {"Gemma4B未起動", "日誌記憶なし"}:
                    chat_memory.append_message(channel_id, "ジェンマ課長", reply, "assistant")
                await message.channel.send(reply)
                return

            if is_command:
                if command == "!dragons" and not load_yaml(DRAGONS_PATH):
                    reply = "ドラゴンズ関連ログはありません"
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
                chat_memory.append_message(channel_id, "ジェンマ課長", reply, "assistant")
                await message.channel.send(reply)
                return
        except Exception:
            traceback.print_exc()

    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
