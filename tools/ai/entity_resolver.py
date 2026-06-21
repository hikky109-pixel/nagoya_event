#!/usr/bin/env python3
"""辞書一致したエンティティをGemmaへ渡す前に固定する。"""

from __future__ import annotations

from typing import Any

from tools.ai.entity_dictionary import (
    DRAGONS_WORDS,
    FACILITY_WORDS,
    FOOD_WORDS,
    PLACE_WORDS,
    RAILWAY_WORDS,
    ROAD_WORDS,
)


ENTITY_TYPES = {
    "person",
    "food_chain",
    "sports_team",
    "railway",
    "road",
    "place",
    "facility",
    "event",
    "unknown",
}


def first_match(text: str, words: set[str]) -> str | None:
    for word in sorted(words, key=len, reverse=True):
        if word in text:
            return word
    return None


def resolve_entity(text: str) -> dict[str, Any]:
    food = first_match(text, FOOD_WORDS)
    if food:
        return {
            "type": "food_chain",
            "name": food,
            "note": f"「{food}」は人名ではありません。日本の飲食チェーンです。人として扱わないでください。",
        }

    dragons = first_match(text, DRAGONS_WORDS)
    if dragons:
        return {
            "type": "sports_team",
            "name": dragons,
            "note": f"「{dragons}」は人物ではありません。中日ドラゴンズまたは関連文脈を指します。",
        }

    railway = first_match(text, RAILWAY_WORDS)
    if railway:
        return {
            "type": "railway",
            "name": railway,
            "note": f"「{railway}」は人物ではありません。鉄道関連として扱ってください。",
        }

    road = first_match(text, ROAD_WORDS)
    if road:
        return {
            "type": "road",
            "name": road,
            "note": f"「{road}」は人物ではありません。道路交通関連として扱ってください。",
        }

    place = first_match(text, PLACE_WORDS)
    if place:
        return {
            "type": "place",
            "name": place,
            "note": f"「{place}」は人物ではありません。場所として扱ってください。",
        }

    facility = first_match(text, FACILITY_WORDS)
    if facility:
        return {
            "type": "facility",
            "name": facility,
            "note": f"「{facility}」は人物ではありません。施設として扱ってください。",
        }

    return {
        "type": "unknown",
        "name": "",
        "note": "辞書一致なし。人物・店・球団・鉄道・場所・施設・イベントを混同しないでください。",
    }


def entity_system_prompt(text: str) -> str:
    entity = resolve_entity(text)
    return "\n".join(
        [
            "エンティティ固定:",
            f"- type: {entity['type']}",
            f"- name: {entity['name'] or 'unknown'}",
            f"- rule: {entity['note']}",
            "- 辞書一致をGemmaの自由推論より優先してください。",
        ]
    )
