#!/usr/bin/env python3
"""Create a one-off, protected Aichi-Nagoya 2026 pre-event baseline."""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


SNAPSHOT_DATE = "2026-08-10"
KYUOGI_URL = "https://lp-ag.tickets-aichi-nagoya2026.org/wp-content/themes/asia/assets/js/kyougi.json"
VENUE_URL = "https://lp-ag.tickets-aichi-nagoya2026.org/wp-content/themes/asia/assets/js/venue.json"
SESSIONS_URL = "https://generalsale.tickets-aichi-nagoya2026.org/getFilteredProductsJSON.th"
EVENT_CATEGORY_FATHER = 3
ROWS_PER_PAGE = 25
CEREMONY_EVENT_TYPES = {
    "開会式": "opening_ceremony",
    "閉会式": "closing_ceremony",
}

BASELINE_FIELDS = [
    "snapshot_date", "event_type", "idProduct", "idPerformance", "eventCategory", "sessionCode",
    "idVenue", "date", "time", "end_time", "venue", "event_name",
    "event_category_name", "session_name", "session_info", "availability_status",
    "selling_status", "is_sellable", "source",
]

CANDIDATE_FIELDS = BASELINE_FIELDS + [
    "venue_match", "venue_master_name", "venue_pref", "venue_address",
    "venue_comp", "venue_events", "selection_area", "db_display_name",
    "selection_grade", "demand_point", "candidate_status",
]


def fetch_json(url: str) -> tuple[bytes, dict[str, Any]]:
    request = Request(url, headers={"User-Agent": "nagoya-event-baseline/1.0"})
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        raw = response.read()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {url}")
    return raw, value


def extract_allowed_categories(kyougi: dict[str, Any]) -> set[int]:
    categories: set[int] = set()
    for item in kyougi.get("data", []):
        values = parse_qs(urlparse(str(item.get("url", ""))).query).get("eventCategory", [])
        if values and values[0].isdigit():
            categories.add(int(values[0]))
    return categories


def fetch_session_pages() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pages: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    page_number = 1
    expected_total: int | None = None
    while True:
        url = (
            f"{SESSIONS_URL}?nohistory=true&eventCategoryFather={EVENT_CATEGORY_FATHER}"
            f"&currentPage={page_number}&rowsNumber={ROWS_PER_PAGE}"
        )
        _, page = fetch_json(url)
        if page.get("successfull") is not True or not isinstance(page.get("products"), list):
            raise ValueError(f"invalid session response on page {page_number}")
        total = page.get("totalRecords")
        if not isinstance(total, int) or total <= 1:
            raise ValueError(f"unsafe session totalRecords={total!r}")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError(f"totalRecords changed while paging: {expected_total} -> {total}")
        pages.append(page)
        products.extend(page["products"])
        if not page.get("hasMoreRecords"):
            break
        if not page["products"] or page_number > 1000:
            raise ValueError("session pagination did not make progress")
        page_number += 1
    if len(products) != expected_total:
        raise ValueError(f"session count mismatch: expected={expected_total} actual={len(products)}")
    return pages, products


def parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing datetime")
    cleaned = value.replace("\u202f", " ").replace("\xa0", " ")
    return datetime.strptime(cleaned, "%b %d, %Y, %I:%M:%S %p")


def normalize_venue_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = normalized.translate(str.maketrans({"[": "(", "]": ")", "［": "(", "］": ")"}))
    return re.sub(r"\s+", "", normalized)


def build_venue_index(venue_master: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    index: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for venue in venue_master.get("data", []):
        key = normalize_venue_name(str(venue.get("name", "")))
        if not key:
            continue
        if key in index:
            ambiguous.add(key)
        else:
            index[key] = venue
    for key in ambiguous:
        index.pop(key, None)
    return index, ambiguous


def classify_event_type(product: dict[str, Any], competition_categories: set[int]) -> str | None:
    if product.get("idEventCategory") in competition_categories:
        return "competition"
    return CEREMONY_EVENT_TYPES.get(str(product.get("nmEventCategory") or "").strip())


def build_rows(
    products: list[dict[str, Any]], allowed: set[int], venue_master: dict[str, Any],
    selection_rows: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    venue_index, ambiguous = build_venue_index(venue_master)
    selection_index = {
        normalize_venue_name(row.get("正式名称（大会資料）", "")): row
        for row in (selection_rows or [])
        if row.get("正式名称（大会資料）") and row.get("採用") in {"◎", "○"}
    }
    baseline: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    match_counts = {"venue_match_success": 0, "venue_match_normalized": 0, "venue_match_unresolved": 0}
    source = f"{SESSIONS_URL}?eventCategoryFather={EVENT_CATEGORY_FATHER}"
    for product in products:
        event_type = classify_event_type(product, allowed)
        if event_type is None:
            continue
        start = parse_datetime(product.get("dhStart"))
        end = parse_datetime(product.get("dhEnd"))
        venue_name = str(product.get("nmVenue") or "")
        key = normalize_venue_name(venue_name)
        matched = venue_index.get(key) if key not in ambiguous else None
        selected = selection_index.get(key)
        if matched and matched.get("name") == venue_name:
            match_type = "exact"
            match_counts["venue_match_success"] += 1
        elif matched:
            match_type = "normalized"
            match_counts["venue_match_normalized"] += 1
        else:
            match_type = "unresolved"
            match_counts["venue_match_unresolved"] += 1
        row = {
            "snapshot_date": SNAPSHOT_DATE,
            "event_type": event_type,
            "idProduct": product.get("idProduct", ""),
            "idPerformance": product.get("idPerformance", ""),
            "eventCategory": product.get("idEventCategory", ""),
            "sessionCode": product.get("sessionCode", ""),
            "idVenue": product.get("idVenue", ""),
            "date": start.strftime("%Y-%m-%d"),
            "time": start.strftime("%H:%M:%S"),
            "end_time": end.strftime("%H:%M:%S"),
            "venue": venue_name,
            "event_name": product.get("nmEvent", ""),
            "event_category_name": product.get("nmEventCategory", ""),
            "session_name": product.get("nmProduct", ""),
            "session_info": product.get("nmInfo", ""),
            "availability_status": product.get("availabilityStatus", ""),
            "selling_status": product.get("cdSellingStatus", ""),
            "is_sellable": product.get("isSellable", ""),
            "source": source,
        }
        baseline.append(row)
        if selected:
            candidates.append({
                **row,
                "venue_match": match_type,
                "venue_master_name": matched.get("name", "") if matched else "",
                "venue_pref": matched.get("pref", "") if matched else "",
                "venue_address": matched.get("address", "") if matched else "",
                "venue_comp": matched.get("comp", "") if matched else "",
                "venue_events": matched.get("ev", "") if matched else "",
                "selection_area": selected.get("エリア", ""),
                "db_display_name": selected.get("DB表示名", ""),
                "selection_grade": selected.get("採用", ""),
                "demand_point": selected.get("需要ポイント", ""),
                "candidate_status": "selected_master_match",
            })
    baseline.sort(key=lambda row: (row["date"], row["time"], str(row["idPerformance"])))
    candidates.sort(key=lambda row: (row["date"], row["time"], str(row["idPerformance"])))
    return baseline, candidates, match_counts


def csv_bytes(rows: list[dict[str, Any]], fields: list[str]) -> bytes:
    import io
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def protected_write(path: Path, content: bytes, force: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == content:
            return "unchanged"
        if not force:
            raise FileExistsError(f"refusing to overwrite different snapshot: {path}")
    path.write_bytes(content)
    return "written"


def read_selection_master(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def create_baseline(
    output_root: Path, force: bool = False, selection_master: Path | None = None
) -> dict[str, Any]:
    retrieved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    kyougi_raw, kyougi = fetch_json(KYUOGI_URL)
    venue_raw, venue = fetch_json(VENUE_URL)
    allowed = extract_allowed_categories(kyougi)
    if not allowed:
        raise ValueError("kyougi.json contains no eventCategory allowlist")
    pages, products = fetch_session_pages()
    selection_rows = read_selection_master(selection_master)
    baseline, candidates, match_counts = build_rows(products, allowed, venue, selection_rows)
    if len(baseline) <= 1:
        raise ValueError(f"unsafe competition session count={len(baseline)}")

    raw_dir = output_root / "raw"
    baseline_dir = output_root / "baseline"
    sessions_document = {
        "retrieved_at": retrieved_at,
        "source_url": SESSIONS_URL,
        "request": {"eventCategoryFather": EVENT_CATEGORY_FATHER, "rowsNumber": ROWS_PER_PAGE},
        "total_records": len(products),
        "pages": pages,
    }
    files = {
        raw_dir / "kyougi.json": kyougi_raw,
        raw_dir / "venue.json": venue_raw,
        raw_dir / f"sessions_{SNAPSHOT_DATE.replace('-', '')}.json": (
            json.dumps(sessions_document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        ),
        baseline_dir / f"baseline_sessions_{SNAPSHOT_DATE.replace('-', '')}.csv": csv_bytes(baseline, BASELINE_FIELDS),
        baseline_dir / f"venue_candidates_{SNAPSHOT_DATE.replace('-', '')}.csv": csv_bytes(candidates, CANDIDATE_FIELDS),
    }
    statuses = {str(path): protected_write(path, content, force) for path, content in files.items()}
    report = {
        "snapshot_date": SNAPSHOT_DATE,
        "retrieved_at": retrieved_at,
        "raw_sessions": len(products),
        "allowed_event_categories": len(allowed),
        "adopted_event_categories": len({row["eventCategory"] for row in baseline}),
        "competition_sessions": sum(row["event_type"] == "competition" for row in baseline),
        "ceremony_sessions": sum(row["event_type"] != "competition" for row in baseline),
        "opening_ceremony_sessions": sum(row["event_type"] == "opening_ceremony" for row in baseline),
        "closing_ceremony_sessions": sum(row["event_type"] == "closing_ceremony" for row in baseline),
        "excluded_non_event_products": len(products) - len(baseline),
        "venue_master_records": len(venue.get("data", [])),
        "selected_venue_master_records": sum(row.get("採用") in {"◎", "○"} for row in selection_rows),
        "selected_candidate_sessions": len(candidates),
        **match_counts,
        "idProduct_duplicates": len(baseline) - len({row["idProduct"] for row in baseline}),
        "idPerformance_duplicates": len(baseline) - len({row["idPerformance"] for row in baseline}),
        "sessionCode_missing": sum(not row["sessionCode"] for row in baseline),
        "dhStart_missing": sum(not product.get("dhStart") for product in products if classify_event_type(product, allowed)),
        "dhEnd_missing": sum(not product.get("dhEnd") for product in products if classify_event_type(product, allowed)),
        "venue_missing": sum(not row["venue"] for row in baseline),
        "earliest": f"{baseline[0]['date']}T{baseline[0]['time']}",
        "latest": max(f"{row['date']}T{row['end_time']}" for row in baseline),
        "files": statuses,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("data/aichi_nagoya_2026"))
    parser.add_argument("--force", action="store_true", help="replace a different same-date snapshot")
    parser.add_argument(
        "--selection-master",
        type=Path,
        default=Path("data/aichi_nagoya_2026/baseline/venue_selection_master_20260810.csv"),
    )
    args = parser.parse_args()
    create_baseline(args.output_root, args.force, args.selection_master)


if __name__ == "__main__":
    main()
