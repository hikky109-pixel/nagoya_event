#!/usr/bin/env python3
"""Fetch Aonami Line WordPress rail information including detail pages."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

try:
    from log_utils import log
except ModuleNotFoundError:
    from tools.ai.log_utils import log


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://www.aonamiline.co.jp"
PAGE_URL = f"{BASE_URL}/railinfo"
FEED_URL = f"{PAGE_URL}/feed/"
STATE_PATH = ROOT / "data" / "ai" / "aonami_status_state.json"
DEBUG_PATH = ROOT / "data" / "debug" / "railway" / "aonami_latest.json"
NORMAL_MARKERS = ("平常通り運行", "平常に運行", "平常運転")
CRITICAL_MARKERS = ("強風", "台風", "運転見合わせ", "運転を見合わせ", "運休")
DELAY_MARKERS = ("遅れ", "遅延")
CAUTION_MARKERS = ("恐れがあります", "可能性があります", "見込まれます")
DETAIL_URL_PATTERN = re.compile(r"^https://www\.aonamiline\.co\.jp/railinfo/\d+/?$")
DEMAND_REASON = "金城ふ頭方面は代替交通が少ない"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _fetch(url: str) -> tuple[bytes, str, int]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read(), response.geturl(), response.status


def _detail_content(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("h3.top0") or soup.select_one("article h1")
    body_nodes = soup.select("p.read")
    if not body_nodes:
        article = soup.select_one("article") or soup.select_one("main")
        body_nodes = article.select("p") if article else []
    title = _clean_text(title_node.get_text(" ", strip=True) if title_node else "")
    body = "\n".join(
        text
        for node in body_nodes
        if (text := _clean_text(node.get_text(" ", strip=True)))
    )
    return title, body


def _classification(title: str, body: str) -> tuple[bool, str, str]:
    text = f"{title} {body}"
    normal = any(marker in title for marker in NORMAL_MARKERS)
    caution_only = normal and any(marker in text for marker in CAUTION_MARKERS)
    if normal:
        return True, "info", "normal_caution" if caution_only else "normal"
    if any(marker in text for marker in CRITICAL_MARKERS):
        return False, "critical", DEMAND_REASON
    if any(marker in text for marker in DELAY_MARKERS):
        return False, "info", "delay"
    return False, "info", "notice"


def parse_aonami_feed(
    xml_data: bytes,
    detail_fetcher: Any = _fetch,
) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_data)
    records: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        feed_title = _clean_text(item.findtext("title", ""))
        feed_body = _clean_text(item.findtext("description", ""))
        detail_url = urljoin(PAGE_URL, _clean_text(item.findtext("link", "")))
        published_raw = _clean_text(item.findtext("pubDate", ""))
        published_at = ""
        if published_raw:
            try:
                published_at = parsedate_to_datetime(published_raw).isoformat()
            except (TypeError, ValueError):
                published_at = published_raw

        detail_title = feed_title
        detail_body = feed_body
        detail_status_code = 0
        if DETAIL_URL_PATTERN.match(detail_url):
            log(f"aonami_detail_url_found: {detail_url}")
            try:
                raw_detail, final_url, detail_status_code = detail_fetcher(detail_url)
                detail_url = final_url
                parsed_title, parsed_body = _detail_content(
                    raw_detail.decode("utf-8", errors="replace")
                )
                detail_title = parsed_title or feed_title
                detail_body = parsed_body or feed_body
            except Exception as exc:
                log(
                    "aonami_detail_fetch_error: "
                    f"url={detail_url} error={type(exc).__name__}"
                )

        is_normal, level, reason = _classification(detail_title, detail_body)
        body_hash = hashlib.sha256(detail_body.encode("utf-8")).hexdigest()
        message = detail_title
        if detail_body and detail_body not in detail_title:
            message = f"{detail_title} {detail_body}".strip()
        records.append(
            {
                "title": feed_title,
                "body": feed_body,
                "published_at": published_at,
                "detail_url": detail_url,
                "detail_title": detail_title,
                "detail_body": detail_body,
                "detail_body_hash": body_hash,
                "detail_status_code": detail_status_code,
                "message": message,
                "is_normal": is_normal,
                "level": level,
                "severity_reason": reason,
            }
        )
    return records


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_aonami_status_snapshot(
    *,
    abnormal_only: bool = False,
    state_path: Path = STATE_PATH,
    debug_path: Path = DEBUG_PATH,
) -> tuple[list[str], dict[str, str], datetime | None, dict[str, str]]:
    xml_data, final_url, status_code = _fetch(FEED_URL)
    records = parse_aonami_feed(xml_data)
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    snapshot = {
        "source_url": FEED_URL,
        "final_url": final_url,
        "status_code": status_code,
        "fetched_at": fetched_at,
        "records": records,
    }
    _write_json(state_path, snapshot)
    _write_json(debug_path, snapshot)
    for record in records:
        log(
            "aonami_detail_saved: "
            f"url={record['detail_url']} hash={record['detail_body_hash'][:12]}"
        )
        if record["level"] == "critical":
            log(
                "aonami_severity_reason: critical "
                f"reason={record['severity_reason']}"
            )

    selected = [
        record for record in records if not abnormal_only or not record["is_normal"]
    ]
    messages = [str(record["message"]) for record in selected if record["message"]]
    source_urls = {
        str(record["message"]): str(record["detail_url"])
        for record in selected
        if record["message"] and record["detail_url"]
    }
    levels = {
        str(record["message"]): str(record["level"])
        for record in selected
        if record["message"] and record["level"]
    }
    updated_at = None
    published_values = [
        str(record["published_at"]) for record in selected if record["published_at"]
    ]
    if published_values:
        try:
            updated_at = datetime.fromisoformat(max(published_values))
        except ValueError:
            pass
    return messages, source_urls, updated_at, levels


def get_aonami_status(abnormal_only: bool = False) -> list[str]:
    messages, _source_urls, _updated_at, _levels = get_aonami_status_snapshot(
        abnormal_only=abnormal_only
    )
    return messages


if __name__ == "__main__":
    print(get_aonami_status())
