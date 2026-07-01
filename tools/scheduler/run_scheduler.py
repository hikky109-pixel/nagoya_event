#!/usr/bin/env python3
"""常駐schedulerで定時ジョブを実行する。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


JST = ZoneInfo("Asia/Tokyo")
LOG_DIR = ROOT / "logs"
OPENMETEO_FORECAST_STATE_PATH = ROOT / "data" / "weather" / "openmeteo_forecast_state.json"
OPENMETEO_FORECAST_SLOTS = {0, 6, 12, 18}
TICK_INTERVAL_SECONDS = 300


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_DIR / "scheduler.log",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )


def log(message: str) -> None:
    print(message, flush=True)
    logging.info(message)


def load_json_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def openmeteo_forecast_slot_key(now: datetime) -> str:
    return f"{now:%Y-%m-%d}-{now.hour:02d}"


def run_openmeteo_forecast(now: datetime) -> None:
    if now.hour not in OPENMETEO_FORECAST_SLOTS:
        log("openmeteo_forecast: skipped outside slot")
        return

    slot_key = openmeteo_forecast_slot_key(now)
    state = load_json_state(OPENMETEO_FORECAST_STATE_PATH)
    if state.get(slot_key):
        log("openmeteo_forecast: skipped already posted")
        return

    try:
        from tools.weather.post_openmeteo_forecast import run as post_openmeteo_forecast

        result = post_openmeteo_forecast(force=True)
    except Exception as exc:
        message = f"openmeteo_forecast_error: {exc}"
        print(message, flush=True)
        logging.exception("openmeteo_forecast_error: %s", exc)
        return

    if result.get("sent"):
        state = load_json_state(OPENMETEO_FORECAST_STATE_PATH)
        state[slot_key] = {
            "posted_at": datetime.now(JST).isoformat(timespec="seconds"),
            "hash": result.get("hash", ""),
        }
        state["last_slot_key"] = slot_key
        save_json_state(OPENMETEO_FORECAST_STATE_PATH, state)
        log("openmeteo_forecast: posted")
        return

    reason = result.get("reason") or result.get("status_code") or "not_sent"
    print(f"openmeteo_forecast_error: {reason}", flush=True)
    logging.warning("openmeteo_forecast_error: %s", result)


SchedulerJob = Callable[[datetime], None]


def scheduler_tick(jobs: list[SchedulerJob] | None = None) -> None:
    now = datetime.now(JST)
    log("scheduler_tick")
    for job in jobs or [run_openmeteo_forecast]:
        try:
            job(now)
        except Exception as exc:
            print(f"scheduler_job_error: {exc}", flush=True)
            logging.exception("scheduler_job_error: %s", exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="nagoya_event scheduler loop")
    parser.add_argument("--once", action="store_true", help="1 tickだけ実行して終了する。")
    parser.add_argument("--interval", type=int, default=TICK_INTERVAL_SECONDS, help="tick間隔秒。")
    return parser.parse_args()


def main() -> int:
    setup_logging()
    args = parse_args()

    while True:
        scheduler_tick()
        if args.once:
            return 0
        time.sleep(max(args.interval, 1))


if __name__ == "__main__":
    raise SystemExit(main())
