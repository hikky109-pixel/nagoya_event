#!/usr/bin/env python3
"""Fetch Kintetsu status and save raw detail records for later investigation."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

try:
    from log_utils import log
except ModuleNotFoundError:
    from tools.ai.log_utils import log


ROOT = Path(__file__).resolve().parents[2]
URL = "https://www.kintetsu.jp/unkou/unkou.html"
DEBUG_DIR = ROOT / "data" / "debug" / "railway"
LATEST_DEBUG_PATH = DEBUG_DIR / "kintetsu_latest.json"
NORMAL_MESSAGE = "現在は１５分以上の列車の遅れはございません。"
TARGET_LINE = "名古屋線"
JST = ZoneInfo("Asia/Tokyo")
LINE_KEYWORDS = (
    "名古屋線",
    "大阪線",
    "奈良線",
    "京都線",
    "橿原線",
    "難波線",
    "信貴線",
    "生駒線",
    "けいはんな線",
    "南大阪線",
    "吉野線",
)
LINE_PATTERN = "|".join(re.escape(line) for line in LINE_KEYWORDS)
SECTION_PATTERN = re.compile(
    rf"(?:^|[\s、。：])(?:(?P<line>{LINE_PATTERN})[　 ]*)?"
    r"(?P<from>[一-龠々ヶぁ-んァ-ヶーA-Za-z0-9]{1,20})"
    r"[～〜－-]"
    r"(?P<to>[一-龠々ヶぁ-んァ-ヶーA-Za-z0-9]{1,20}?)"
    r"(?:間(?=で|の|を|に|$|\s)|(?=で|の|を|に|$|\s))"
)


def _normalize_text(text: Any) -> str:
    value = re.sub(r"<[^>]+>", "", str(text or ""))
    value = value.replace("&nbsp;", " ")
    return " ".join(value.split())


def _decode_html(raw: bytes) -> str:
    for encoding in ("cp932", "shift_jis", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def _fetch(url: str) -> tuple[bytes, str, int]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read(), response.geturl(), response.status


def extract_kintetsu_detail_urls(html: str, base_url: str = URL) -> list[str]:
    candidates = re.findall(
        r"""(?:href\s*=\s*|window\.open\(\s*)["']([^"']*files/\d+\.html(?:#[^"']*)?)["']""",
        html,
        flags=re.IGNORECASE,
    )
    urls: list[str] = []
    for candidate in candidates:
        detail_url, _fragment = urldefrag(urljoin(base_url, candidate))
        if not re.search(r"/unkou/files/\d+\.html$", detail_url):
            continue
        detail_url = f"{detail_url}#tran"
        if detail_url not in urls:
            urls.append(detail_url)
    return urls


def _detail_body(soup: BeautifulSoup) -> str:
    anchor = soup.select_one("#tran")
    if anchor is None:
        return _normalize_text(soup.get_text(" ", strip=True))
    container = anchor.find_parent("td") or anchor
    return _normalize_text(container.get_text(" ", strip=True))


def _detail_title(soup: BeautifulSoup, body_text: str) -> str:
    for node in soup.select('font[size="+2"], font[size="2"]'):
        title = _normalize_text(node.get_text(" ", strip=True))
        if title:
            return title.strip("【】 ")
    match = re.search(r"【([^】]+)】", body_text)
    return _normalize_text(match.group(1)) if match else ""


def _extract_cause(text: str) -> str:
    patterns = (
        r"で発生した([^。、]+?)(?:の影響)?(?:のため|により)",
        r"で発生した([^。、]+?)による",
        r"は、?[^。、]{0,30}?で([^。、]+?)(?:のため|により)",
        r"は、?([^。、]{1,30}?)(?:のため|により)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _normalize_text(match.group(1))
    return ""


def _extract_main_line(title: str, body_text: str) -> str:
    for line in LINE_KEYWORDS:
        if line in title:
            return line
    for line in LINE_KEYWORDS:
        if line in body_text:
            return line
    return ""


def _extract_affected_sections(body_text: str) -> list[str]:
    operation_text = re.split(r"振替輸送[：:]", body_text, maxsplit=1)[0]
    sections: list[str] = []
    for match in SECTION_PATTERN.finditer(operation_text):
        line = _normalize_text(match.group("line"))
        station_from = _normalize_text(match.group("from"))
        station_to = _normalize_text(match.group("to"))
        section = f"{station_from}～{station_to}"
        if line:
            section = f"{line} {section}"
        if section and section not in sections:
            sections.append(section)
    return sections


def _extract_transfer_info(body_text: str) -> str:
    marker = re.search(r"振替輸送[：:]", body_text)
    if not marker:
        return ""
    return _normalize_text(body_text[marker.start():])


def parse_kintetsu_detail(html: str, detail_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    body_text = _detail_body(soup)
    title = _detail_title(soup, body_text)
    updated_match = re.search(
        r"\d{1,2}月\d{1,2}日\s*\d{1,2}時\d{1,2}分\s*現在",
        body_text,
    )
    affected_lines = [
        line
        for line in LINE_KEYWORDS
        if line in f"{title} {body_text}"
    ]
    return {
        "title": title,
        "updated_at_text": _normalize_text(updated_match.group(0)) if updated_match else "",
        "cause": _extract_cause(body_text),
        "main_line": _extract_main_line(title, body_text),
        "affected_lines": affected_lines,
        "affected_sections": _extract_affected_sections(body_text),
        "transfer_info": _extract_transfer_info(body_text),
        "detail_url": detail_url,
        "body_text": body_text,
        "content_hash": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
    }


def _history_debug_path(debug_dir: Path, now: datetime) -> Path:
    stem = f"kintetsu_{now.astimezone(JST):%Y%m%d_%H%M%S}"
    path = debug_dir / f"{stem}.json"
    suffix = 1
    while path.exists():
        path = debug_dir / f"{stem}_{suffix:02d}.json"
        suffix += 1
    return path


def save_kintetsu_debug(
    snapshot: dict[str, Any],
    *,
    debug_dir: Path = DEBUG_DIR,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    saved_at = now or datetime.now(JST)
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=JST)
    snapshot = dict(snapshot)
    snapshot["saved_at"] = saved_at.astimezone(JST).isoformat(timespec="seconds")
    debug_dir.mkdir(parents=True, exist_ok=True)
    latest_path = debug_dir / "kintetsu_latest.json"
    history_path = _history_debug_path(debug_dir, saved_at)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    latest_path.write_text(payload, encoding="utf-8")
    history_path.write_text(payload, encoding="utf-8")
    log(f"kintetsu_debug_saved: latest={latest_path} history={history_path}")
    return latest_path, history_path


def collect_kintetsu_debug(
    top_html: str,
    *,
    top_final_url: str = URL,
    top_status_code: int = 200,
    detail_fetcher: Any = _fetch,
    debug_dir: Path = DEBUG_DIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    detail_urls = extract_kintetsu_detail_urls(top_html, top_final_url)
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for detail_url in detail_urls:
        log(f"kintetsu_detail_url_found: {detail_url}")
        fetch_url, _fragment = urldefrag(detail_url)
        try:
            raw, final_url, status_code = detail_fetcher(fetch_url)
            record = parse_kintetsu_detail(
                _decode_html(raw),
                f"{urldefrag(final_url)[0]}#tran",
            )
            record["status_code"] = status_code
            records.append(record)
            log(
                "kintetsu_affected_lines: "
                f"url={record['detail_url']} lines={','.join(record['affected_lines'])}"
            )
        except Exception as exc:
            errors.append(
                {
                    "detail_url": detail_url,
                    "error": type(exc).__name__,
                }
            )
    snapshot = {
        "source_url": URL,
        "final_url": top_final_url,
        "status_code": top_status_code,
        "detail_urls": detail_urls,
        "records": records,
        "errors": errors,
    }
    save_kintetsu_debug(snapshot, debug_dir=debug_dir, now=now)
    return snapshot


def get_kintetsu_status(abnormal_only: bool = False, nagoya_line_only: bool = False) -> list[str]:
    raw, final_url, status_code = _fetch(URL)
    html = _decode_html(raw)
    try:
        collect_kintetsu_debug(
            html,
            top_final_url=final_url,
            top_status_code=status_code,
        )
    except Exception as exc:
        log(f"kintetsu_debug_saved: failed error={type(exc).__name__}")

    messages = []
    for match in re.finditer(r'<font\s+size="\+1"[^>]*>(.*?)</font>', html, re.S | re.I):
        text = _normalize_text(match.group(1))
        if text:
            messages.append(text)

    if not messages:
        fallback = _normalize_text(html)
        if NORMAL_MESSAGE in fallback:
            messages = [NORMAL_MESSAGE]

    if abnormal_only:
        messages = [message for message in messages if message != NORMAL_MESSAGE]

    if nagoya_line_only:
        messages = [message for message in messages if TARGET_LINE in message]

    return messages


if __name__ == "__main__":
    print(get_kintetsu_status())
