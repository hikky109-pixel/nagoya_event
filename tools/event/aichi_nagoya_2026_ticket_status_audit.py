#!/usr/bin/env python3
"""Read-only audit of Asia Games Sheet ticket availability.

The command reuses the official ticket-session feed and the immutable 2026-08-10
candidate snapshot.  It has no Google Sheets write path.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.utils.google_sheet_events import ASIA_OPERATIONAL_COLUMNS
from tools.event.aichi_nagoya_2026_results import external_request_timeout
from tools.event.aichi_nagoya_2026_results_dry_run import (
    SHEET_HARD_TIMEOUT_SECONDS,
    load_asia_sheet_rows_read_only,
)
from tools.event.build_aichi_nagoya_2026_baseline import (
    fetch_session_pages,
    parse_datetime,
)
from tools.event.build_aichi_nagoya_2026_operational import (
    OPERATIONAL_FIELDS,
    operational_row_from_candidate,
)


UNCHANGED = "UNCHANGED"
STATUS_CHANGED = "STATUS_CHANGED"
MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
NOT_FOUND = "NOT_FOUND"
CLASSIFICATIONS = (UNCHANGED, STATUS_CHANGED, MULTIPLE_CANDIDATES, NOT_FOUND)
KNOWN_AVAILABILITY_STATUSES = {"BUY", "LIMITED", "SOLD_OUT"}
IDENTITY_FIELDS = tuple(OPERATIONAL_FIELDS[:-1])
DEFAULT_CANDIDATES_PATH = Path(
    "data/aichi_nagoya_2026/baseline/venue_candidates_20260810.csv"
)
DEFAULT_OVERALL_TIMEOUT_SECONDS = 120.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0
CSV_FIELDS = [
    "sheet_data_row",
    *OPERATIONAL_FIELDS,
    "official_availability_status",
    "classification",
    "candidate_count",
    "reason",
    "idPerformance",
    "idProduct",
    "sessionCode",
    "official_session_name",
    "official_date",
    "official_time",
    "official_end_time",
    "official_venue",
    "official_event_name",
    "official_session_info",
]


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _read_candidate_rows(path: Path) -> list[dict[str, str]]:
    required = {
        *IDENTITY_FIELDS,
        "availability_status",
        "idPerformance",
        "idProduct",
        "sessionCode",
        "db_display_name",
        "event_type",
    }
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"candidate baseline missing columns: {sorted(missing)}")
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError("candidate baseline contains zero rows")
    return rows


def _key(row: dict[str, Any], fields: Iterable[str]) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "").strip() for field in fields)


def _stable_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("idPerformance") or "").strip(),
        str(row.get("idProduct") or "").strip(),
        str(row.get("sessionCode") or "").strip(),
    )


def _is_business_row(row: dict[str, str]) -> bool:
    return not row.get("event_name", "").strip().startswith("【発火テスト】")


def build_baseline_indexes(
    candidate_rows: Iterable[dict[str, str]],
) -> list[tuple[tuple[str, ...], dict[tuple[str, ...], list[dict[str, str]]]]]:
    """Build conservative identity indexes, strongest first."""

    fields_by_strength = (
        IDENTITY_FIELDS,
        ("date", "time", "end_time", "venue", "event_name"),
        ("date", "time", "venue", "event_name"),
        ("date", "venue", "event_name"),
    )
    indexes: list[tuple[tuple[str, ...], dict[tuple[str, ...], list[dict[str, str]]]]] = []
    rows = list(candidate_rows)
    for fields in fields_by_strength:
        index: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
        for candidate in rows:
            projected = operational_row_from_candidate(candidate)
            index[_key(projected, fields)].append(candidate)
        indexes.append((fields, dict(index)))
    return indexes


def match_sheet_to_baseline(
    sheet_row: dict[str, str],
    indexes: list[
        tuple[tuple[str, ...], dict[tuple[str, ...], list[dict[str, str]]]]
    ],
) -> tuple[list[dict[str, str]], str]:
    """Return only a unique candidate, or all candidates at the last stage."""

    last_candidates: list[dict[str, str]] = []
    for fields, index in indexes:
        candidates = index.get(_key(sheet_row, fields), [])
        if len(candidates) == 1:
            return candidates, "baseline identity matched fields=" + ",".join(fields)
        if len(candidates) > 1:
            last_candidates = candidates
    if last_candidates:
        return last_candidates, (
            "multiple 2026-08-10 candidates remain for date/venue/event_name"
        )
    return [], "no 2026-08-10 selected candidate matched Sheet identity"


def build_current_index(
    products: Iterable[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for product in products:
        key = _stable_key(product)
        if all(key):
            index[key].append(product)
    return dict(index)


def project_current_product(product: dict[str, Any]) -> dict[str, str]:
    """Project current ticket metadata used by the follow-up safety audit."""

    start = parse_datetime(product.get("dhStart"))
    end = parse_datetime(product.get("dhEnd"))
    return {
        "date": start.strftime("%Y-%m-%d"),
        "time": start.strftime("%H:%M:%S"),
        "end_time": end.strftime("%H:%M:%S"),
        "venue": str(product.get("nmVenue") or "").strip(),
        "event_name": str(product.get("nmEvent") or "").strip(),
        "session_info": str(product.get("nmInfo") or "").strip(),
        "session_name": str(product.get("nmProduct") or "").strip(),
    }


def audit_sheet_rows(
    sheet_rows: Iterable[dict[str, str]],
    candidate_rows: Iterable[dict[str, str]],
    current_products: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Classify rows without modifying inputs or choosing ambiguous sessions."""

    baseline_indexes = build_baseline_indexes(candidate_rows)
    current_index = build_current_index(current_products)
    audited: list[dict[str, Any]] = []
    excluded = 0
    for data_row, source_sheet_row in enumerate(sheet_rows, start=1):
        sheet_row = {
            field: str(source_sheet_row.get(field) or "").strip()
            for field in OPERATIONAL_FIELDS
        }
        if not _is_business_row(sheet_row):
            excluded += 1
            continue
        baseline_matches, baseline_reason = match_sheet_to_baseline(
            sheet_row, baseline_indexes
        )
        result: dict[str, Any] = {
            "sheet_data_row": data_row,
            "sheet": sheet_row,
            "official_availability_status": "",
            "classification": NOT_FOUND,
            "candidate_count": len(baseline_matches),
            "reason": baseline_reason,
            "stable_ids": {},
            "official_session_name": "",
            "baseline_ticket": {},
            "official_ticket": {},
            "auto_selected": False,
        }
        if len(baseline_matches) > 1:
            result["classification"] = MULTIPLE_CANDIDATES
            result["baseline_candidates"] = [
                {
                    "idPerformance": row.get("idPerformance", ""),
                    "idProduct": row.get("idProduct", ""),
                    "sessionCode": row.get("sessionCode", ""),
                    "time": row.get("time", ""),
                    "session_info": row.get("session_info", ""),
                }
                for row in baseline_matches
            ]
            audited.append(result)
            continue
        if not baseline_matches:
            audited.append(result)
            continue

        baseline = baseline_matches[0]
        stable_ids = {
            "idPerformance": str(baseline.get("idPerformance") or ""),
            "idProduct": str(baseline.get("idProduct") or ""),
            "sessionCode": str(baseline.get("sessionCode") or ""),
        }
        result["stable_ids"] = stable_ids
        result["baseline_ticket"] = {
            field: str(baseline.get(field) or "").strip()
            for field in ("date", "time", "end_time", "venue", "event_name", "session_info")
        }
        official_matches = current_index.get(_stable_key(baseline), [])
        result["candidate_count"] = len(official_matches)
        if len(official_matches) > 1:
            result["classification"] = MULTIPLE_CANDIDATES
            result["reason"] = "multiple current products share all three stable IDs"
            audited.append(result)
            continue
        if not official_matches:
            result["reason"] = "stable 2026-08-10 session is absent from current official feed"
            audited.append(result)
            continue

        official = official_matches[0]
        try:
            result["official_ticket"] = project_current_product(official)
        except ValueError as exc:
            result["reason"] = (
                "current official product has invalid date/time metadata; "
                f"preserved as NOT_FOUND: {exc}"
            )
            audited.append(result)
            continue
        official_status = str(official.get("availabilityStatus") or "").strip()
        result["official_availability_status"] = official_status
        result["official_session_name"] = str(official.get("nmProduct") or "").strip()
        if official_status not in KNOWN_AVAILABILITY_STATUSES:
            result["reason"] = (
                "current official availabilityStatus is unsupported; preserved as NOT_FOUND: "
                f"{official_status!r}"
            )
            audited.append(result)
            continue
        sheet_status = sheet_row["availability_status"]
        if sheet_status == official_status:
            result["classification"] = UNCHANGED
            result["reason"] = baseline_reason + "; stable IDs matched; status unchanged"
        else:
            result["classification"] = STATUS_CHANGED
            result["reason"] = baseline_reason + "; stable IDs matched; status differs"
        audited.append(result)
    return audited, excluded


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    classifications = Counter(row["classification"] for row in rows)
    transitions = Counter(
        (
            row["sheet"]["availability_status"],
            row["official_availability_status"],
        )
        for row in rows
        if row["classification"] == STATUS_CHANGED
    )
    old_statuses = Counter(row["sheet"]["availability_status"] for row in rows)
    official_statuses = Counter(
        row["official_availability_status"]
        for row in rows
        if row["classification"] in {UNCHANGED, STATUS_CHANGED}
    )
    protected_statuses = Counter(
        (
            row["official_availability_status"]
            if row["classification"] in {UNCHANGED, STATUS_CHANGED}
            else row["sheet"]["availability_status"]
        )
        for row in rows
    )
    return {
        "classifications": {
            name: classifications.get(name, 0) for name in CLASSIFICATIONS
        },
        "sheet_statuses": dict(sorted(old_statuses.items())),
        "official_statuses_matched": dict(sorted(official_statuses.items())),
        "protected_effective_statuses": dict(sorted(protected_statuses.items())),
        "transitions": {
            f"{old} -> {new}": count
            for (old, new), count in sorted(transitions.items())
        },
    }


def run_audit(
    *,
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    sheet_loader: Callable[[], list[dict[str, str]]] | None = None,
    session_fetcher: Callable[[], tuple[list[dict[str, Any]], list[dict[str, Any]]]]
    | None = None,
    overall_timeout: float = DEFAULT_OVERALL_TIMEOUT_SECONDS,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run a fail-closed audit; no partial acquisition is classified."""

    overall_timeout = float(overall_timeout)
    if overall_timeout <= 0:
        raise ValueError("overall_timeout must be greater than zero")
    started = time.monotonic()
    deadline = started + overall_timeout
    emit = progress or (lambda _message: None)
    emit(
        "ticket_status_audit stage=start "
        f"overall_timeout_s={overall_timeout:g} sheet_write=false"
    )
    with external_request_timeout(overall_timeout, "ticket availability dry-run"):
        emit("ticket_status_audit stage=sheet_fetch_start range=A:G")
        remaining = max(0.001, deadline - time.monotonic())
        if sheet_loader is None:
            sheet_rows = load_asia_sheet_rows_read_only(
                hard_timeout=min(SHEET_HARD_TIMEOUT_SECONDS, remaining),
                progress=progress,
            )
        else:
            sheet_rows = sheet_loader()
        if not sheet_rows:
            raise ValueError("Asia Games Sheet contains zero rows")
        emit(f"ticket_status_audit stage=sheet_fetch_done rows={len(sheet_rows)}")

        candidate_rows = _read_candidate_rows(candidates_path)
        emit(
            "ticket_status_audit stage=baseline_loaded "
            f"selected_candidates={len(candidate_rows)}"
        )
        emit("ticket_status_audit stage=official_fetch_start")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("overall timeout expired before official ticket fetch")
        if session_fetcher is None:
            pages, products = fetch_session_pages(
                request_timeout=request_timeout,
                overall_timeout=remaining,
                progress=progress,
            )
        else:
            pages, products = session_fetcher()
        if not pages or len(products) <= 1:
            raise ValueError("unsafe current official ticket response; refusing audit")
        emit(
            "ticket_status_audit stage=official_fetch_done "
            f"pages={len(pages)} products={len(products)}"
        )

        rows, excluded = audit_sheet_rows(sheet_rows, candidate_rows, products)
        if not rows:
            raise ValueError("ticket status audit produced zero business rows")
        summary = summarize(rows)
        report = {
            "dry_run": True,
            "sheet_write": False,
            "sheet_schema": list(ASIA_OPERATIONAL_COLUMNS),
            "generated_date": date.today().isoformat(),
            "sheet_row_count": len(sheet_rows),
            "business_row_count": len(rows),
            "excluded_test_rows": excluded,
            "baseline_candidate_count": len(candidate_rows),
            "official_product_count": len(products),
            "summary": summary,
            "rows": rows,
        }
    emit(
        "ticket_status_audit stage=complete "
        f"elapsed_s={time.monotonic() - started:.3f} "
        + " ".join(
            f"{name}={summary['classifications'][name]}" for name in CLASSIFICATIONS
        )
        + " sheet_write=false"
    )
    return report


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# アジア大会 チケット販売状況 dry-run監査",
        "",
        "- dry-run: `true`",
        "- Google Sheet書き込み: `false`",
        f"- Sheet取得行: {report['sheet_row_count']}",
        f"- 営業用監査行: {report['business_row_count']}",
        f"- 除外した発火テスト行: {report['excluded_test_rows']}",
        f"- 現在公式API商品数: {report['official_product_count']}",
        "",
        "## 件数",
        "",
        "| 分類 | 件数 |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {name} | {summary['classifications'][name]} |"
        for name in CLASSIFICATIONS
    )
    lines.extend(["", "## 販売状態", "", "### Sheet（監査前）", ""])
    lines.extend(
        f"- {status}: {count}"
        for status, count in summary["sheet_statuses"].items()
    )
    lines.extend(["", "### Official（安定ID一致行）", ""])
    lines.extend(
        f"- {status}: {count}"
        for status, count in summary["official_statuses_matched"].items()
    )
    lines.extend(["", "### 変化内訳", ""])
    if summary["transitions"]:
        lines.extend(
            f"- {transition}: {count}"
            for transition, count in summary["transitions"].items()
        )
    else:
        lines.append("- なし")
    lines.extend(
        [
            "",
            "### 保護後の実効内訳",
            "",
            "`NOT_FOUND` / `MULTIPLE_CANDIDATES` はSheet値を保持して集計。",
            "",
        ]
    )
    lines.extend(
        f"- {status}: {count}"
        for status, count in summary["protected_effective_statuses"].items()
    )

    for classification in (STATUS_CHANGED, MULTIPLE_CANDIDATES, NOT_FOUND):
        selected = [
            row for row in report["rows"] if row["classification"] == classification
        ]
        lines.extend(
            [
                "",
                f"## {classification} ({len(selected)}件)",
                "",
                "| Sheet行 | 日時 | 会場 | event_name | Sheet | Official | 候補数 | 理由 |",
                "| ---: | --- | --- | --- | --- | --- | ---: | --- |",
            ]
        )
        for row in selected:
            sheet = row["sheet"]
            lines.append(
                f"| {row['sheet_data_row']} | {_md(sheet['date'])} {_md(sheet['time'])} | "
                f"{_md(sheet['venue'])} | {_md(sheet['event_name'])} | "
                f"{_md(sheet['availability_status'])} | "
                f"{_md(row['official_availability_status']) or '-'} | "
                f"{row['candidate_count']} | {_md(row['reason'])} |"
            )
    lines.extend(
        [
            "",
            "曖昧候補は自動選択していない。Sheet、session_info、availability_status、",
            "その他6列、7列スキーマはいずれも変更していない。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in report["rows"]:
            sheet = row["sheet"]
            stable = row["stable_ids"]
            writer.writerow(
                {
                    "sheet_data_row": row["sheet_data_row"],
                    **sheet,
                    "official_availability_status": row[
                        "official_availability_status"
                    ],
                    "classification": row["classification"],
                    "candidate_count": row["candidate_count"],
                    "reason": row["reason"],
                    "idPerformance": stable.get("idPerformance", ""),
                    "idProduct": stable.get("idProduct", ""),
                    "sessionCode": stable.get("sessionCode", ""),
                    "official_session_name": row["official_session_name"],
                    "official_date": row["official_ticket"].get("date", ""),
                    "official_time": row["official_ticket"].get("time", ""),
                    "official_end_time": row["official_ticket"].get("end_time", ""),
                    "official_venue": row["official_ticket"].get("venue", ""),
                    "official_event_name": row["official_ticket"].get("event_name", ""),
                    "official_session_info": row["official_ticket"].get(
                        "session_info", ""
                    ),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument(
        "--overall-timeout", type=float, default=DEFAULT_OVERALL_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS
    )
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    try:
        report = run_audit(
            candidates_path=args.candidates,
            overall_timeout=args.overall_timeout,
            request_timeout=args.request_timeout,
            progress=_progress,
        )
        markdown = render_markdown(report)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown, encoding="utf-8")
        write_csv(args.csv_output, report)
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:
        print(
            "ticket_status_audit stage=failed "
            f"error_type={type(exc).__name__} error={exc} sheet_write=false",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from None
    print(markdown, end="")


if __name__ == "__main__":
    main()
