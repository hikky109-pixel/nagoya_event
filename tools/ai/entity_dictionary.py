#!/usr/bin/env python3
"""ジェンマ課長の軽量エンティティ辞書。"""

from __future__ import annotations


FOOD_WORDS = {
    "かつや",
    "すき家",
    "吉野家",
    "松屋",
    "丸亀製麺",
    "スガキヤ",
}

DRAGONS_WORDS = {
    "ドラゴンズ",
    "中日",
    "バンテリン",
}

RAILWAY_WORDS = {
    "新幹線",
    "JR",
    "名鉄",
}

ROAD_WORDS = {
    "オービス",
    "事故",
    "通行止",
    "高速",
}

PLACE_WORDS = {
    "名古屋駅",
    "今池",
    "栄",
    "金山",
    "大須",
}

FACILITY_WORDS = {
    "IGアリーナ",
    "バンテリンドーム",
    "ポートメッセ",
    "御園座",
}


def classify_by_dictionary(text: str) -> str | None:
    if any(word in text for word in FOOD_WORDS):
        return "food"
    if any(word in text for word in DRAGONS_WORDS):
        return "dragons"
    if any(word in text for word in RAILWAY_WORDS):
        return "railway"
    if any(word in text for word in ROAD_WORDS):
        return "road"
    if any(word in text for word in PLACE_WORDS):
        return "place"
    if any(word in text for word in FACILITY_WORDS):
        return "facility"
    return None
