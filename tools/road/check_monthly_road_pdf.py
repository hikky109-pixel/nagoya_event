#!/usr/bin/env python3
"""愛知県警の月次取締予定PDF公開を監視する。"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time
from email.utils import parsedate_to_datetime
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
PUBLICATION_PAGE_URL = (
    "https://www.pref.aichi.jp/police/koutsu/ko-shidou/"
    "sokudokanri-issei.html"
)
DEBUG_DIR = ROOT / "data" / "debug" / "road_monthly"


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


def road_log(key: str, value: Any) -> None:
    message = f"{key}: {value}"
    print(message, flush=True)
    logging.info(message)


def _cache_busted_url(url: str, now: datetime) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}_={int(now.timestamp())}"


def fetch_publication_page(now: datetime) -> dict[str, Any]:
    request = urllib.request.Request(
        _cache_busted_url(PUBLICATION_PAGE_URL, now),
        headers={
            "User-Agent": "nagoya-event-road-monthly/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
            return {
                "ok": 200 <= int(response.status) < 300,
                "status_code": int(response.status),
                "final_url": response.geturl(),
                "body": body.decode("utf-8", errors="replace"),
                "length": len(body),
                "last_modified": str(response.headers.get("Last-Modified") or ""),
                "etag": str(response.headers.get("ETag") or ""),
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status_code": int(exc.code), "error": str(exc)}
    except (OSError, urllib.error.URLError) as exc:
        return {"ok": False, "status_code": 0, "error": str(exc)}


def page_month_info(html: str, month_key: str) -> dict[str, Any]:
    links = re.findall(r"torishimariyotei(R\d+\.\d+)\.pdf", html, re.IGNORECASE)
    unique_links = list(dict.fromkeys(links))
    return {
        "month_key": month_key,
        "current_month_published": month_key in unique_links,
        "published_months": unique_links,
        "previous_month_only": bool(unique_links) and month_key not in unique_links,
    }


def download_pdf(month_key: str, now: datetime) -> dict[str, Any]:
    url = road_pdf.pdf_url(month_key)
    path = ROOT / road_pdf.pdf_path(month_key)
    request = urllib.request.Request(
        _cache_busted_url(url, now),
        headers={
            "User-Agent": "nagoya-event-road-monthly/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
            status_code = int(response.status)
            final_url = response.geturl()
            last_modified = str(response.headers.get("Last-Modified") or "")
            etag = str(response.headers.get("ETag") or "")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status_code": int(exc.code), "error": str(exc), "url": url}
    except (OSError, urllib.error.URLError) as exc:
        return {"ok": False, "status_code": 0, "error": str(exc), "url": url}

    if not 200 <= status_code < 300:
        return {"ok": False, "status_code": status_code, "error": f"HTTP{status_code}", "url": url}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        "ok": True,
        "status_code": status_code,
        "final_url": final_url,
        "path": str(path),
        "url": url,
        "length": len(body),
        "last_modified": last_modified,
        "etag": etag,
    }


def regenerate_road_csv(month_key: str) -> tuple[int, list[str]]:
    if month_key not in road_pdf.PDF_MONTHS:
        road_pdf.PDF_MONTHS.append(month_key)
    events, health_messages = road_pdf.extract_all_events_with_health(force_download=False)
    road_pdf.save_road_csv(events, CSV_PATH)
    return len(events), health_messages


def extract_target_month_records(month_key: str) -> tuple[list[dict[str, Any]], int]:
    path = ROOT / road_pdf.pdf_path(month_key)
    url = road_pdf.pdf_url(month_key)
    place_records = road_pdf.extract_events(path, url)
    focus_records = road_pdf.extract_focus_events(path, url)
    raw_count = len(place_records) + len(focus_records)
    return road_pdf.sort_events(road_pdf.dedupe_events(place_records + focus_records)), raw_count


def future_records(
    records: list[dict[str, Any]],
    target_date: date,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for record in records:
        record_date = str(record.get("date") or "")
        if record_date < target_date.isoformat():
            road_log(
                "road_record_skip_reason",
                f"past_record date={record_date} venue={record.get('venue', '')}",
            )
            continue
        kept.append(record)
    return kept


def explicit_no_schedule(path: Path) -> bool:
    try:
        with road_pdf.pdfplumber.open(path) as pdf:
            text = " ".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return False
    normalized = " ".join(text.split())
    return any(
        marker in normalized
        for marker in ("予定なし", "取締り予定はありません", "取締予定はありません")
    )


def classify_zero_result(
    page_info: dict[str, Any],
    pdf_path: Path | None,
    page_result: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> str:
    if pdf_path is not None and explicit_no_schedule(pdf_path):
        return "official_no_schedule"
    if page_info.get("previous_month_only"):
        return "publication_not_updated_yet"
    last_modified = str((page_result or {}).get("last_modified") or "")
    if last_modified and now is not None:
        try:
            modified_at = parsedate_to_datetime(last_modified).astimezone(JST)
        except (TypeError, ValueError):
            modified_at = None
        release_time = datetime.combine(now.date(), time(10, 0), tzinfo=JST)
        if modified_at is not None and modified_at < release_time:
            return "publication_not_updated_yet"
    return "fetch_or_parse_error"


def save_debug_snapshot(snapshot: dict[str, Any], now: datetime) -> Path:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / f"{now:%Y%m%d_%H%M%S}.json"
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def csv_count(path: Path = CSV_PATH) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return sum(1 for _row in csv.DictReader(f))


def _sheet_sync_failure_reason(exc: BaseException) -> str:
    detail = f"{type(exc).__name__}: {exc}".lower()
    if type(exc).__name__ == "RefreshError" or "invalid_grant" in detail:
        return "oauth_refresh_failed"
    return "sheet_sync_error"


def run_sheet_sync(
    target_date: date,
    *,
    sync_func: Any = None,
    archive_func: Any = None,
) -> dict[str, Any]:
    if sync_func is None or archive_func is None:
        from scrapers.utils.google_sheet_events import (  # noqa: PLC0415
            archive_old_road_rows,
            sync_road_csv_to_sheet,
        )

        sync_func = sync_func or sync_road_csv_to_sheet
        archive_func = archive_func or archive_old_road_rows

    try:
        result = sync_func(str(CSV_PATH))
        if not isinstance(result, dict) or not result.get("synced"):
            reason = str(result.get("reason") or "sheet_sync_rejected") if isinstance(result, dict) else "sheet_sync_rejected"
            road_log("road_sheet_sync_status", "failed")
            road_log("road_sheet_sync_reason", reason)
            road_log("road_sheet_sync_records", 0)
            return {"ok": False, "reason": reason, "records": 0, "output": str(result)}

        archive_result = archive_func(target_date, str(CSV_PATH))
        synced_records = int(result.get("merged_records") or 0)
        output = json.dumps(
            {"sync": result, "archive": archive_result},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        road_log("road_sheet_sync_status", "success")
        road_log("road_sheet_sync_reason", "none")
        road_log("road_sheet_sync_records", synced_records)
        return {"ok": True, "reason": "", "records": synced_records, "output": output}
    except Exception as exc:
        reason = _sheet_sync_failure_reason(exc)
        road_log("road_sheet_sync_status", "failed")
        road_log("road_sheet_sync_reason", reason)
        road_log("road_sheet_sync_records", 0)
        logging.exception("road_sheet_sync_failed reason=%s", reason)
        return {
            "ok": False,
            "reason": reason,
            "records": 0,
            "output": f"{type(exc).__name__}: {exc}",
        }


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
            "10:15再試行後も公開・解析を確認できませんでした。",
            f"確認時刻: {now.isoformat(timespec='seconds')}",
            f"取得結果: {status}",
        ]
    )


def mark_success(
    state: dict[str, Any],
    key: str,
    *,
    now: datetime,
    csv_rows: int,
    sync_result: dict[str, Any],
) -> None:
    month_state = state.get(key) if isinstance(state.get(key), dict) else {}
    month_state.update({
        "downloaded": True,
        "downloaded_at": now.isoformat(timespec="seconds"),
        "csv_rows": csv_rows,
        "sheet_sync_ok": bool(sync_result["ok"]),
        "sheet_sync_pending": not bool(sync_result["ok"]),
        "sheet_sync_reason": str(sync_result["reason"]),
        "sheet_sync_records": int(sync_result["records"]),
        "sheet_sync_attempted_at": now.isoformat(timespec="seconds"),
    })
    state[key] = month_state
    save_state(state)


def retry_pending_sheet_sync(
    state: dict[str, Any],
    state_key: str,
    month_key: str,
    month_state: dict[str, Any],
    current: datetime,
) -> dict[str, Any]:
    road_log("road_sheet_sync_retry", "saved_csv_only")
    sync_result = run_sheet_sync(current.date())
    month_state.update(
        {
            "sheet_sync_ok": bool(sync_result["ok"]),
            "sheet_sync_pending": not bool(sync_result["ok"]),
            "sheet_sync_reason": str(sync_result["reason"]),
            "sheet_sync_records": int(sync_result["records"]),
            "sheet_sync_attempted_at": current.isoformat(timespec="seconds"),
        }
    )
    state[state_key] = month_state
    save_state(state)
    return {
        "status": "sheet_sync_retried" if sync_result["ok"] else "sheet_sync_pending",
        "month_key": month_key,
        "csv_rows": int(month_state.get("csv_rows") or csv_count()),
        "sheet_sync_ok": bool(sync_result["ok"]),
        "sheet_sync_pending": not bool(sync_result["ok"]),
        "sheet_sync_reason": str(sync_result["reason"]),
        "sheet_sync_records": int(sync_result["records"]),
    }


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

    road_log("road_scraper_started_at", current.isoformat(timespec="seconds"))

    if month_state.get("downloaded") and month_state.get("sheet_sync_pending") and not force:
        return retry_pending_sheet_sync(state, state_key, month_key, month_state, current)

    if month_state.get("downloaded") and not force:
        print(f"road_monthly_pdf: skipped already downloaded {month_key}", flush=True)
        logging.info("road_monthly_pdf: skipped already downloaded %s", month_key)
        return {"status": "skipped", "reason": "already_downloaded", "month_key": month_key}

    page_result = fetch_publication_page(current)
    page_html = str(page_result.get("body") or "")
    page_info = page_month_info(page_html, month_key)
    road_log("road_scraper_http_status", page_result.get("status_code", 0))
    road_log("road_scraper_final_url", page_result.get("final_url", PUBLICATION_PAGE_URL))
    road_log("road_scraper_html_length", page_result.get("length", 0))
    road_log(
        "road_scraper_page_month",
        ",".join(page_info.get("published_months", [])) or "none",
    )

    pdf_result = download_pdf(month_key, current)
    road_log("road_scraper_http_status", f"pdf={pdf_result.get('status_code', 0)}")
    road_log("road_scraper_final_url", pdf_result.get("final_url", road_pdf.pdf_url(month_key)))
    road_log("road_scraper_html_length", f"pdf={pdf_result.get('length', 0)}")
    if pdf_result.get("ok"):
        pdf_path = Path(str(pdf_result["path"]))
        try:
            target_records, raw_count = extract_target_month_records(month_key)
            parse_error = ""
        except Exception as exc:
            target_records = []
            raw_count = 0
            parse_error = f"{type(exc).__name__}: {exc}"
        parsed_count = len(target_records)
        current_and_future = future_records(target_records, current.date())
        road_log("road_scraper_raw_records", raw_count)
        road_log("road_scraper_parsed_records", parsed_count)
        road_log("road_scraper_future_records", len(current_and_future))

        if not target_records:
            diagnosis = (
                "fetch_or_parse_error"
                if parse_error
                else classify_zero_result(page_info, pdf_path, page_result, current)
            )
            previous_attempts = int(month_state.get("attempts") or 0)
            if (
                previous_attempts
                and month_state.get("page_etag") == page_result.get("etag")
                and month_state.get("pdf_etag") == pdf_result.get("etag")
            ):
                diagnosis = "publication_not_updated_yet"
            road_log("road_record_skip_reason", diagnosis)
            attempts = previous_attempts + 1
            month_state.update(
                {
                    "attempts": attempts,
                    "last_attempt_at": current.isoformat(timespec="seconds"),
                    "last_status": diagnosis,
                    "page_etag": page_result.get("etag", ""),
                    "pdf_etag": pdf_result.get("etag", ""),
                }
            )
            state[state_key] = month_state
            save_state(state)
            debug_path = save_debug_snapshot(
                {
                    "started_at": current.isoformat(timespec="seconds"),
                    "month_key": month_key,
                    "page": {key: value for key, value in page_result.items() if key != "body"},
                    "page_info": page_info,
                    "pdf": pdf_result,
                    "raw_records": raw_count,
                    "parsed_records": parsed_count,
                    "future_records": len(current_and_future),
                    "diagnosis": diagnosis,
                    "parse_error": parse_error,
                    "attempt": attempts,
                },
                current,
            )
            road_log("road_scraper_csv_records", "skipped existing_csv_preserved")
            road_log("road_sheet_sync_records", "skipped existing_sheet_preserved")
            return {
                "status": "retry_scheduled" if attempts == 1 else diagnosis,
                "diagnosis": diagnosis,
                "month_key": month_key,
                "attempt": attempts,
                "raw_records": raw_count,
                "parsed_records": parsed_count,
                "future_records": len(current_and_future),
                "csv_preserved": True,
                "sheet_preserved": True,
                "debug_path": str(debug_path),
            }

        csv_rows, health_messages = regenerate_road_csv(month_key)
        road_log("road_scraper_csv_records", csv_rows or csv_count())
        sync_result = run_sheet_sync(current.date())
        sync_ok = bool(sync_result["ok"])
        sync_output = str(sync_result["output"])
        synced_records = int(sync_result["records"])
        message = build_success_message(target_month, current, csv_rows or csv_count(), sync_ok, sync_output)
        notify_ok, notify_status = post_admin_discord(message)
        mark_success(
            state,
            state_key,
            now=current,
            csv_rows=csv_rows or csv_count(),
            sync_result=sync_result,
        )
        print(f"road_monthly_pdf: downloaded {month_key}", flush=True)
        print(f"road_monthly_pdf: admin_notify={notify_status}", flush=True)
        for health_message in health_messages:
            logging.info("road_monthly_pdf_health: %s", health_message)
        return {
            "status": "downloaded" if sync_ok else "downloaded_sheet_sync_pending",
            "month_key": month_key,
            "csv_rows": csv_rows,
            "raw_records": raw_count,
            "parsed_records": parsed_count,
            "future_records": len(current_and_future),
            "sheet_sync_ok": sync_ok,
            "sheet_sync_pending": not sync_ok,
            "sheet_sync_reason": sync_result["reason"],
            "sheet_sync_records": synced_records,
            "admin_notified": notify_ok,
            "admin_notify_status": notify_status,
        }

    status_code = int(pdf_result.get("status_code") or 0)
    detail = str(pdf_result.get("error") or "")
    status = f"HTTP{status_code}" if status_code else detail
    diagnosis = (
        "publication_not_updated_yet"
        if page_info.get("previous_month_only")
        else "fetch_or_parse_error"
    )
    attempts = int(month_state.get("attempts") or 0) + 1
    month_state.update(
        {
            "attempts": attempts,
            "last_attempt_at": current.isoformat(timespec="seconds"),
            "last_status": diagnosis,
        }
    )
    state[state_key] = month_state
    save_state(state)
    road_log("road_record_skip_reason", diagnosis)
    road_log("road_scraper_raw_records", 0)
    road_log("road_scraper_parsed_records", 0)
    road_log("road_scraper_future_records", 0)
    road_log("road_scraper_csv_records", "skipped existing_csv_preserved")
    road_log("road_sheet_sync_records", "skipped existing_sheet_preserved")
    debug_path = save_debug_snapshot(
        {
            "started_at": current.isoformat(timespec="seconds"),
            "month_key": month_key,
            "page": {key: value for key, value in page_result.items() if key != "body"},
            "page_info": page_info,
            "pdf": pdf_result,
            "raw_records": 0,
            "parsed_records": 0,
            "future_records": 0,
            "diagnosis": diagnosis,
            "attempt": attempts,
        },
        current,
    )
    logging.info("road_monthly_pdf: not_available month=%s status=%s", month_key, status)
    if attempts <= 1:
        print(f"road_monthly_pdf: retry scheduled {month_key} {status}", flush=True)
        return {
            "status": "retry_scheduled",
            "diagnosis": diagnosis,
            "month_key": month_key,
            "download_status": status,
            "attempt": attempts,
            "csv_preserved": True,
            "sheet_preserved": True,
            "debug_path": str(debug_path),
        }

    if month_state.get("failure_notified") and not force:
        print(f"road_monthly_pdf: skipped failure already notified {month_key}", flush=True)
        return {"status": "skipped", "reason": "failure_already_notified", "month_key": month_key}

    notify_ok, notify_status = post_admin_discord(build_failure_message(target_month, current, status))
    if notify_ok:
        mark_failure_notified(state, state_key, now=current, status=status)
    print(f"road_monthly_pdf: missing after 18:00 {month_key}", flush=True)
    print(f"road_monthly_pdf: admin_notify={notify_status}", flush=True)
    return {
        "status": diagnosis,
        "diagnosis": diagnosis,
        "month_key": month_key,
        "download_status": status,
        "admin_notified": notify_ok,
        "admin_notify_status": notify_status,
        "debug_path": str(debug_path),
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
