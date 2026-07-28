from utils import is_wanted_venue
from bs4 import BeautifulSoup
from datetime import datetime
import json
from pathlib import Path
import re

from tools.common.scraper_health import (
    build_admin_warning_message,
    check_selector_count,
    check_structure_hash,
    has_major_warning,
)

URL = "https://www.kyodotokai.co.jp/events"
ROOT = Path(__file__).resolve().parents[1]
DEBUG_DIR = ROOT / "data" / "debug" / "scrapers" / "kyodo_tokai"
EVENT_SELECTOR = "div.eventlistbox dl"
MAX_FETCH_ATTEMPTS = 2

WANTED_VENUES = [
    "IGアリーナ",
    "日本ガイシホール",
    "愛知県芸術劇場",
    "Niterra日本特殊陶業市民会館",
    "岡谷鋼機名古屋公会堂",
    "Zepp Nagoya",
    "DIAMOND HALL",
    "NAGOYA JAMMIN",
    "NAGOYA JAMMIN’",
    "バンテリンドーム",
]

def _kyodo_health_messages(soup):
    messages = []
    messages.extend(
        check_selector_count(
            "kyodo_tokai",
            soup,
            EVENT_SELECTOR,
            "events",
            min_count=1,
            drop_ratio=0.8,
        )
    )
    fragment_nodes = soup.select("div.eventlistbox")
    messages.extend(
        check_structure_hash(
            "kyodo_tokai",
            "\n".join(str(node) for node in fragment_nodes),
            "events",
        )
    )
    if has_major_warning(messages, "kyodo_tokai"):
        messages.append(
            build_admin_warning_message(
                "キョードー東海",
                {"イベント": len(soup.select(EVENT_SELECTOR))},
            )
        )
    return messages


def _save_fetch_debug(html, diagnostics):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    html_path = DEBUG_DIR / f"kyodo_tokai_{timestamp}.html"
    json_path = DEBUG_DIR / f"kyodo_tokai_{timestamp}.json"
    html_path.write_text(html or "", encoding="utf-8")
    payload = dict(diagnostics)
    payload["saved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    payload["html_path"] = str(html_path)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return html_path, json_path


def _fetch_events_page(page):
    attempts = []
    last_html = ""
    last_soup = BeautifulSoup("", "html.parser")

    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        response = None
        error = ""
        try:
            response = page.goto(URL, wait_until="domcontentloaded", timeout=15000)
            last_html = page.content()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            try:
                last_html = page.content()
            except Exception:
                last_html = ""

        last_soup = BeautifulSoup(last_html, "html.parser")
        selector_count = len(last_soup.select(EVENT_SELECTOR))
        status = getattr(response, "status", None) if response is not None else None
        attempts.append(
            {
                "attempt": attempt,
                "status_code": status,
                "final_url": str(getattr(page, "url", "") or ""),
                "response_length": len(last_html.encode("utf-8")),
                "selector": EVENT_SELECTOR,
                "selector_count": selector_count,
                "error": error,
            }
        )
        if status == 200 and selector_count > 0:
            return last_soup, attempts, None

    diagnostics = {
        "source_url": URL,
        "attempts": attempts,
        "final": attempts[-1],
    }
    html_path, json_path = _save_fetch_debug(last_html, diagnostics)
    return last_soup, attempts, (html_path, json_path)


def scrape_kyodo_tokai_with_health(page, target_date):
    events = []

    target_str = target_date.strftime("%Y年%m月%d日")

    soup, attempts, debug_paths = _fetch_events_page(page)
    health_messages = _kyodo_health_messages(soup)
    if len(attempts) > 1:
        health_messages.insert(
            0,
            "scraper_health_info: kyodo_tokai fetch retried "
            f"first_status={attempts[0]['status_code']} "
            f"first_length={attempts[0]['response_length']} "
            f"first_selector_count={attempts[0]['selector_count']} "
            f"final_status={attempts[-1]['status_code']} "
            f"final_length={attempts[-1]['response_length']} "
            f"final_selector_count={attempts[-1]['selector_count']}",
        )
    if debug_paths is not None:
        html_path, json_path = debug_paths
        final = attempts[-1]
        health_messages.append(
            "scraper_health_warning: kyodo_tokai fetch diagnostics "
            f"status={final['status_code']} final_url={final['final_url']} "
            f"response_length={final['response_length']} "
            f"selector_count={final['selector_count']} "
            f"saved_html={html_path} saved_json={json_path}"
        )

    for dl in soup.select(EVENT_SELECTOR):
        text = " ".join(dl.get_text(" ", strip=True).split())

        if target_str not in text:
            continue

        title_tag = dl.select_one("a.alink")
        title = title_tag.get_text(" ", strip=True) if title_tag else ""

        dd = dl.select_one("dd")
        venue = ""
        if dd:
            dd_text = dd.get_text(" ", strip=True)
            m_venue = re.search(r"【会場名】\s*(.*?)\s*【料金】", dd_text)
            venue = m_venue.group(1).strip() if m_venue else dd_text

        if not title or not venue:
            continue

        if not any(v in venue for v in WANTED_VENUES):
            print(f"キョードー除外: {venue} | {title}")
            continue

        time_text = "未定"

        m_time = re.search(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})", text)
        if m_time:
            time_text = m_time.group(2)

        events.append({
            "time": time_text,
            "venue": venue,
            "title": title,
            "source": "kyodo_tokai",
        })

    return events, health_messages


def scrape_kyodo_tokai(page, target_date):
    events, _messages = scrape_kyodo_tokai_with_health(page, target_date)
    return events
