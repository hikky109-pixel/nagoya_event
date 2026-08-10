#!/usr/bin/env python3
"""Preview or explicitly send one isolated Asian Games opening-ceremony test Embed."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: F401  # Load .env before importing the BOT.
from tools.event.aichi_nagoya_2026_bot import (
    build_embed,
    is_enabled,
    opening_test_event,
    send_events,
)


OPENING_DATE = date(2026, 9, 19)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--send",
        action="store_true",
        help="WEBHOOK_ASIAへ開会式1件をテスト投稿する。省略時はpreviewのみ。",
    )
    args = parser.parse_args()
    if not is_enabled():
        raise SystemExit("ENABLE_AICHI_NAGOYA_2026=false: テスト投稿経路は無効です")
    event = opening_test_event()
    events = [event]
    embed = build_embed(events, OPENING_DATE, test_mode=True)
    print("asia_event_test_mode=true")
    print("asia_event_test_records=1")
    print("asia_event_opening_notification_target=true")
    print(json.dumps({"embeds": [embed]}, ensure_ascii=False, indent=2))
    if not args.send:
        print("asia_event_discord_status=dry_run")
        return
    if not send_events(events, OPENING_DATE, test_mode=True):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
