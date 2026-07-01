#!/usr/bin/env python3
"""愛知県警の月次取締予定PDF公開を監視する。"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from scrapers import road_pdf  # noqa: E402


JST = ZoneInfo("Asia/Tokyo")
STATE_PATH = ROOT / "data" / "road_monthly_pdf_state.json"
CSV_PATH = ROOT / "csv_events" / "road.csv"
LOG_DIR = ROOT / "logs"
REQUEST_TIMEOUT_SECONDS = 30


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_DIR / "road_monthly_pdf.log",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def month_key_for(month: int, *, now: datetime) -> str:
    return f"R{now.year - 2018}.{month}"


def month_state_key(month_key: str) -> str:
    return month_key.replace(".", "_")


def download_pdf(month_key: str) -> tuple[bool, int, str]:
    url = road_pdf.pdf_url(month_key)
    path = ROOT / road_pdf.pdf_path(month_key)
    request = urllib.request.Request(url, headers={"User-Agent": "nagoya-event-road-monthly/1.0"})

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        return False, int(exc.code), str(exc)
    except (OSError, urllib.error.URLError) as exc:
        return False, 0, str(exc)

    if not 200 <= status_code < 300:
        return False, status_code, f"HTTP{status_code}"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return True, status_code, str(path)


def regenerate_road_csv(month_key: str) -> tuple[int, list[str]]:
    if month_key not in road_pdf.PDF_MONTHS:
        road_pdf.PDF_MONTHS.append(month_key)
    events, health_messages = road_pdf.extract_all_events_with_health(force_download=False)
    road_pdf.save_road_csv(events, CSV_PATH)
    return len(events), health_messages


def csv_count(path: Path = CSV_PATH) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return sum(1 for _row in csv.DictReader(f))


def run_sheet_sync() -> tuple[bool, str]:
    command = [sys.executable, str(ROOT / "tools" / "db" / "import_sheet_road.py")]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0, output or f"exit={result.returncode}"


def setting(name: str) -> str:
    value = getattr(config, name, None)
    if value is None:
        value = os.getenv(name, "")
    return str(value).strip()


def admin_channel_id() -> str:
    for name in ("GEMMA_CHANNEL_ADMIN", "ADMIN_CHANNEL_ID", "GEMMA_CHANNEL_TEST"):
        value = setting(name)
        if value:
            return value
    return ""


def post_discord_bot(content: str) -> tuple[bool, str]:
    token = setting("DISCORD_BOT_TOKEN")
    channel_id = admin_channel_id()
    if not token or not channel_id:
        return False, "admin Discord Bot設定未完了"

    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "nagoya-event-road-monthly/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            return 200 <= int(response.status) < 300, f"HTTP{response.status} {body}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP{exc.code} {exc.read().decode('utf-8', errors='replace')}"
    except (OSError, urllib.error.URLError) as exc:
        return False, str(exc)


def admin_webhook_url() -> str:
    for name in ("WEBHOOK_ADMIN", "WEBHOOK_ADMIN_DISCORD", "DISCORD_ADMIN_WEBHOOK", "WEBHOOK_MANAGE"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def post_discord_webhook(content: str) -> tuple[bool, str]:
    webhook_url = admin_webhook_url()
    if not webhook_url:
        return False, "admin Discord webhook設定未完了"

    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"content": content}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "nagoya-event-road-monthly/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            return 200 <= int(response.status) < 300, f"HTTP{response.status} {body}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP{exc.code} {exc.read().decode('utf-8', errors='replace')}"
    except (OSError, urllib.error.URLError) as exc:
        return False, str(exc)


def post_admin_discord(content: str) -> tuple[bool, str]:
    bot_ok, bot_status = post_discord_bot(content)
    if bot_ok:
        return bot_ok, bot_status
    webhook_ok, webhook_status = post_discord_webhook(content)
    if webhook_ok:
        return webhook_ok, webhook_status
    return False, f"{bot_status}; {webhook_status}"


def build_success_message(month: int, now: datetime, csv_rows: int, sync_ok: bool, sync_output: str) -> str:
    sync_status = "成功" if sync_ok else "失敗"
    return "\n".join(
        [
            f"✅ 愛知県警 {month}月版取締予定PDF取得成功",
            f"取得時刻: {now.isoformat(timespec='seconds')}",
            f"CSV件数: {csv_rows}件",
            f"Sheets同期結果: {sync_status}",
            sync_output[:1200],
        ]
    )


def build_failure_message(month: int, now: datetime, status: str) -> str:
    return "\n".join(
        [
            f"⚠️ 愛知県警 {month}月版取締予定PDF 未取得",
            "18時時点で公開確認できず。土日・休日遅延の可能性あり",
            f"確認時刻: {now.isoformat(timespec='seconds')}",
            f"取得結果: {status}",
        ]
    )


def mark_success(state: dict[str, Any], key: str, *, now: datetime, csv_rows: int, sync_ok: bool) -> None:
    state[key] = {
        "downloaded": True,
        "downloaded_at": now.isoformat(timespec="seconds"),
        "csv_rows": csv_rows,
        "sheet_sync_ok": sync_ok,
    }
    save_state(state)


def mark_failure_notified(state: dict[str, Any], key: str, *, now: datetime, status: str) -> None:
    month_state = state.get(key) if isinstance(state.get(key), dict) else {}
    month_state.update(
        {
            "failure_notified": True,
            "failure_notified_at": now.isoformat(timespec="seconds"),
            "last_status": status,
        }
    )
    state[key] = month_state
    save_state(state)


def check_monthly_pdf(*, month: int | None = None, force: bool = False, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(JST)
    target_month = month or current.month
    month_key = month_key_for(target_month, now=current)
    state_key = month_state_key(month_key)
    state = load_state()
    month_state = state.get(state_key) if isinstance(state.get(state_key), dict) else {}

    if month_state.get("downloaded") and not force:
        print(f"road_monthly_pdf: skipped already downloaded {month_key}", flush=True)
        logging.info("road_monthly_pdf: skipped already downloaded %s", month_key)
        return {"status": "skipped", "reason": "already_downloaded", "month_key": month_key}

    ok, status_code, detail = download_pdf(month_key)
    if ok:
        csv_rows, health_messages = regenerate_road_csv(month_key)
        sync_ok, sync_output = run_sheet_sync()
        message = build_success_message(target_month, current, csv_rows or csv_count(), sync_ok, sync_output)
        notify_ok, notify_status = post_admin_discord(message)
        mark_success(state, state_key, now=current, csv_rows=csv_rows or csv_count(), sync_ok=sync_ok)
        print(f"road_monthly_pdf: downloaded {month_key}", flush=True)
        print(f"road_monthly_pdf: admin_notify={notify_status}", flush=True)
        for health_message in health_messages:
            logging.info("road_monthly_pdf_health: %s", health_message)
        return {
            "status": "downloaded",
            "month_key": month_key,
            "csv_rows": csv_rows,
            "sheet_sync_ok": sync_ok,
            "admin_notified": notify_ok,
            "admin_notify_status": notify_status,
        }

    status = f"HTTP{status_code}" if status_code else detail
    logging.info("road_monthly_pdf: not_available month=%s status=%s", month_key, status)
    if current.hour < 18:
        print(f"road_monthly_pdf: not available before 18:00 {month_key} {status}", flush=True)
        return {"status": "not_available", "month_key": month_key, "download_status": status}

    if month_state.get("failure_notified") and not force:
        print(f"road_monthly_pdf: skipped failure already notified {month_key}", flush=True)
        return {"status": "skipped", "reason": "failure_already_notified", "month_key": month_key}

    notify_ok, notify_status = post_admin_discord(build_failure_message(target_month, current, status))
    if notify_ok:
        mark_failure_notified(state, state_key, now=current, status=status)
    print(f"road_monthly_pdf: missing after 18:00 {month_key}", flush=True)
    print(f"road_monthly_pdf: admin_notify={notify_status}", flush=True)
    return {
        "status": "missing_after_18",
        "month_key": month_key,
        "download_status": status,
        "admin_notified": notify_ok,
        "admin_notify_status": notify_status,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="愛知県警の月次取締予定PDF公開を監視する。")
    parser.add_argument("--force", action="store_true", help="取得済みでも再取得・再生成する。")
    parser.add_argument("--month", type=int, default=None, help="確認対象月。省略時は当月。")
    return parser.parse_args()


def main() -> int:
    setup_logging()
    args = parse_args()
    result = check_monthly_pdf(month=args.month, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
