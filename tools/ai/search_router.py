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
    "railway": {"新幹線", "JR", "JR東海", "名鉄", "近鉄", "地下鉄", "名古屋市営地下鉄", "あおなみ線", "リニモ"},
    "road": {"オービス", "事故", "通行止", "高速"},
    "event": {"IGアリーナ", "バンテリンドーム", "ポートメッセ", "御園座"},
}

RAIL_OFFICIAL_HINTS = {
    "新幹線": [
        "traininfo.jr-central.co.jp",
        "jr-central.co.jp",
    ],
    "東海道新幹線": [
        "traininfo.jr-central.co.jp",
        "jr-central.co.jp",
    ],
    "名鉄": [
        "top.meitetsu.co.jp",
        "meitetsu.co.jp",
    ],
    "近鉄": [
        "kintetsu.jp",
    ],
    "JR東海": [
        "traininfo.jr-central.co.jp",
        "jr-central.co.jp",
    ],
    "地下鉄": [
        "kotsu.city.nagoya.jp",
    ],
    "名古屋市営地下鉄": [
        "kotsu.city.nagoya.jp",
    ],
    "あおなみ線": [
        "aonamiline.co.jp",
    ],
    "リニモ": [
        "linimo.jp",
    ],
}

sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from tools.ai.entity_resolver import entity_system_prompt, resolve_entity  # noqa: E402
from tools.ai.light_context import build_light_context  # noqa: E402
from tools.ai.oracle_memory import format_oracle_matches, oracle_log_values_from_matches  # noqa: E402
from tools.ai.oracle_search import search_oracle  # noqa: E402
from tools.ai.result_formatter import format_results  # noqa: E402
from tools.ai.time_debug import timer  # noqa: E402
from tools.ai.web_query import search_web  # noqa: E402


def get_oracle_max_items() -> int:
    value = getattr(config, "GEMMA_ORACLE_MAX_ITEMS", 3)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 3


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


def official_domains_for_query(query: str) -> list[str]:
    domains: list[str] = []
    for keyword, hints in RAIL_OFFICIAL_HINTS.items():
        if keyword in query:
            domains.extend(hints)

    unique: list[str] = []
    seen: set[str] = set()
    for domain in domains:
        if domain not in seen:
            unique.append(domain)
            seen.add(domain)
    return unique


def result_url(item: dict[str, Any]) -> str:
    return str(item.get("url", "") or item.get("link", "")).lower()


def is_official_url(url: str, domains: list[str]) -> bool:
    return any(domain in url for domain in domains)


def rank_official_first(query: str, search_result: dict[str, Any]) -> dict[str, Any]:
    domains = official_domains_for_query(query)
    print(f"official_hint_domains={domains}", file=sys.stderr)
    if not domains:
        print("official_first=False", file=sys.stderr)
        return search_result

    results = search_result.get("results", [])
    if not isinstance(results, list):
        print("official_first=False", file=sys.stderr)
        return search_result

    official_candidates: list[dict[str, Any]] = []
    enriched: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        official = is_official_url(result_url(normalized), domains)
        normalized["official"] = official
        enriched.append(normalized)
        if official:
            official_candidates.append(normalized)

    ranked = sorted(enriched, key=lambda item: (not bool(item.get("official")), result_url(item)))
    official_first = bool(official_candidates)
    print(f"official_first={official_first}", file=sys.stderr)

    updated = dict(search_result)
    updated["results"] = ranked
    updated["official_candidates"] = official_candidates
    updated["official_status"] = "公式候補あり" if official_first else "公式情報は確認できませんでした。検索結果ベースです"
    updated["official_hint_domains"] = domains
    updated["official_first"] = official_first
    return updated


def call_ollama(prompt: str) -> str | None:
    with timer("ollama", stream=sys.stderr):
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
    light_context = build_light_context()
    with timer("oracle_memory", stream=sys.stderr):
        oracle_matches = search_oracle(text, limit=get_oracle_max_items())
    oracle_text = format_oracle_matches(oracle_matches)
    oracle_count, oracle_titles = oracle_log_values_from_matches(oracle_matches)
    print(f"oracle_matches={oracle_count}", file=sys.stderr)
    print(f"oracle_titles={oracle_titles}", file=sys.stderr)
    return f"""あなたはジェンマ課長です。

{entity_prompt}

{light_context}

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
公式情報がある場合は「公式情報では、」で始めてください。
公式情報がない場合は「公式情報は確認できませんでした。検索結果ベースでは、」で始めてください。

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

過去事例:
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
    if len(lines) < 3 and "・詳細は未確認です。" not in lines:
        lines.append("・詳細は未確認です。")
    normalized = []
    for line in lines[:7]:
        line = line.replace("調査したところ / 公式候補では / 検索結果では / ", "調査したところ、")
        line = line.replace("調査したところ / 公式候補では / 検索結果では、", "検索結果では、")
        line = line.replace("これらのウェブサイトは全て公式ではない候補です。", "公式判定は未確認のため、candidateとして扱います。")
        normalized.append(line if line.startswith(("・", "-", "*", "🤖")) else f"・{line}")
    deduped = []
    seen = set()
    detail_seen = False
    for line in normalized:
        if line == "・詳細は未確認です。":
            if detail_seen:
                continue
            detail_seen = True
        elif line in seen:
            continue
        deduped.append(line)
        seen.add(line)
    return "\n".join(deduped).rstrip() + "\n"


def answer_with_research(text: str) -> str:
    with timer("total", stream=sys.stderr):
        with timer("search_router", stream=sys.stderr):
            if not needs_research(text):
                return "no_search"

            category = classify_category(text)
            with timer("search_router.web_query", stream=sys.stderr):
                web_result = search_web(build_search_query(text, category), category=category)
            if category == "railway":
                web_result = rank_official_first(text, web_result)
            with timer("search_router.format_results", stream=sys.stderr):
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
