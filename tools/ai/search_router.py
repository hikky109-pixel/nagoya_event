#!/usr/bin/env python3
"""自然言語を外部調査モードへ振り分け、Gemmaで回答する。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

RESEARCH_TRIGGERS = {
    "調べて",
    "WEBで",
    "webで",
    "検索して",
    "公式",
    "最新",
    "今日",
    "現在",
    "今どう",
    "今どう？",
    "限定",
    "メニュー",
}

CATEGORY_WORDS = {
    "food": {"かつや", "すき家", "スガキヤ", "吉野家", "松屋"},
    "dragons": {"ドラゴンズ", "中日", "バンテリン"},
    "railway": {"新幹線", "JR", "名鉄", "近鉄"},
    "road": {"オービス", "事故", "通行止", "高速"},
    "event": {"IGアリーナ", "バンテリンドーム", "ポートメッセ", "御園座"},
}

sys.path.insert(0, str(ROOT))
from tools.ai.entity_resolver import entity_system_prompt, resolve_entity  # noqa: E402
from tools.ai.oracle_memory import format_oracle_memory  # noqa: E402
from tools.ai.result_formatter import format_results  # noqa: E402
from tools.ai.web_query import search_web  # noqa: E402


def needs_research(text: str) -> bool:
    if any(trigger in text for trigger in RESEARCH_TRIGGERS):
        return True
    return any(word in text for words in CATEGORY_WORDS.values() for word in words)


def classify_category(text: str) -> str:
    for category, words in CATEGORY_WORDS.items():
        if any(word in text for word in words):
            return category

    entity_type = resolve_entity(text).get("type")
    if entity_type == "food_chain":
        return "food"
    if entity_type == "sports_team":
        return "dragons"
    if entity_type == "railway":
        return "railway"
    if entity_type == "road":
        return "road"
    if entity_type == "facility":
        return "event"
    return "unknown"


def build_search_query(text: str, category: str) -> str:
    suffix = {
        "food": "公式 最新 メニュー",
        "dragons": "中日ドラゴンズ 最新",
        "railway": "運行情報 最新",
        "road": "交通情報 最新",
        "event": "公式 最新",
    }.get(category, "最新")
    return f"{text} {suffix}".strip()


def call_ollama(prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 360},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None

    data = json.loads(response_body)
    if not isinstance(data, dict):
        return ""
    return str(data.get("response", "")).strip()


def build_prompt(text: str, category: str, formatted_result: dict[str, Any]) -> str:
    result_json = json.dumps(formatted_result, ensure_ascii=False, indent=2)
    entity_prompt = entity_system_prompt(text)
    oracle_text = format_oracle_memory(text)
    return f"""あなたはジェンマ課長です。

{entity_prompt}

以下は外部調査結果です。
以下は検索結果です。
以下は整理済み検索結果です。
調査予定や今後の方針ではなく、
検索結果から分かることを報告してください。
結果に含まれない内容は推測しないでください。
URLの読み上げは禁止。
検索結果をそのまま列挙せず、
人間向けに要約してください。
3〜6行。
「調べます」「確認します」
「候補を探します」
など未来形は禁止です。

事実と推測を分け、
未確認事項は断定しないこと。
公式ドメイン以外の情報は candidate として扱い、断定しないこと。

ルール:
- 勝手に補完しない
- 不明なら未確認
- candidate を利用
- ツッコミ最大1回
- 本番データを勝手に確定しない
- 推奨表現: 調査したところ / 公式候補では / 検索結果では / 未確認ですが / candidateとして
- 推奨表現: 詳細は公式をご確認ください。
- 禁止表現: 調べます / 確認します / 候補を探します / ピックアップします / 期待しています
- URLを出力しない

分類: {category}
質問: {text}

Oracle記憶:
{oracle_text}

整理済み検索結果:
{result_json}
"""


def normalize_answer(text: str) -> str:
    blocked_phrases = ("未確認事項はありません",)
    banned_plan_phrases = ("調べます", "確認します", "候補を探します", "ピックアップします", "期待しています")
    url_pattern = ("http://", "https://")
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not line.startswith(("承知", "了解"))
        and line.strip("*：:") not in {"分析", "未確認事項", "推論", "回答", "調査結果：かつや 限定メニュー"}
        and not any(phrase in line for phrase in blocked_phrases)
        and not any(phrase in line for phrase in banned_plan_phrases)
        and not any(pattern in line for pattern in url_pattern)
    ]
    if not lines:
        return "・外部調査では確認できる内容は未確認です。\n"
    if len(lines) < 3:
        lines.extend(["・詳細は未確認です。"] * (3 - len(lines)))
    normalized = []
    for line in lines[:7]:
        line = line.replace("調査したところ / 公式候補では / 検索結果では / ", "調査したところ、")
        line = line.replace("調査したところ / 公式候補では / 検索結果では、", "検索結果では、")
        line = line.replace("これらのウェブサイトは全て公式ではない候補です。", "公式判定は未確認のため、candidateとして扱います。")
        normalized.append(line if line.startswith(("・", "-", "*", "🤖")) else f"・{line}")
    return "\n".join(normalized).rstrip() + "\n"


def answer_with_research(text: str) -> str:
    if not needs_research(text):
        return "no_search"

    category = classify_category(text)
    web_result = search_web(build_search_query(text, category), category=category)
    formatted_result = format_results(web_result)
    answer = call_ollama(build_prompt(text, category, formatted_result))
    if answer is None:
        return "Gemma4B未起動"
    return normalize_answer(answer).rstrip()


def main() -> int:
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        text = sys.stdin.read().strip()
    if not text:
        print("no_search")
        return 0
    print(answer_with_research(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
