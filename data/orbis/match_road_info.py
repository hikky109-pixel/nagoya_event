#!/usr/bin/env python3
"""
オービス秘伝のタレDB: 可搬式オービス情報と道路情報CSVを照合するスクリプト。

入力:
  data/orbis/orbis_mobile.csv
  道路情報CSV候補:
    data/road_info.csv
    data/road/road_info.csv
    data/roads/road_info.csv
    data/road_info/road_info.csv

出力:
  data/orbis/orbis_road_matches.csv

まずは Ver.1 として、住所・場所・道路名などの文字列を正規化し、
共通文字列スコアでゆるく照合する。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORBIS_CSV = PROJECT_ROOT / "data" / "orbis" / "orbis_mobile.csv"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "data" / "orbis" / "orbis_road_matches.csv"

ROAD_INFO_CANDIDATES = [
    PROJECT_ROOT / "data" / "road_info.csv",
    PROJECT_ROOT / "data" / "road" / "road_info.csv",
    PROJECT_ROOT / "data" / "roads" / "road_info.csv",
    PROJECT_ROOT / "data" / "road_info" / "road_info.csv",
]

ORBIS_TEXT_COLUMNS = [
    "category",
    "city",
    "location",
    "place",
    "address",
    "spot",
    "road",
    "road_name",
    "route",
    "name",
    "場所",
    "住所",
    "地点",
    "道路",
    "路線",
    "路線名",
    "名称",
    "市区町村",
    "市町村",
]

ORBIS_OUTPUT_COLUMNS = ["category", "city", "road", "direction", "location", "note"]

ROAD_TEXT_COLUMNS = [
    "venue",
    "note",
    "location",
    "place",
    "address",
    "spot",
    "road",
    "road_name",
    "route",
    "name",
    "title",
    "description",
    "場所",
    "住所",
    "地点",
    "道路",
    "路線",
    "路線名",
    "名称",
    "件名",
    "内容",
]

CITY_KEYWORDS = [
    "名古屋市",
    "千種区",
    "東区",
    "北区",
    "西区",
    "中村区",
    "中区",
    "昭和区",
    "瑞穂区",
    "熱田区",
    "中川区",
    "港区",
    "南区",
    "守山区",
    "緑区",
    "名東区",
    "天白区",
    "豊田市",
    "半田市",
    "春日井市",
    "小牧市",
    "豊山町",
]

ROAD_KEYWORDS = [
    "名古屋高速",
    "東山線",
    "小牧線",
    "東海線",
    "環状線",
    "国道",
    "県道",
    "市道",
    "名二環",
    "東名阪道",
    "新東名",
    "新東名高速道路",
    "猿投グリーンロード",
    "グリーンロード",
    "東名高速",
    "名神高速",
]

ROAD_ALIASES = {
    "名二環": ["名二環", "名古屋第二環状", "名古屋第二環状自動車道"],
    "東名阪道": ["東名阪", "東名阪道", "東名阪自動車道"],
    "猿投グリーンロード": ["猿投グリーンロード", "グリーンロード"],
    "新東名": ["新東名", "新東名高速道路"],
}


@dataclass(frozen=True)
class MatchResult:
    orbis_index: int
    road_index: int
    score: int
    orbis_text: str
    road_text: str
    orbis_row: dict[str, str]
    road_row: dict[str, str]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSVが見つかりません: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"ヘッダーがありません: {path}")
        return [dict(row) for row in reader]


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_text(value: str) -> str:
    text = str(value or "")
    text = text.lower()
    text = text.replace("　", " ")
    text = re.sub(r"[\s,./・･:：;；()（）\[\]【】「」『』\-ー−―]+", "", text)
    text = text.replace("国道", "r")
    text = text.replace("県道", "p")
    text = text.replace("市道", "c")
    text = text.replace("号線", "")
    return text


# 国道番号抽出関数
def extract_route_number(text: str) -> str | None:
    """国道○号、○号線などから番号を抽出する。"""
    text = str(text or "")

    patterns = [
        r"国道\s*([0-9０-９]+)",
        r"([0-9０-９]+)号線",
        r"([0-9０-９]+)号",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))

    return None


def keyword_bonus(left: str, right: str) -> int:
    """地名・路線名など、短い一致をスコアに加点する。"""
    bonus = 0
    combined_left = normalize_text(left)
    combined_right = normalize_text(right)

    for keyword in CITY_KEYWORDS:
        normalized = normalize_text(keyword)
        if normalized and normalized in combined_left and normalized in combined_right:
            bonus += 35

    for keyword in ROAD_KEYWORDS:
        normalized = normalize_text(keyword)
        if normalized and normalized in combined_left and normalized in combined_right:
            bonus += 30

    if "オービス" in left and "オービス" in right:
        bonus += 30

    if "可搬式" in left and "可搬式" in right:
        bonus += 30

    # 別名辞書による路線一致
    for aliases in ROAD_ALIASES.values():
        found_left = any(alias in left for alias in aliases)
        found_right = any(alias in right for alias in aliases)
        if found_left and found_right:
            bonus += 40

    return min(bonus, 80)


def pick_existing_columns(row: dict[str, str], candidates: Iterable[str]) -> list[str]:
    return [col for col in candidates if col in row and str(row.get(col, "")).strip()]


def joined_text(row: dict[str, str], preferred_columns: list[str]) -> str:
    columns = pick_existing_columns(row, preferred_columns)
    if not columns:
        columns = [key for key, value in row.items() if str(value or "").strip()]
    return " ".join(str(row.get(col, "")).strip() for col in columns if str(row.get(col, "")).strip())


def char_ngram_set(text: str, n: int = 2) -> set[str]:
    if not text:
        return set()
    if len(text) <= n:
        return {text}
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def similarity_score(left: str, right: str) -> int:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    bonus = keyword_bonus(left, right)

    # オービスDBとの照合では、通常の「交通取締予定」より
    # 「可搬式オービス予定」を優先する。
    if "交通取締" in right and "オービス" not in right:
        bonus -= 60
    if "取締" in right and "オービス" not in right:
        bonus -= 40

    # 国道番号が一致する場合は大幅加点、不一致なら減点
    left_route = extract_route_number(left)
    right_route = extract_route_number(right)

    if left_route and right_route:
        if left_route == right_route:
            bonus += 50
        else:
            bonus -= 50

    if not left_norm or not right_norm:
        return bonus

    if left_norm == right_norm:
        return 100

    if left_norm in right_norm or right_norm in left_norm:
        shorter = min(len(left_norm), len(right_norm))
        longer = max(len(left_norm), len(right_norm))
        return min(100, max(70, int(shorter / longer * 100)) + bonus)

    left_set = char_ngram_set(left_norm)
    right_set = char_ngram_set(right_norm)
    if not left_set or not right_set:
        return bonus

    overlap = len(left_set & right_set)
    union = len(left_set | right_set)
    base_score = int(overlap / union * 100)
    return min(100, base_score + bonus)


def find_road_info_csv(explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"道路情報CSVが見つかりません: {path}")
        return path

    for path in ROAD_INFO_CANDIDATES:
        if path.exists():
            return path

    candidates = "\n".join(f"  - {path}" for path in ROAD_INFO_CANDIDATES)
    raise FileNotFoundError(
        "道路情報CSVが見つかりません。--road-csv で指定してください。\n"
        f"探索候補:\n{candidates}"
    )


def match_rows(
    orbis_rows: list[dict[str, str]],
    road_rows: list[dict[str, str]],
    min_score: int,
    top_n: int,
) -> list[MatchResult]:
    results: list[MatchResult] = []

    road_text_cache = [joined_text(row, ROAD_TEXT_COLUMNS) for row in road_rows]

    for orbis_index, orbis_row in enumerate(orbis_rows, start=1):
        orbis_text = joined_text(orbis_row, ORBIS_TEXT_COLUMNS)
        scored: list[MatchResult] = []

        for road_index, road_row in enumerate(road_rows, start=1):
            road_text = road_text_cache[road_index - 1]
            score = similarity_score(orbis_text, road_text)
            if score >= min_score:
                scored.append(
                    MatchResult(
                        orbis_index=orbis_index,
                        road_index=road_index,
                        score=score,
                        orbis_text=orbis_text,
                        road_text=road_text,
                        orbis_row=orbis_row,
                        road_row=road_row,
                    )
                )

        scored.sort(key=lambda item: item.score, reverse=True)
        results.extend(scored[:top_n])

    return results


def flatten_match(result: MatchResult) -> dict[str, str]:
    row: dict[str, str] = {
        "score": str(result.score),
        "orbis_index": str(result.orbis_index),
        "road_index": str(result.road_index),
        "orbis_text": result.orbis_text,
        "road_text": result.road_text,
    }

    for key, value in result.orbis_row.items():
        row[f"orbis_{key}"] = value

    for key, value in result.road_row.items():
        row[f"road_{key}"] = value

    return row


def build_fieldnames(rows: list[dict[str, str]]) -> list[str]:
    base = ["score", "orbis_index", "road_index", "orbis_text", "road_text"]
    preferred = [f"orbis_{column}" for column in ORBIS_OUTPUT_COLUMNS]
    extra: list[str] = []
    seen = set(base)

    for key in preferred:
        if key not in seen:
            seen.add(key)
            extra.append(key)

    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                extra.append(key)

    return base + extra


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="オービスCSVと道路情報CSVを照合します。")
    parser.add_argument("--orbis-csv", default=str(DEFAULT_ORBIS_CSV), help="orbis_mobile.csv のパス")
    parser.add_argument("--road-csv", default=None, help="道路情報CSVのパス。未指定なら候補パスを探索")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="出力CSVのパス")
    parser.add_argument("--min-score", type=int, default=25, help="出力する最低スコア")
    parser.add_argument("--top-n", type=int, default=3, help="オービス1件あたりの最大候補数")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    orbis_csv = Path(args.orbis_csv).expanduser().resolve()
    road_csv = find_road_info_csv(args.road_csv)
    output_csv = Path(args.output_csv).expanduser().resolve()

    orbis_rows = read_csv(orbis_csv)
    road_rows = read_csv(road_csv)

    matches = match_rows(
        orbis_rows=orbis_rows,
        road_rows=road_rows,
        min_score=args.min_score,
        top_n=args.top_n,
    )

    output_rows = [flatten_match(match) for match in matches]
    fieldnames = build_fieldnames(output_rows)
    write_csv(output_csv, output_rows, fieldnames)

    print(f"オービス件数: {len(orbis_rows)}")
    print(f"道路情報件数: {len(road_rows)}")
    print(f"照合結果: {len(output_rows)}件")
    print(f"出力: {output_csv}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
