import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_LIBS = PROJECT_ROOT.parent / "libs"
ORACLE_LIBS = Path("/home/ubuntu/libs")

for libs_path in (LOCAL_LIBS, ORACLE_LIBS):
    if libs_path.exists():
        sys.path.insert(0, str(libs_path))

from rokuyou import get_rokuyou
from discord_sender import send_discord

import logging
import os
import re
import csv
import json

import requests

from datetime import date, datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

from scrapers.vantelin import scrape_vantelin_with_health
from scrapers.jailhouse import scrape_jailhouse_with_health
from scrapers.sundayfolk import scrape_sundayfolk_with_health
from scrapers.kyodo_tokai import scrape_kyodo_tokai_with_health
from scrapers.cruise import scrape_cruise
from scrapers.misonoza import (
    dedupe_events as dedupe_misonoza_events,
    scrape_misonoza_with_notifications,
    write_misonoza_csv,
)
from scrapers.shiki import scrape_shiki_with_health, write_shiki_csv
from scrapers.utils.csv_events import (
    filter_events_by_date,
    load_csv_events,
    save_daily_debug_log,
)
from scrapers.utils.google_sheet_events import (
    archive_old_road_rows,
    cleanup_old_asia_rows,
    cleanup_old_cruise_rows,
    load_all_google_sheet_events,
    sync_asia_csv_to_sheet,
    sync_cruise_csv_to_sheet,
    sync_csv_to_sheet,
    sync_road_csv_to_sheet,
)

JST = timezone(timedelta(hours=9))
DRY_RUN = False
DISCORD_TARGET = "WEBHOOK_EVENT"
ROAD_WEBHOOK_ENV = "WEBHOOK_ROAD"
CRUISE_WEBHOOK_ENV = "WEBHOOK_CRUISE"
ASIA_WEBHOOK_ENV = "WEBHOOK_ASIA"
ROAD_CSV_PATH = Path("csv_events/road.csv")
CRUISE_CSV_PATH = Path("csv_events/cruise.csv")
ASIA_CSV_PATH = Path("csv_events/asia.csv")
ROAD_CATEGORY_ORDER = [
    "重点取締",
    "交通規制",
    "アジア大会",
    "工事",
    "取締",
    "オービス",
    "イベント",
]
ROAD_CATEGORY_ICONS = {
    "重点取締": "⚠️",
    "交通規制": "🚫",
    "アジア大会": "🏟️",
    "工事": "👷",
    "取締": "🚓",
    "オービス": "📷",
    "イベント": "🎪",
}
LOG_DIR = Path(os.getenv("EVENT_BOT_LOG_DIR", PROJECT_ROOT / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
OPENMETEO_FORECAST_STATE_PATH = PROJECT_ROOT / "data" / "weather" / "openmeteo_forecast_state.json"
OPENMETEO_FORECAST_SLOTS = {0, 6, 12, 18}

logging.basicConfig(
    filename=LOG_DIR / "event_bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)


def _load_json_state(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def openmeteo_forecast_slot_key(now):
    return f"{now:%Y-%m-%d}-{now.hour:02d}"


def run_openmeteo_forecast_scheduler(now):
    if now.hour not in OPENMETEO_FORECAST_SLOTS:
        print("openmeteo_forecast: skipped outside slot")
        logging.info("openmeteo_forecast: skipped outside slot")
        return

    if not os.getenv("WEATHER_ALERT_CHANNEL_ID", "").strip():
        print("openmeteo_forecast: skipped missing WEATHER_ALERT_CHANNEL_ID")
        logging.info("openmeteo_forecast: skipped missing WEATHER_ALERT_CHANNEL_ID")
        return

    slot_key = openmeteo_forecast_slot_key(now)
    state = _load_json_state(OPENMETEO_FORECAST_STATE_PATH)
    if state.get(slot_key):
        print("openmeteo_forecast: skipped already posted")
        logging.info("openmeteo_forecast: skipped already posted")
        return

    try:
        from tools.weather.post_openmeteo_forecast import run as post_openmeteo_forecast

        result = post_openmeteo_forecast(force=True)
        if result.get("sent"):
            state = _load_json_state(OPENMETEO_FORECAST_STATE_PATH)
            state[slot_key] = {
                "posted_at": datetime.now(JST).isoformat(timespec="seconds"),
                "hash": result.get("hash", ""),
            }
            state["last_slot_key"] = slot_key
            _save_json_state(OPENMETEO_FORECAST_STATE_PATH, state)
            print("openmeteo_forecast: posted")
            logging.info("openmeteo_forecast: posted")
            return
        print(f"openmeteo_forecast_error: {result.get('reason') or result.get('status_code') or 'not_sent'}")
        logging.warning("openmeteo_forecast_error: %s", result)
    except Exception as exc:
        print(f"openmeteo_forecast_error: {exc}")
        logging.exception("openmeteo_forecast_error: %s", exc)


def normalize_date_text(value, today=None):
    if not value:
        return today.strftime("%Y-%m-%d") if today else ""

    return str(value).strip().replace("/", "-")


def normalize_event_date(event, today):
    event["date"] = normalize_date_text(event.get("date"), today)
    return event


def normalize_event_time(event):
    event["time"] = event.get("time", "")
    event["end_time"] = event.get("end_time", "")

    if not event["time"] and not event["end_time"]:
        event["time"] = "未定"

    return event


def normalize_events(events, today):
    for event in events:
        normalize_event_date(event, today)
        normalize_event_time(event)

    return events


def dedupe_display_events(events):
    unique_events = []
    seen = set()

    for event in events:
        key = (
            normalize_date_text(event.get("date", "")),
            str(event.get("time", "")).strip(),
            str(event.get("venue", "")).strip(),
            str(event.get("title", "")).strip(),
        )

        if key in seen:
            message = f"重複除外: {event.get('venue', '')} | {event.get('title', '')}"
            print(message)
            logging.info(message)
            continue

        seen.add(key)
        unique_events.append(event)

    return unique_events


def send_admin_discord(message):
    webhook_url = (
        os.getenv("WEBHOOK_ADMIN")
        or os.getenv("WEBHOOK_ADMIN_DISCORD")
        or os.getenv("DISCORD_ADMIN_WEBHOOK")
        or os.getenv("WEBHOOK_MANAGE")
    )

    if not webhook_url:
        print("[WARN] Admin Discord webhook is not configured")
        logging.warning("Admin Discord webhook is not configured")
        return False

    response = requests.post(webhook_url, json={"content": message}, timeout=10)
    if response.status_code != 204:
        raise RuntimeError(f"Discord admin webhook error: {response.status_code} {response.text}")

    return True


def handle_scraper_health_messages(messages):
    for message in messages:
        if message.startswith("scraper_health_warning:"):
            logging.warning(message)
            continue
        if message.startswith("scraper_health_info:") or message.startswith("scraper_health:"):
            logging.info(message)
            continue
        if message.startswith("⚠️ "):
            logging.warning(message)
            try:
                send_admin_discord(message)
            except Exception as exc:
                print(f"[WARN] Failed to send admin notification: {exc}")
                logging.warning(f"管理Discord通知送信失敗: {exc}")


def run_scraper_health_dashboard(force=False):
    from tools.health.build_scraper_dashboard import build_dashboard

    result = build_dashboard(force=force)
    if result.get("skipped"):
        logging.info(
            "scraper_dashboard: skipped reason=%s last_run_at=%s",
            result.get("reason", ""),
            result.get("last_run_at", ""),
        )
        return

    dashboard = result.get("dashboard")
    if not isinstance(dashboard, dict):
        logging.warning("scraper_dashboard: failed empty_result")
        return

    warnings = dashboard.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    infos = dashboard.get("infos")
    if not isinstance(infos, list):
        infos = []

    logging.info("scraper_dashboard: generated warnings=%s infos=%s", len(warnings), len(infos))
    for info in infos:
        logging.info("scraper_dashboard_info: %s", info)
    for warning in warnings:
        logging.warning("scraper_dashboard_warning: %s", warning)

    if warnings:
        message = "⚠️ Scraper Health Dashboard\n\n" + "\n".join(
            f"・{warning}" for warning in warnings
        )
        try:
            send_admin_discord(message)
        except Exception as exc:
            print(f"[WARN] Failed to send admin notification: {exc}")
            logging.warning(f"管理Discord通知送信失敗: {exc}")


def _is_empty_time(value):
    return not value or value in ("未定", "時間情報なし")


def format_event_time(event):
    time_text = str(event.get("time", "")).strip()
    end_time = str(event.get("end_time", "")).strip()

    has_time = not _is_empty_time(time_text)
    has_end_time = not _is_empty_time(end_time)

    if has_time and has_end_time:
        return f"{time_text}〜{end_time}"

    if has_time:
        return f"{time_text}〜"

    if has_end_time:
        return f"終了予定 {end_time}"

    return "時刻未定"


def sort_events(events):
    def sort_key(event):
        time_text = str(event.get("time", "")).strip()
        end_time = str(event.get("end_time", "")).strip()

        has_time = re.fullmatch(r"\d{1,2}:\d{2}", time_text) is not None
        has_end_time = re.fullmatch(r"\d{1,2}:\d{2}", end_time) is not None
        notify_time = time_text if has_time else end_time if has_end_time else ""

        if has_time and has_end_time:
            display_priority = 0
        elif has_time:
            display_priority = 1
        elif has_end_time:
            display_priority = 2
        else:
            display_priority = 3

        if notify_time:
            hour, minute = map(int, notify_time.split(":"))
            time_key = (0, hour, minute, display_priority)
        else:
            time_key = (1, 99, 99, display_priority)

        return (
            *time_key,
            event.get("venue", ""),
            event.get("title", ""),
        )

    return sorted(events, key=sort_key)



def load_non_road_manual_csv_events():
    events = []

    events += load_csv_events("misonoza.csv", "misonoza")
    events += load_csv_events("shiki.csv", "shiki")
    events += load_csv_events("spot.csv", "spot")
    events += load_csv_events("ajipara.csv", "ajipara")

    return events


def load_road_events(target_date, csv_path=ROAD_CSV_PATH):
    if not csv_path.exists():
        print(f"道路交通情報CSVなし: {csv_path}")
        logging.info("道路交通情報CSVなし: %s", csv_path)
        return []

    if isinstance(target_date, datetime):
        target_date = target_date.date()

    if isinstance(target_date, date):
        target_strings = {
            target_date.strftime("%Y/%m/%d"),
            target_date.strftime("%Y-%m-%d"),
        }
    else:
        target_text = str(target_date)
        target_strings = {
            target_text,
            target_text.replace("/", "-"),
            target_text.replace("-", "/"),
        }

    events = []

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            if row.get("status", "").strip() == "inactive":
                continue

            event = {
                "date": row.get("date", "").strip(),
                "time": row.get("time", "").strip() or "未定",
                "end_time": row.get("end_time", "").strip(),
                "venue": row.get("venue", "").strip(),
                "title": row.get("title", "").strip(),
                "source": row.get("source", "").strip(),
                "status": row.get("status", "").strip(),
                "note": row.get("note", "").strip() or "イベント",
                "url": row.get("url", "").strip(),
            }

            if event["date"] in target_strings and event["title"]:
                events.append(event)

    return events



def _target_date_strings(target_date):
    if isinstance(target_date, datetime):
        target_date = target_date.date()

    if isinstance(target_date, date):
        return {
            target_date.strftime("%Y/%m/%d"),
            target_date.strftime("%Y-%m-%d"),
        }

    target_text = str(target_date)
    return {
        target_text,
        target_text.replace("/", "-"),
        target_text.replace("-", "/"),
    }


def load_csv_daily_notice_events(target_date, csv_path, label):
    csv_path = Path(csv_path)

    if not csv_path.exists():
        print(f"{label}CSVなし: {csv_path}")
        logging.info("%sCSVなし: %s", label, csv_path)
        return []

    target_strings = _target_date_strings(target_date)
    events = []

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            if row.get("status", "").strip() == "inactive":
                continue

            event = {
                "date": row.get("date", "").strip(),
                "time": row.get("time", "").strip(),
                "end_time": row.get("end_time", "").strip(),
                "venue": row.get("venue", "").strip(),
                "title": row.get("title", "").strip(),
                "source": row.get("source", "").strip(),
                "status": row.get("status", "").strip(),
                "note": row.get("note", "").strip(),
                "url": row.get("url", "").strip(),
            }

            if event["date"] in target_strings and event["title"]:
                events.append(event)

    return sort_events(events)


def format_notice_time(event, unknown_text="時刻未定"):
    time_text = str(event.get("time", "")).strip()
    end_time = str(event.get("end_time", "")).strip()

    has_time = not _is_empty_time(time_text)
    has_end_time = not _is_empty_time(end_time)

    if has_time and has_end_time:
        return f"{time_text}〜{end_time}"

    if has_time:
        return f"{time_text}〜"

    if has_end_time:
        return f"〜{end_time}"

    return unknown_text


def render_cruise_notice_item(event):
    title = event.get("title", "").strip()
    venue = event.get("venue", "").strip() or "不明"

    return (
        f"🚢 {title}\n"
        f"📍 {venue}\n"
        f"🕐 {format_notice_time(event, '時間未定')}"
    )


def render_asia_notice_item(event):
    title = event.get("title", "").strip()
    venue = event.get("venue", "").strip() or "不明"

    return (
        f"📢 {format_notice_time(event)}\n"
        f"📍 {venue}\n"
        f"🎺 {title}"
    )


def build_csv_daily_notice_message(events, target_date, header_title, count_icon, count_unit, render_item):
    if isinstance(target_date, datetime):
        target_date = target_date.date()

    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    weekday = weekdays[target_date.weekday()]

    message = f"{header_title}\n"
    message += target_date.strftime("%m月%d日") + f"（{weekday}）\n"
    message += f"{count_icon} 本日 {len(events)}{count_unit}\n"
    message += "────────────\n"

    for index, event in enumerate(events):
        if index:
            message += "────────────\n"

        message += render_item(event).rstrip() + "\n"

    return message.rstrip()


def send_csv_daily_notice(
    target_date,
    csv_path,
    webhook_env,
    header_title,
    count_icon,
    count_unit,
    render_item,
    label,
):
    events = load_csv_daily_notice_events(target_date, csv_path, label)

    if not events:
        print(f"{label}情報: 当日データなしのため送信スキップ")
        logging.info("%s情報: 当日データなしのため送信スキップ", label)
        return False

    webhook_url = os.getenv(webhook_env)
    if not webhook_url:
        print(f"{label}情報: {webhook_env} 未設定のため送信スキップ")
        logging.info("%s情報: %s 未設定のため送信スキップ", label, webhook_env)
        return False

    message = build_csv_daily_notice_message(
        events,
        target_date,
        header_title,
        count_icon,
        count_unit,
        render_item,
    )

    if DRY_RUN:
        print(message)
        logging.info("DRY_RUN=True のため%s情報Discord送信をスキップ", label)
        return False

    response = requests.post(webhook_url, json={"content": message}, timeout=10)
    if response.status_code != 204:
        raise RuntimeError(f"{label}情報Discord投稿エラー: {response.status_code} {response.text}")

    print(f"{label}Discord送信成功")
    logging.info("%sDiscord送信成功: %s件", label, len(events))
    return True


def send_cruise_info(target_date):
    return send_csv_daily_notice(
        target_date=target_date,
        csv_path=CRUISE_CSV_PATH,
        webhook_env=CRUISE_WEBHOOK_ENV,
        header_title="🚢 クルーズ船情報",
        count_icon="🚢",
        count_unit="隻",
        render_item=render_cruise_notice_item,
        label="クルーズ船",
    )


def send_asia_info(target_date):
    return send_csv_daily_notice(
        target_date=target_date,
        csv_path=ASIA_CSV_PATH,
        webhook_env=ASIA_WEBHOOK_ENV,
        header_title="🏟️ アジア大会情報",
        count_icon="🏟️",
        count_unit="件",
        render_item=render_asia_notice_item,
        label="アジア大会",
    )


def sort_road_events(events):
    category_rank = {category: index for index, category in enumerate(ROAD_CATEGORY_ORDER)}

    return sorted(
        events,
        key=lambda event: (
            category_rank.get(event.get("note", ""), len(ROAD_CATEGORY_ORDER)),
            event.get("venue", ""),
            event.get("title", ""),
        ),
    )


def group_road_events(events):
    grouped = {category: [] for category in ROAD_CATEGORY_ORDER}

    for event in sort_road_events(events):
        category = event.get("note", "") or "イベント"
        grouped.setdefault(category, []).append(event)

    return grouped


def build_road_message(events, target_date):
    if isinstance(target_date, datetime):
        target_date = target_date.date()

    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    weekday = weekdays[target_date.weekday()]

    message = "🚗🚓🚨🏍️ 道路交通情報\n"
    message += target_date.strftime("%m月%d日") + f"（{weekday}）\n"
    message += "────────────\n"

    grouped = group_road_events(events)
    wrote_group = False

    for category in ROAD_CATEGORY_ORDER:
        category_events = grouped.get(category, [])
        if not category_events:
            continue

        if wrote_group:
            message += "────────────\n"

        icon = ROAD_CATEGORY_ICONS.get(category, "ℹ️")
        message += f"{icon} {category}\n"

        for event in category_events:
            venue = event.get("venue", "").strip()
            title = event.get("title", "").strip()

            if category == "重点取締" and venue == "愛知県内":
                message += f"・{title}\n"
            elif venue:
                message += f"📍 {venue}\n{title}\n"
            else:
                message += f"・{title}\n"

        wrote_group = True

    message += "────────────\n"
    message += "※道路交通情報・オービス実績データは、あくまでも参考情報です。\n"
    message += "鵜呑みにせず、速度を守った安全運転をお願いします。\n"
    message += "別地点や、これまで見かけなかった取締があれば、当チャンネルで呟いてください🚕🚨\n"
    return message.rstrip()


def send_road_traffic_info(target_date):
    road_events = load_road_events(target_date)

    if not road_events:
        print("道路交通情報: 当日データなしのため送信スキップ")
        logging.info("道路交通情報: 当日データなしのため送信スキップ")
        return False

    webhook_url = os.getenv(ROAD_WEBHOOK_ENV)
    if not webhook_url:
        print(f"道路交通情報: {ROAD_WEBHOOK_ENV} 未設定のため送信スキップ")
        logging.info("道路交通情報: %s 未設定のため送信スキップ", ROAD_WEBHOOK_ENV)
        return False

    message = build_road_message(road_events, target_date)

    if DRY_RUN:
        print(message)
        logging.info("DRY_RUN=True のため道路交通情報Discord送信をスキップ")
        return False

    response = requests.post(webhook_url, json={"content": message}, timeout=10)
    if response.status_code != 204:
        raise RuntimeError(f"道路交通情報Discord投稿エラー: {response.status_code} {response.text}")

    print("道路交通情報Discord送信成功")
    logging.info("道路交通情報Discord送信成功: %s件", len(road_events))
    return True


def main():

    logging.info("名古屋イベントBOT起動")

    today = datetime.now(JST)
    #下記はテスト用。
    #today = datetime(2026, 6, 10, tzinfo=JST)
    run_openmeteo_forecast_scheduler(today)

    events = []

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        vantelin_events, vantelin_messages = scrape_vantelin_with_health(page, today)
        events += vantelin_events
        handle_scraper_health_messages(vantelin_messages)
        logging.info("バンテリン取得完了")

        jailhouse_events, jailhouse_messages = scrape_jailhouse_with_health(page, today)
        events += jailhouse_events
        handle_scraper_health_messages(jailhouse_messages)
        logging.info("JAILHOUSE取得完了")

        sundayfolk_events, sundayfolk_messages = scrape_sundayfolk_with_health(page, today)
        events += sundayfolk_events
        handle_scraper_health_messages(sundayfolk_messages)
        logging.info("サンデーフォーク取得完了")

        kyodo_events, kyodo_messages = scrape_kyodo_tokai_with_health(page, today)
        events += kyodo_events
        handle_scraper_health_messages(kyodo_messages)
        logging.info("キョードー東海取得完了")

        misonoza_events, misonoza_messages = scrape_misonoza_with_notifications(page, today)
        misonoza_events = dedupe_misonoza_events(misonoza_events)

        handle_scraper_health_messages(
            [
                message for message in misonoza_messages
                if message.startswith("scraper_health")
            ]
        )
        for message in [
            message for message in misonoza_messages
            if not message.startswith("scraper_health")
        ]:
            print()
            print(message)
            try:
                send_admin_discord(message)
            except Exception as exc:
                print(f"[WARN] Failed to send admin notification: {exc}")
                logging.warning(f"管理Discord通知送信失敗: {exc}")

        write_misonoza_csv(misonoza_events, "csv_events/misonoza.csv")
        logging.info("御園座CSV更新完了: csv_events/misonoza.csv")

        events += misonoza_events
        logging.info(f"御園座取得完了: {len(misonoza_events)}件")

        shiki_events, shiki_messages = scrape_shiki_with_health(page, today)
        handle_scraper_health_messages(shiki_messages)
        write_shiki_csv(shiki_events, "csv_events/shiki.csv", today=today)
        logging.info(f"劇団四季CSV更新完了: csv_events/shiki.csv / {len(shiki_events)}件")

        browser.close()

    run_scraper_health_dashboard()

    manual_events = filter_events_by_date(load_non_road_manual_csv_events(), today)
    events += manual_events
    logging.info(f"手入力CSV取得完了: {len(manual_events)}件")

    all_google_sheet_events = load_all_google_sheet_events()
    google_sheet_events = filter_events_by_date(all_google_sheet_events, today)
    events += google_sheet_events
    logging.info(f"Googleスプレッドシート取得完了: 全{len(all_google_sheet_events)}件 / 今日{len(google_sheet_events)}件")

    events = normalize_events(events, today)
    today_events = filter_events_by_date(events, today)
    today_events = sort_events(today_events)
    today_events = dedupe_display_events(today_events)

    save_daily_debug_log(today_events, today)

    print(f"取得件数: {len(today_events)}件")
    logging.info(f"取得件数: {len(today_events)}件")
    print(f"Discord本文生成対象: id={id(today_events)} 件数={len(today_events)}")
    logging.info(f"Discord本文生成対象: id={id(today_events)} 件数={len(today_events)}")

    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    weekday = weekdays[today.weekday()]
    rokuyou = get_rokuyou()

    message = "🗓️ 名古屋イベント情報\n\n"
    message += today.strftime("%m月%d日") + f"（{weekday}） {rokuyou}\n\n"
    message += f"🚕 本日 {len(today_events)}件\n\n"
    message += "────────────\n\n"

    for e in today_events:

        artists = e["title"].split("|")[0].strip()

        message += (
            f"📢 {format_event_time(e)}\n\n"
            f"📍 {e['venue']}\n\n"
            f"🎺 {artists}\n\n"
            f"────────────\n\n"
        )

    message += "※自動取得ベータ版です😇\n\n"
    message += "誤検知・貸切公演の漏れ・取得漏れ・時間違いがあります\n\n"
    message += "参考程度にご利用ください\n"

    try:
        cruise_events = scrape_cruise()
        print("クルーズ船PDF取得成功")
        print(f"クルーズ船CSV生成: {len(cruise_events)}件")
        logging.info("クルーズ船CSV生成: %s件", len(cruise_events))
    except Exception as exc:
        print(f"[WARN] クルーズ船スクレイプ失敗: {exc}")
        logging.exception("クルーズ船スクレイプ失敗")

    if DRY_RUN:
        print(message)
        logging.info("DRY_RUN=True のため Discord送信をスキップ")
    else:
        print("Discord送信開始")
        sent = send_discord(message)
        if not sent:
            logging.error("Discord送信失敗")
            raise RuntimeError("Discord送信に失敗しました")
        print("Discord送信成功")
        logging.info("Discord送信完了")

    try:
        send_road_traffic_info(today)
    except Exception as exc:
        print(f"[WARN] 道路交通情報Discord送信失敗: {exc}")
        logging.exception("道路交通情報Discord送信失敗")

    try:
        send_cruise_info(today)
    except Exception:
        print("[WARN] クルーズ船Discord送信失敗")
        logging.exception("クルーズ船Discord送信失敗")

    try:
        send_asia_info(today)
    except Exception:
        print("[WARN] アジア大会Discord送信失敗")
        logging.exception("アジア大会Discord送信失敗")

    try:
        sync_csv_to_sheet("csv_events/misonoza.csv", "御園座")
        print("Synced csv_events/misonoza.csv to 御園座 sheet")
        logging.info("御園座Google Sheets同期完了")
    except Exception as exc:
        print(f"[WARN] Failed to sync misonoza sheet: {exc}")
        logging.warning(f"御園座Google Sheets同期失敗: {exc}")

    try:
        sync_road_csv_to_sheet()
    except Exception as exc:
        print(f"[WARN] 道路情報Google Sheets同期失敗: {exc}")
        logging.exception("道路情報Google Sheets同期失敗")

    try:
        archive_old_road_rows(today)
    except Exception as exc:
        print(f"[WARN] 道路情報過去ログ退避失敗: {exc}")
        logging.exception("道路情報過去ログ退避失敗")

    try:
        sync_cruise_csv_to_sheet()
    except Exception:
        print("[WARN] クルーズ船Google Sheets同期失敗")
        logging.exception("クルーズ船Google Sheets同期失敗")

    try:
        cleanup_old_cruise_rows(today)
    except Exception:
        print("[WARN] クルーズ船シート削除失敗")
        logging.exception("クルーズ船シート削除失敗")

    try:
        sync_asia_csv_to_sheet()
    except Exception:
        print("[WARN] アジア大会Google Sheets同期失敗")
        logging.exception("アジア大会Google Sheets同期失敗")

    try:
        cleanup_old_asia_rows(today)
    except Exception:
        print("[WARN] アジア大会シート削除失敗")
        logging.exception("アジア大会シート削除失敗")


if __name__ == "__main__":
    main()
