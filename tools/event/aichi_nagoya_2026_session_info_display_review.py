#!/usr/bin/env python3
"""Review display quality of SAFE session_info candidates without Sheet writes."""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DISPLAY_OK = "DISPLAY_OK"
DISPLAY_NEEDS_FIX = "DISPLAY_NEEDS_FIX"
NEEDS_REVIEW = "NEEDS_REVIEW"
CLASSIFICATIONS = (DISPLAY_OK, DISPLAY_NEEDS_FIX, NEEDS_REVIEW)
CSV_FIELDS = (
    "sheet_row_number",
    "date",
    "time",
    "venue",
    "event_name",
    "current_session_info",
    "candidate_session_info",
    "recommended_session_info",
    "result_code",
    "is_japan_match",
    "important_round_types",
    "display_classification",
    "display_reason",
    "team_identity_check",
)


def recommend_display(candidate: str) -> tuple[str, list[str]]:
    """Apply review-only, general display repairs; do not mutate source audits."""

    value = unicodedata.normalize("NFKC", candidate).strip().replace("|", "｜")
    reasons: list[str] = []
    repaired = re.sub(r"予選ラウンド[-‐‑–—ー・\s]*グループ", "予選グループ", value)
    if repaired != value:
        reasons.append("予選ラウンドとグループを簡潔な公式風表示へ統一")
        value = repaired
    repaired = re.sub(r"予選ラウンド[-‐‑–—ー・\s]*プール", "予選プール", value)
    if repaired != value:
        reasons.append("予選ラウンドとプールを簡潔な公式風表示へ統一")
        value = repaired
    repaired = re.sub(r"(男子|女子)\1", r"\1", value)
    if repaired != value:
        reasons.append("男女ラベルの重複を除去")
        value = repaired
    return value, reasons


def important_round_types(candidate: str) -> list[str]:
    found: list[str] = []
    checks = (
        ("予選", "予選"),
        ("グループ", "グループ"),
        ("プール", "プール"),
        ("準々決勝", "準々決勝"),
        ("準決勝", "準決勝"),
        ("3位決定戦", "3位決定戦"),
        ("順位決定戦", "順位決定戦"),
        ("メダル", "メダル"),
    )
    for label, marker in checks:
        if marker in candidate:
            found.append(label)
    if (
        "決勝" in candidate
        and "準々決勝" not in candidate
        and "準決勝" not in candidate
        and "3位決定戦" not in candidate
    ):
        found.append("決勝")
    return found or ["その他"]


def review_row(row: dict[str, Any]) -> dict[str, Any]:
    candidate = str(row.get("candidate_session_info") or "").strip()
    recommended, repair_reasons = recommend_display(candidate)
    classification = DISPLAY_OK
    reasons: list[str] = []

    if not candidate or not str(row.get("result_code") or "").strip():
        classification = NEEDS_REVIEW
        reasons.append("候補またはResCodeが空")
    if any(marker in candidate for marker in ("?", "？", "�")):
        classification = NEEDS_REVIEW
        reasons.append("API由来の欠損・文字化け記号を検出")
    if candidate.count("｜") > 1:
        classification = NEEDS_REVIEW
        reasons.append("PhaseDesc/UnitDesc由来の区切りが重複")
    without_vs = candidate.replace(" vs ", "")
    if re.search(r"[A-Za-z]{2,}", without_vs):
        classification = NEEDS_REVIEW
        reasons.append("vs以外の連続英字が日本語表示に混在")
    if classification != NEEDS_REVIEW and repair_reasons:
        classification = DISPLAY_NEEDS_FIX
        reasons.extend(repair_reasons)
    if not reasons:
        reasons.append("重複・文字化け・不自然な混在がなく、そのまま表示可能")

    candidate_is_team = "｜" in candidate and " vs " in candidate
    identity_check = (
        "ORG_CODE_TEAM_EVENT"
        if candidate_is_team
        else "NO_COMPETITOR_NAME_INCLUDED"
    )
    sheet = row["sheet"]
    return {
        "sheet_row_number": row["sheet_row_number"],
        "date": sheet["date"],
        "time": sheet["time"],
        "venue": sheet["venue"],
        "event_name": sheet["event_name"],
        "current_session_info": row["current_session_info"],
        "candidate_session_info": candidate,
        "recommended_session_info": recommended if classification == DISPLAY_NEEDS_FIX else "",
        "result_code": row["result_code"],
        "is_japan_match": bool(row.get("is_japan_match")),
        "important_round_types": important_round_types(recommended),
        "display_classification": classification,
        "display_reason": "; ".join(reasons),
        "team_identity_check": identity_check,
    }


def build_report(session_audit: dict[str, Any]) -> dict[str, Any]:
    source_rows = [
        row for row in session_audit.get("rows", [])
        if row.get("classification") == "SAFE_TO_UPDATE"
    ]
    rows = [review_row(row) for row in source_rows]
    counts = Counter(row["display_classification"] for row in rows)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dry_run": True,
        "sheet_write": False,
        "source_safe_count": len(source_rows),
        "summary": {
            "classifications": {name: counts.get(name, 0) for name in CLASSIFICATIONS},
            "japan_matches": sum(row["is_japan_match"] for row in rows),
            "quarterfinals": sum("準々決勝" in row["important_round_types"] for row in rows),
            "semifinals": sum("準決勝" in row["important_round_types"] for row in rows),
            "bronze_matches": sum("3位決定戦" in row["important_round_types"] for row in rows),
            "finals": sum("決勝" in row["important_round_types"] for row in rows),
        },
        "normalization_rule_proposals": [
            {
                "pattern": "予選ラウンド[-‐‑–—ー・\\s]*グループ",
                "replacement": "予選グループ",
                "implemented_in_generator": False,
            },
            {
                "pattern": "予選ラウンド[-‐‑–—ー・\\s]*プール",
                "replacement": "予選プール",
                "implemented_in_generator": False,
            },
        ],
        "rows": rows,
    }


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# アジア大会 session_info SAFE候補 表示品質レビュー",
        "",
        "- Google Sheet書き込み: `false`",
        f"- SAFEレビュー対象: {report['source_safe_count']}",
        "",
        "## 集計",
        "",
        "| 判定 | 件数 |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {name} | {summary['classifications'][name]} |" for name in CLASSIFICATIONS)
    lines.extend(
        [
            "",
            f"- 日本戦: {summary['japan_matches']}",
            f"- 準々決勝: {summary['quarterfinals']}",
            f"- 準決勝: {summary['semifinals']}",
            f"- 3位決定戦: {summary['bronze_matches']}",
            f"- 決勝: {summary['finals']}",
            "",
            "## 一般化可能なルール案（生成器には未適用）",
            "",
            "- `予選ラウンド[-/空白等]グループ` → `予選グループ`",
            "- `予選ラウンド[-/空白等]プール` → `予選プール`",
            "",
            f"## SAFE {report['source_safe_count']}件 全件",
            "",
            "| Sheet行 | date | time | venue | event_name | current_session_info | candidate_session_info | 推奨candidate | ResCode | 日本戦 | 重要ラウンド | 表示品質判定 | 理由 |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in report["rows"]:
        lines.append(
            f"| {row['sheet_row_number']} | {_md(row['date'])} | {_md(row['time'])} | "
            f"{_md(row['venue'])} | {_md(row['event_name'])} | {_md(row['current_session_info'])} | "
            f"{_md(row['candidate_session_info'])} | {_md(row['recommended_session_info']) or '-'} | "
            f"{_md(row['result_code'])} | {'はい' if row['is_japan_match'] else 'いいえ'} | "
            f"{_md('／'.join(row['important_round_types']))} | {row['display_classification']} | "
            f"{_md(row['display_reason'])} |"
        )
    lines.extend(["", "7列schema、session_info、availability_statusは変更していない。", ""])
    return "\n".join(lines)


def write_csv(path: Path, report: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow({**row, "important_round_types": "/".join(row["important_round_types"])})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-audit", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.session_audit.read_text(encoding="utf-8"))
    report = build_report(source)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_prefix.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    write_csv(args.output_prefix.with_suffix(".csv"), report)
    print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
