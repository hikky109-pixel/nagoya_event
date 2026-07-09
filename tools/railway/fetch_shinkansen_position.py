"""Fetch JR Central Tokaido/Sanyo Shinkansen train position JSON."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "railway" / "shinkansen_position"
TRAIN_LOCATION_URL = "https://traininfo.jr-central.co.jp/shinkansen/var/train_info/train_location_info.json"
COMMON_JA_URL = "https://traininfo.jr-central.co.jp/shinkansen/common/data/common_ja.json"
SOURCE_PAGE_URL = "https://traininfo.jr-central.co.jp/shinkansen/pc/ja/ti08.html"
USER_AGENT = "Mozilla/5.0 (compatible; nagoya_event shinkansen-position fetcher)"


def fetch_json(url: str, *, timeout: int = 15) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ja,en-US;q=0.9",
            "Referer": SOURCE_PAGE_URL,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8-sig", errors="replace")
    stripped = text.strip()
    if stripped.startswith("<"):
        raise ValueError(f"JSONではなくHTMLを受信しました: {url}")
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError(f"JSON rootがobjectではありません: {url}")
    return data


def build_snapshot(
    *,
    train_location: dict[str, Any],
    common: dict[str, Any] | None,
    fetched_at: datetime | None = None,
    source_url: str = TRAIN_LOCATION_URL,
    common_url: str = COMMON_JA_URL,
) -> dict[str, Any]:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    return {
        "source": "shinkansen_position",
        "line": "tokaido_shinkansen",
        "coverage": "tokaido_sanyo_shinkansen",
        "fetched_at": fetched_at.isoformat(),
        "source_page_url": SOURCE_PAGE_URL,
        "source_url": source_url,
        "common_url": common_url,
        "payload": train_location,
        "common": common or {},
    }


def snapshot_filename(fetched_at: datetime | None = None) -> str:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    return fetched_at.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S_shinkansen_position.json")


def save_snapshot(snapshot: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_fetched_at = str(snapshot.get("fetched_at") or "")
    try:
        fetched_at = datetime.fromisoformat(raw_fetched_at)
    except ValueError:
        fetched_at = datetime.now(timezone.utc)
    path = output_dir / snapshot_filename(fetched_at)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def fetch_snapshot(
    *,
    url: str = TRAIN_LOCATION_URL,
    common_url: str = COMMON_JA_URL,
    timeout: int = 15,
) -> dict[str, Any]:
    train_location = fetch_json(url, timeout=timeout)
    common = fetch_json(common_url, timeout=timeout)
    return build_snapshot(train_location=train_location, common=common, source_url=url, common_url=common_url)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JR東海 新幹線列車走行位置JSONを取得して保存する。")
    parser.add_argument("--url", default=TRAIN_LOCATION_URL, help="列車走行位置JSON URL。")
    parser.add_argument("--common-url", default=COMMON_JA_URL, help="駅名・列車名辞書JSON URL。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="保存先ディレクトリ。")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout seconds。")
    parser.add_argument("--no-save", action="store_true", help="取得のみ行い、ファイル保存しない。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        snapshot = fetch_snapshot(url=args.url, common_url=args.common_url, timeout=args.timeout)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print(f"shinkansen_position_fetch_failed: {exc}", file=sys.stderr)
        return 1

    if args.no_save:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0

    path = save_snapshot(snapshot, args.output_dir)
    print(f"shinkansen_position_saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
