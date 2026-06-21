#!/usr/bin/env python3
"""外部調査用の軽量Web検索。"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DUCKDUCKGO_URL = "https://lite.duckduckgo.com/lite/"
USER_AGENT = "Mozilla/5.0 (compatible; GemmaKachoResearch/1.0)"
KATSUYA_OFFICIAL_DOMAINS = ("katsuya.jp", "arclandservice.co.jp")


def fetch_search_page(query: str) -> str:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"{DUCKDUCKGO_URL}?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    value = re.sub(r"<.*?>", "", value, flags=re.S)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_url(url: str) -> str:
    url = html.unescape(url)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    return url


def parse_results(page: str, limit: int = 5) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    pattern = re.compile(
        r'<a[^>]+href="([^"]+)"[^>]+class=[\'"][^\'"]*result-link[^\'"]*[\'"][^>]*>(.*?)</a>',
        re.S,
    )
    for match in pattern.finditer(page):
        url = clean_url(match.group(1))
        title = clean_text(match.group(2))
        if not title or not url:
            continue
        results.append({"title": title, "url": url})
        if len(results) >= limit:
            break
    return results


def result_domain(result: dict[str, str]) -> str:
    return urllib.parse.urlparse(result.get("url", "")).netloc.lower()


def is_official_candidate(result: dict[str, str], official_domains: tuple[str, ...]) -> bool:
    domain = result_domain(result)
    return any(domain == official or domain.endswith(f".{official}") for official in official_domains)


def official_domains_for(query: str, category: str = "") -> tuple[str, ...]:
    if category == "food" and "かつや" in query:
        return KATSUYA_OFFICIAL_DOMAINS
    if "かつや" in query:
        return KATSUYA_OFFICIAL_DOMAINS
    return ()


def prioritize_official_results(
    results: list[dict[str, str]],
    official_domains: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    for result in results:
        official_candidate = is_official_candidate(result, official_domains) if official_domains else False
        item = dict(result)
        item["official"] = official_candidate
        enriched.append(item)

    prioritized = sorted(enriched, key=lambda item: not item["official"])
    official_candidates = [item for item in prioritized if item["official"]]
    return prioritized, official_candidates


def search_web(query: str, limit: int = 5, category: str = "") -> dict[str, Any]:
    try:
        page = fetch_search_page(query)
        raw_results = parse_results(page, limit=limit)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "query": query,
            "category": category,
            "results": [],
            "official_candidates": [],
            "official_status": "公式情報は未確認。検索候補です",
            "error": str(exc),
        }

    official_domains = official_domains_for(query, category)
    results, official_candidates = prioritize_official_results(raw_results, official_domains)
    return {
        "query": query,
        "category": category,
        "official_candidates": official_candidates,
        "official_status": "公式候補あり" if official_candidates else "公式情報は未確認。検索候補です",
        "results": results,
        "error": "",
    }


def main() -> int:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        query = sys.stdin.read().strip()
    if not query:
        print(json.dumps({"query": "", "results": [], "error": "empty query"}, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps(search_web(query), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
