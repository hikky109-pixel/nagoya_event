"""Aichi-Nagoya 2026 BOT integration, removable through one feature flag."""

from __future__ import annotations

import csv
import logging
import os
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from config import ENABLE_AICHI_NAGOYA_2026
from scrapers.utils.google_sheet_events import load_asia_operational_google_sheet_events


ASIA_WEBHOOK_ENV = "WEBHOOK_ASIA"
ASIA_CSV_PATH = Path(
    "data/aichi_nagoya_2026/operational/asia_games_operational_20260810.csv"
)
ASIA_OPERATIONAL_COLUMNS = [
    "date",
    "time",
    "end_time",
    "venue",
    "event_name",
    "session_info",
    "availability_status",
]
ASIA_TICKET_STATUS_LABELS = {
    "BUY": "販売中",
    "LIMITED": "残席わずか",
    "SOLD_OUT": "予定枚数終了",
}
ASIA_TICKET_FOOTER = (
    "チケット状況は公式チケット状況です。販路によって異なる場合があります😇"
)


def is_enabled() -> bool:
    return ENABLE_AICHI_NAGOYA_2026


def _require_enabled() -> None:
    if not is_enabled():
        raise RuntimeError("ENABLE_AICHI_NAGOYA_2026=false: 大会専用機能は無効です")


def _target_date_strings(target_date):
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    if isinstance(target_date, date):
        return {target_date.strftime("%Y/%m/%d"), target_date.strftime("%Y-%m-%d")}
    text = str(target_date)
    return {text, text.replace("/", "-"), text.replace("-", "/")}


def read_operational_csv(csv_path=ASIA_CSV_PATH):
    _require_enabled()
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"アジア大会CSVなし: {csv_path}")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ASIA_OPERATIONAL_COLUMNS:
            raise ValueError(
                f"アジア大会CSV列不一致: expected={ASIA_OPERATIONAL_COLUMNS} "
                f"actual={reader.fieldnames}"
            )
        events = [
            {column: (row.get(column) or "").strip() for column in ASIA_OPERATIONAL_COLUMNS}
            for row in reader
            if (row.get("date") or "").strip() and (row.get("event_name") or "").strip()
        ]
    if not events:
        raise ValueError("アジア大会CSV0件")
    return events


def load_notice_events(target_date, csv_path=ASIA_CSV_PATH, prefer_sheet=True):
    _require_enabled()
    source = "csv"
    if prefer_sheet and Path(csv_path) == ASIA_CSV_PATH:
        try:
            all_events = load_asia_operational_google_sheet_events()
            source = "google_sheet"
        except Exception as exc:
            print(f"[WARN] アジア大会Google Sheets取得失敗、営業用CSVへfallback: {exc}")
            logging.exception("アジア大会Google Sheets取得失敗、営業用CSVへfallback")
            all_events = read_operational_csv(csv_path)
    else:
        all_events = read_operational_csv(csv_path)
    counts = Counter(event.get("availability_status", "") for event in all_events)
    opening_found = any(event.get("event_name") == "開会式" for event in all_events)
    print(f"asia_event_records={len(all_events)}")
    print(f"asia_event_schema={','.join(ASIA_OPERATIONAL_COLUMNS)} source={source}")
    print(f"asia_ticket_status_counts={dict(sorted(counts.items()))}")
    print(f"asia_event_opening_found={str(opening_found).lower()}")
    logging.info("asia_event_records=%s", len(all_events))
    logging.info("asia_event_schema=%s source=%s", ",".join(ASIA_OPERATIONAL_COLUMNS), source)
    logging.info("asia_ticket_status_counts=%s", dict(sorted(counts.items())))
    logging.info("asia_event_opening_found=%s", opening_found)
    targets = _target_date_strings(target_date)
    events = [event for event in all_events if event["date"] in targets]
    return sorted(events, key=lambda event: (event["date"], event["time"], event["venue"]))


def _format_clock(value):
    text = str(value or "").strip()
    if re.fullmatch(r"\d{1,2}:\d{2}:00", text):
        return text[:-3]
    return text


def _format_time(event):
    start = _format_clock(event.get("time"))
    end = _format_clock(event.get("end_time"))
    if start and end:
        return f"{start}〜{end}"
    if start:
        return f"{start}〜"
    if end:
        return f"〜{end}"
    return "時刻未定"


def _truncate(text, limit):
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def render_notice_item(event):
    _require_enabled()
    title = event.get("event_name", "").strip()
    venue = event.get("venue", "").strip() or "不明"
    info = event.get("session_info", "").strip()
    status = event.get("availability_status", "").strip()
    ticket_label = ASIA_TICKET_STATUS_LABELS.get(status, status)
    if status and status not in ASIA_TICKET_STATUS_LABELS:
        print(f"asia_ticket_status_unknown={status}")
        logging.warning("asia_ticket_status_unknown=%s", status)
    lines = [f"📢 {_format_time(event)}", f"📍 {venue}", f"🎺 {title}"]
    if info:
        lines.append(f"📝 {_truncate(info, 700)}")
    if status:
        lines.append(f"🎫 チケット：{ticket_label}")
    return "\n".join(lines)


def combine_embed_footer(embed, footer_text):
    existing = str(embed.get("footer", {}).get("text", "")).strip()
    if existing and footer_text not in existing:
        footer_text = f"{existing}｜{footer_text}"
    elif existing:
        footer_text = existing
    embed["footer"] = {"text": footer_text}
    return embed


def build_embed(events, target_date, test_mode=False):
    _require_enabled()
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    if not events:
        raise ValueError("アジア大会Embed対象0件")
    if test_mode and (len(events) != 1 or events[0].get("event_name") != "開会式"):
        raise ValueError("開会式テストは開会式1件だけを対象にしてください")
    prefix = "🧪【テスト投稿】" if test_mode else ""
    description = (
        target_date.strftime("%Y-%m-%d")
        + f"\n🏟️ {len(events)}件\n────────────\n"
        + "\n────────────\n".join(render_notice_item(event) for event in events)
    )
    embed = {
        "title": f"{prefix}🏟️ アジア大会情報",
        "description": _truncate(description, 4096),
        "color": 0xE67E22,
    }
    if any(event.get("availability_status", "").strip() for event in events):
        combine_embed_footer(embed, ASIA_TICKET_FOOTER)
    return embed


def build_embeds(events, target_date, test_mode=False):
    _require_enabled()
    if test_mode:
        return [build_embed(events, target_date, test_mode=True)]
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    if not events:
        raise ValueError("アジア大会Embed対象0件")
    header = target_date.strftime("%Y-%m-%d") + f"\n🏟️ {len(events)}件\n────────────\n"
    descriptions = []
    current = header
    for event in events:
        item = render_notice_item(event)
        separator = "" if current == header else "\n────────────\n"
        if len(current) + len(separator) + len(item) > 3800 and current != header:
            descriptions.append(current)
            current = header + item
        else:
            current += separator + item
    descriptions.append(current)
    embeds = []
    for index, description in enumerate(descriptions, start=1):
        title = "🏟️ アジア大会情報"
        if len(descriptions) > 1:
            title += f" ({index}/{len(descriptions)})"
        embed = {"title": title, "description": description, "color": 0xE67E22}
        if any(event.get("availability_status", "").strip() for event in events):
            combine_embed_footer(embed, ASIA_TICKET_FOOTER)
        embeds.append(embed)
    return embeds


def send_events(events, target_date, test_mode=False, webhook_url=None, http_post=requests.post):
    _require_enabled()
    if test_mode:
        print("asia_event_test_mode=true")
        print(f"asia_event_test_records={len(events)}")
        print(
            "asia_event_opening_notification_target="
            + str(len(events) == 1 and events[0].get("event_name") == "開会式").lower()
        )
    embeds = build_embeds(events, target_date, test_mode=test_mode)
    webhook_url = webhook_url or os.getenv(ASIA_WEBHOOK_ENV)
    if not webhook_url:
        print("asia_event_discord_status=not_configured")
        return False
    post_url = webhook_url
    if test_mode:
        parts = urlsplit(webhook_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["wait"] = "true"
        post_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    footer_verified = not test_mode
    for embed in embeds:
        response = http_post(post_url, json={"embeds": [embed]}, timeout=10)
        expected_statuses = {200} if test_mode else {204}
        if response.status_code not in expected_statuses:
            print(f"asia_event_discord_status=error status={response.status_code}")
            raise RuntimeError(
                f"アジア大会Discord投稿エラー: {response.status_code} {response.text}"
            )
        if test_mode:
            posted = response.json()
            posted_embeds = posted.get("embeds") or []
            footer_text = (
                posted_embeds[0].get("footer", {}).get("text", "") if posted_embeds else ""
            )
            footer_verified = footer_text == ASIA_TICKET_FOOTER
            print(f"asia_event_footer_verified={str(footer_verified).lower()}")
            if not footer_verified:
                raise RuntimeError("Discord投稿後のfooter確認に失敗しました")
    print(f"asia_event_discord_status=sent records={len(events)} embeds={len(embeds)}")
    return True


def send_daily_notice(target_date, dry_run=False):
    if not is_enabled():
        print("asia_event_disabled=true")
        return False
    events = load_notice_events(target_date)
    if not events:
        print("アジア大会情報: 当日データなしのため送信スキップ")
        return False
    if dry_run:
        for embed in build_embeds(events, target_date):
            print(embed)
        return False
    return send_events(events, target_date)


def opening_test_event():
    _require_enabled()
    opening_date = date(2026, 9, 19)
    events = load_notice_events(opening_date, ASIA_CSV_PATH, prefer_sheet=False)
    opening = [event for event in events if event.get("event_name") == "開会式"]
    if len(opening) != 1:
        raise RuntimeError(f"開会式テスト対象は1件必須: actual={len(opening)}")
    return opening[0]
