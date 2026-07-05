#!/usr/bin/env python3
"""Export Discord GPS/PlaceInfo posts to a review TSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_INPUT = ROOT / "data" / "ai" / "discord_history"
DEFAULT_OUTPUT = ROOT / "data" / "location" / "placeinfo_review.tsv"
TARGET_MARKER = "🚕 現在地テスト結果"
DISCORD_API_BASE = "https://discord.com/api/v10"

REVIEW_COLUMNS = [
    "timestamp",
    "message_id",
    "lat",
    "lon",
    "address",
    "current_guess",
    "candidate1",
    "candidate2",
    "candidate3",
    "candidate4",
    "candidate5",
    "google_maps_url",
    "my_comment",
    "expected",
    "judge",
    "fix_policy",
    "fixed_at",
    "retest_result",
]

COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")
CANDIDATE_RE = re.compile(r"^\s*([1-5])[\.\．]\s*(.+?)\s*$")


def _text(value: Any) -> str:
    return str(value or "").strip()


def iter_jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[WARN] JSONL parse skipped: {path}:{line_number}: {exc}", file=sys.stderr)
                continue
            if isinstance(payload, dict):
                yield payload


def iter_discord_rows(input_path: Path) -> Iterable[dict[str, Any]]:
    if input_path.is_file():
        yield from iter_jsonl_rows(input_path)
        return
    if not input_path.exists():
        return
    for path in sorted(input_path.glob("*.jsonl")):
        yield from iter_jsonl_rows(path)


def discord_authorization_header(token: str) -> str:
    token = token.strip()
    if token.lower().startswith("bot "):
        return token
    return f"Bot {token}"


def fetch_discord_messages(channel_id: str, token: str, limit: int = 100) -> list[dict[str, Any]]:
    channel_id = channel_id.strip()
    token = token.strip()
    if not channel_id:
        raise RuntimeError("GPS_REPORT_CHANNEL_ID or YAHOO_PLACEINFO_TEST_CHANNEL_ID is not configured")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")

    safe_limit = max(1, min(int(limit or 100), 100))
    query = urlencode({"limit": safe_limit})
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages?{query}"
    request = Request(
        url,
        headers={
            "Authorization": discord_authorization_header(token),
            "User-Agent": "nagoya-event-placeinfo-review/1.0",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error: HTTP{exc.code} {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed: {exc}") from exc

    if not isinstance(payload, list):
        raise RuntimeError("Discord API returned unexpected payload")
    return [item for item in payload if isinstance(item, dict)]


def configured_discord_source() -> tuple[str, str]:
    try:
        import config
    except ImportError:
        return (
            os.getenv("GPS_REPORT_CHANNEL_ID", "").strip() or os.getenv("YAHOO_PLACEINFO_TEST_CHANNEL_ID", "").strip(),
            os.getenv("DISCORD_BOT_TOKEN", "").strip(),
        )
    return (
        str(getattr(config, "GPS_REPORT_CHANNEL_ID", "") or getattr(config, "YAHOO_PLACEINFO_TEST_CHANNEL_ID", "") or "").strip(),
        str(getattr(config, "DISCORD_BOT_TOKEN", "") or "").strip(),
    )


def _next_nonempty(lines: list[str], start_index: int) -> str:
    for line in lines[start_index + 1 :]:
        value = line.strip()
        if value:
            return value
    return ""


def _parse_labeled_value(lines: list[str], label: str) -> str:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == label:
            return _next_nonempty(lines, index)
        if stripped.startswith(f"{label}:"):
            value = stripped.split(":", 1)[1].strip()
            return value or _next_nonempty(lines, index)
    return ""


def parse_placeinfo_content(content: str) -> dict[str, str] | None:
    if TARGET_MARKER not in content:
        return None

    lines = content.splitlines()
    address = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("📍"):
            address = stripped.removeprefix("📍").strip()
            break
        if stripped.startswith("住所:"):
            address = stripped.split(":", 1)[1].strip()
            break

    current_guess = _parse_labeled_value(lines, "推定")

    lat = ""
    lon = ""
    coordinate_line = _parse_labeled_value(lines, "座標")
    match = COORD_RE.search(coordinate_line)
    if not match:
        match = COORD_RE.search(content)
    if match:
        lat, lon = match.group(1), match.group(2)

    candidates = ["", "", "", "", ""]
    for line in lines:
        match = CANDIDATE_RE.match(line)
        if match:
            index = int(match.group(1)) - 1
            candidates[index] = match.group(2).strip()

    return {
        "lat": lat,
        "lon": lon,
        "address": address,
        "current_guess": current_guess,
        "candidate1": candidates[0],
        "candidate2": candidates[1],
        "candidate3": candidates[2],
        "candidate4": candidates[3],
        "candidate5": candidates[4],
        "google_maps_url": f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else "",
    }


def row_from_discord_message(message: dict[str, Any]) -> dict[str, str] | None:
    content = _text(message.get("content"))
    parsed = parse_placeinfo_content(content)
    if parsed is None:
        return None

    row = {column: "" for column in REVIEW_COLUMNS}
    row.update(parsed)
    row["timestamp"] = _text(message.get("timestamp") or message.get("created_at"))
    row["message_id"] = _text(message.get("message_id") or message.get("id"))
    return row


def dedupe_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        message_id = row.get("message_id", "")
        if message_id:
            key = f"message_id:{message_id}"
        else:
            key = f"fallback:{row.get('lat', '')}:{row.get('lon', '')}:{row.get('timestamp', '')}"
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def write_review_tsv(rows: list[dict[str, str]], output_path: Path = DEFAULT_OUTPUT) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rows_from_messages(messages: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    return dedupe_rows(
        row
        for message in messages
        if (row := row_from_discord_message(message)) is not None
    )


def export_review_tsv(input_path: Path = DEFAULT_INPUT, output_path: Path = DEFAULT_OUTPUT) -> list[dict[str, str]]:
    rows = dedupe_rows(
        row
        for message in iter_discord_rows(input_path)
        if (row := row_from_discord_message(message)) is not None
    )
    write_review_tsv(rows, output_path)
    return rows


def export_review_tsv_from_discord(output_path: Path = DEFAULT_OUTPUT, limit: int = 100) -> list[dict[str, str]]:
    channel_id, token = configured_discord_source()
    messages = fetch_discord_messages(channel_id, token, limit=limit)
    rows = rows_from_messages(messages)
    write_review_tsv(rows, output_path)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discordの現在地テスト投稿をレビューTSVへ抽出する。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Discord履歴JSONLファイルまたはディレクトリ。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="出力TSVパス。")
    parser.add_argument("--fetch-discord", action="store_true", help="Discord APIから直近メッセージを取得する。")
    parser.add_argument("--limit", type=int, default=100, help="Discord API取得件数。最大100。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fetch_discord:
        rows = export_review_tsv_from_discord(args.output, limit=args.limit)
    else:
        rows = export_review_tsv(args.input, args.output)
    print(f"PlaceInfoレビューTSV出力完了: {args.output} ({len(rows)}件)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
