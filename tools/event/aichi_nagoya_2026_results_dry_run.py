#!/usr/bin/env python3
"""Read-only reconciliation of official Results units against the Asia Games sheet.

The command intentionally has no Google Sheets write path.  It reads the fixed
seven-column ``アジア大会`` export and reports candidates for one day.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.utils.google_sheet_events import (
    ASIA_OPERATIONAL_COLUMNS,
    ASIA_OPERATIONAL_SHEET_URL,
)
from tools.event.aichi_nagoya_2026_results import (
    RESULTS_HARD_TIMEOUT_SECONDS,
    ExternalRequestTimeout,
    external_request_timeout,
    extract_discipline_codes,
    fetch_day_schedule,
    fetch_normalized_discipline_daily,
)


MATCH = "MATCH"
AMBIGUOUS = "AMBIGUOUS"
NOT_FOUND = "NOT_FOUND"
RECONCILIATION_RESULTS = (MATCH, AMBIGUOUS, NOT_FOUND)
ASIA_DRY_RUN_SHEET_URL = f"{ASIA_OPERATIONAL_SHEET_URL}&range=A:G"
SHEET_CONNECT_TIMEOUT_SECONDS = 5.0
SHEET_READ_TIMEOUT_SECONDS = 15.0
SHEET_REQUEST_TIMEOUT = (
    SHEET_CONNECT_TIMEOUT_SECONDS,
    SHEET_READ_TIMEOUT_SECONDS,
)
SHEET_HARD_TIMEOUT_SECONDS = 20.0
DRY_RUN_OVERALL_TIMEOUT_SECONDS = 90.0


def _emit_progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _stderr_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _remaining_hard_timeout(
    deadline: float | None,
    request_limit: float,
    stage: str,
) -> float:
    if deadline is None:
        return request_limit
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExternalRequestTimeout(
            f"dry-run overall timeout expired before stage={stage}"
        )
    return min(request_limit, remaining)


# Each group has one comparison identity.  The aliases are deliberately exact:
# unknown names do not receive fuzzy or substring matching.
VENUE_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "aichi_international_arena": (
        "Aichi International Arena",
        "IGアリーナ",
        "愛知国際アリーナ",
    ),
    "nagoya_rainbow_pool": (
        "名古屋市総合体育館［レインボープール］",
        "名古屋市総合体育館（レインボープール）",
        "NGKアリーナ",
    ),
    "nagoya_rainbow_hall": (
        "名古屋市総合体育館［レインボーホール］",
        "名古屋市総合体育館（レインボーホール）",
        "NGKホール",
    ),
    "mizuho_stadium": (
        "名古屋市瑞穂公園陸上競技場",
        "パロマ瑞穂スタジアム",
    ),
    "mizuho_rugby_ground": (
        "名古屋市瑞穂公園ラグビー場",
        "パロマ瑞穂ラグビー場",
    ),
    "mizuho_arena": (
        "名古屋市瑞穂公園体育館",
        "パロマ瑞穂アリーナ",
    ),
    "higashiyama_tennis_center": (
        "名古屋市東山公園テニスセンター",
        "東山公園テニスセンター",
    ),
    "fukiage_hall": (
        "名古屋市中小企業振興会館",
        "吹上ホール",
    ),
    "minato_soccer_stadium": (
        "名古屋市港サッカー場",
        "CSアセット港サッカー場",
    ),
    # Confirmed official Results names needed by the 2026-09-16 real-data run.
    "park_arena_komaki": (
        "Park Arena Komaki",
        "小牧市スポーツ公園総合体育館",
    ),
    "wave_stadium_kariya": (
        "WAVE STADIUM KARIYA",
        "ウェーブスタジアム刈谷",
    ),
    "toyota_stadium": (
        "TOYOTA STADIUM",
        "豊田スタジアム",
    ),
}


SPORT_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "3x3_basketball": ("3x3 Basketball", "3×3 Basketball", "3x3 バスケットボール"),
    "artistic_gymnastics": ("Artistic Gymnastics", "体操 (体操)", "体操（体操）"),
    "athletics": ("Athletics", "陸上競技（トラック/フィールド）"),
    "badminton": ("Badminton", "バドミントン"),
    "basketball": ("Basketball", "バスケットボール"),
    "cricket": ("Cricket", "Cricket T20", "クリケット（T20）"),
    "football": ("Football", "サッカー"),
    "golf": ("Golf", "ゴルフ"),
    "handball": ("Handball", "ハンドボール"),
    "ju_jitsu": ("Ju-Jitsu", "Ju Jitsu", "コンバットスポーツ (柔術)"),
    "judo": ("Judo", "柔道"),
    "kabaddi": ("Kabaddi", "カバディ"),
    "kurash": ("Kurash", "コンバットスポーツ (クラッシュ)"),
    "modern_pentathlon": ("Modern Pentathlon", "近代五種"),
    "rhythmic_gymnastics": ("Rhythmic Gymnastics", "体操 (新体操)"),
    "rugby_sevens": ("Rugby Sevens", "Rugby 7s", "ラグビー（ラグビー7s）"),
    "sepaktakraw": ("Sepaktakraw", "Sepak Takraw", "セパタクロー"),
    "soft_tennis": ("Soft Tennis", "ソフトテニス"),
    "sport_climbing": ("Sport Climbing", "スポーツクライミング"),
    "squash": ("Squash", "スカッシュ"),
    "table_tennis": ("Table Tennis", "卓球"),
    "tennis": ("Tennis", "テニス"),
    "trampoline_gymnastics": ("Trampoline Gymnastics", "体操 (トランポリン)"),
    "volleyball": ("Volleyball", "バレーボール"),
    "water_polo": ("Water Polo", "Aquatics - Water Polo", "水泳 (水球)"),
    "weightlifting": ("Weightlifting", "ウエイトリフティング"),
    "wushu": ("Wushu", "武術太極拳"),
}


DISCIPLINE_CANONICAL = {
    "ATH": "athletics",
    "BDM": "badminton",
    "BKB": "basketball",
    "BK3": "3x3_basketball",
    "CKT": "cricket",
    "FBL": "football",
    "GAR": "artistic_gymnastics",
    "GLF": "golf",
    "GRY": "rhythmic_gymnastics",
    "GTR": "trampoline_gymnastics",
    "HBL": "handball",
    "JUD": "judo",
    "JJI": "ju_jitsu",
    "KAB": "kabaddi",
    "KUR": "kurash",
    "MPN": "modern_pentathlon",
    "RU7": "rugby_sevens",
    "SPK": "sepaktakraw",
    "SQU": "squash",
    "TST": "soft_tennis",
    "TEN": "tennis",
    "TTE": "table_tennis",
    "VVO": "volleyball",
    "WLF": "weightlifting",
    "WPO": "water_polo",
    "WSU": "wushu",
}


def _comparison_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[\s\u3000・･·,，.．()\[\]{}【】/\\_\-‐‑‒–—―]+", "", text)


def _alias_index(groups: dict[str, tuple[str, ...]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for canonical, aliases in groups.items():
        for alias in aliases:
            key = _comparison_text(alias)
            previous = index.setdefault(key, canonical)
            if previous != canonical:
                raise RuntimeError(f"conflicting alias {alias!r}: {previous} / {canonical}")
    return index


VENUE_ALIAS_INDEX = _alias_index(VENUE_ALIAS_GROUPS)
SPORT_ALIAS_INDEX = _alias_index(SPORT_ALIAS_GROUPS)


def normalize_venue(value: Any) -> str:
    key = _comparison_text(value)
    return VENUE_ALIAS_INDEX.get(key, key)


def normalize_sport(value: Any, discipline_code: Any = "") -> str:
    code = str(discipline_code or "").strip().upper()
    if code in DISCIPLINE_CANONICAL:
        return DISCIPLINE_CANONICAL[code]
    key = _comparison_text(value)
    return SPORT_ALIAS_INDEX.get(key, key)


def normalize_date(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return text


def normalize_time(value: Any) -> str:
    text = str(value or "").strip()
    for pattern in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, pattern).strftime("%H:%M:%S")
        except ValueError:
            pass
    return text


def _session_phase_label(value: Any) -> str:
    """Compact an official Japanese PhaseDesc for the Sheet display candidate."""

    label = unicodedata.normalize("NFKC", str(value or "")).strip()
    label = re.sub(r"\s+", "", label)
    label = label.replace("一次ラウンド-グループ", "グループ")
    # Results uses several separators (or no separator) between these terms.
    # Keep this deliberately narrow so other rounds such as quarterfinals,
    # classification matches, and medal sessions remain untouched.
    label = re.sub(
        r"予選ラウンド[-‐‑‒–—―ー・]*?(グループ|プール)",
        r"予選\1",
        label,
    )
    return label


def build_session_info_candidate(result: dict[str, Any]) -> str:
    """Build a candidate from official API labels without translating them."""

    event_label = str(result.get("event_name") or "").strip()
    phase_label = _session_phase_label(
        result.get("phase_name") or result.get("round_name") or ""
    )
    session_label = str(result.get("session_name") or "").strip()
    # Individual brackets can also be represented as head-to-head units.  Player
    # names are deliberately not suitable for automatic session_info updates.
    if result.get("is_head_to_head") and result.get("is_team_event", True):
        label = phase_label or event_label or session_label
        matchup = str(result.get("matchup") or "").strip()
        detail = matchup or (session_label if session_label != label else "")
        return "｜".join(part for part in (label, detail) if part)

    # PhaseDesc is preferred over UnitDesc.  Some official Japanese daily feeds
    # currently contain a literal "?" in UnitDesc while PhaseDesc is intact.
    return phase_label or session_label or event_label


def fetch_normalized_day(
    target_date: str,
    *,
    day_fetcher: Callable[[str], Any] | None = None,
    daily_fetcher: Callable[[str, str], list[dict[str, Any]]] | None = None,
    progress: Callable[[str], None] | None = None,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch all discipline daily feeds for one date, failing on partial data."""

    day = normalize_date(target_date)
    _emit_progress(progress, f"dry_run_progress stage=results_overview_start date={day}")
    overview_hard_timeout = _remaining_hard_timeout(
        deadline, RESULTS_HARD_TIMEOUT_SECONDS, "results_overview"
    )
    if day_fetcher is None:
        overview = fetch_day_schedule(
            day,
            hard_timeout=overview_hard_timeout,
            progress=progress,
        )
    else:
        overview = day_fetcher(day)
    disciplines = extract_discipline_codes(overview)
    if not disciplines:
        raise ValueError(f"Results day schedule has no disciplines: {day}")
    _emit_progress(
        progress,
        "dry_run_progress stage=results_overview_done "
        f"date={day} discipline_count={len(disciplines)} "
        f"disciplines={','.join(disciplines)}",
    )

    records: list[dict[str, Any]] = []
    for index, discipline in enumerate(disciplines, start=1):
        daily_hard_timeout = _remaining_hard_timeout(
            deadline,
            RESULTS_HARD_TIMEOUT_SECONDS,
            f"results_daily_{discipline}",
        )
        _emit_progress(
            progress,
            "dry_run_progress stage=results_daily_start "
            f"date={day} index={index}/{len(disciplines)} discipline={discipline}",
        )
        started = time.monotonic()
        try:
            if daily_fetcher is None:
                daily = fetch_normalized_discipline_daily(
                    discipline,
                    day,
                    hard_timeout=daily_hard_timeout,
                    progress=progress,
                )
            else:
                daily = daily_fetcher(discipline, day)
        except Exception as exc:
            _emit_progress(
                progress,
                "dry_run_progress stage=results_daily_error "
                f"date={day} index={index}/{len(disciplines)} "
                f"discipline={discipline} elapsed_s={time.monotonic() - started:.3f} "
                f"error_type={type(exc).__name__} error={exc}",
            )
            raise
        if not isinstance(daily, list):
            raise ValueError(f"Results daily is not a list: discipline={discipline}")
        if not daily:
            raise ValueError(f"Results daily has no records: discipline={discipline} date={day}")
        records.extend(daily)
        _emit_progress(
            progress,
            "dry_run_progress stage=results_daily_done "
            f"date={day} index={index}/{len(disciplines)} discipline={discipline} "
            f"records={len(daily)} elapsed_s={time.monotonic() - started:.3f}",
        )
    selected = [record for record in records if normalize_date(record.get("date")) == day]
    if not selected:
        raise ValueError(f"Results normalized day has no records: {day}")
    _emit_progress(
        progress,
        f"dry_run_progress stage=results_all_done date={day} records={len(selected)}",
    )
    return selected


def load_asia_sheet_rows_read_only(
    *,
    http_get: Callable[..., Any] = requests.get,
    timeout: float | tuple[float, float] = SHEET_REQUEST_TIMEOUT,
    hard_timeout: float = SHEET_HARD_TIMEOUT_SECONDS,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, str]]:
    """GET only A:G from the operational tab and validate the fixed schema."""

    connect_timeout, read_timeout = (
        timeout if isinstance(timeout, tuple) else (timeout, timeout)
    )
    started = time.monotonic()
    _emit_progress(
        progress,
        "external_http_start source=google_sheet "
        f"endpoint={ASIA_DRY_RUN_SHEET_URL} "
        f"connect_timeout_s={connect_timeout:g} read_timeout_s={read_timeout:g} "
        f"hard_timeout_s={hard_timeout:g}",
    )
    try:
        with external_request_timeout(hard_timeout, "Google Sheets A:G export"):
            response = http_get(ASIA_DRY_RUN_SHEET_URL, timeout=timeout)
            response.raise_for_status()
            response.encoding = "utf-8-sig"
            reader = csv.DictReader(io.StringIO(response.text))
            if reader.fieldnames != ASIA_OPERATIONAL_COLUMNS:
                raise ValueError(
                    "アジア大会 dry-run sheet列不一致: "
                    f"expected={ASIA_OPERATIONAL_COLUMNS} actual={reader.fieldnames}"
                )
            rows = [
                {column: (row.get(column) or "").strip() for column in ASIA_OPERATIONAL_COLUMNS}
                for row in reader
                if (row.get("date") or "").strip()
                and (row.get("event_name") or "").strip()
            ]
    except Exception as exc:
        _emit_progress(
            progress,
            "external_http_error source=google_sheet "
            f"endpoint={ASIA_DRY_RUN_SHEET_URL} "
            f"elapsed_s={time.monotonic() - started:.3f} "
            f"error_type={type(exc).__name__} error={exc}",
        )
        raise
    _emit_progress(
        progress,
        "external_http_done source=google_sheet "
        f"endpoint={ASIA_DRY_RUN_SHEET_URL} "
        f"elapsed_s={time.monotonic() - started:.3f} records={len(rows)}",
    )
    if not rows:
        raise ValueError("アジア大会 dry-run sheet 0件")
    return rows


def load_sheet_day(
    target_date: str,
    *,
    sheet_loader: Callable[[], list[dict[str, str]]] | None = None,
) -> list[dict[str, str]]:
    """Read and select one day from the fixed seven-column operational sheet."""

    sheet_loader = sheet_loader or load_asia_sheet_rows_read_only
    day = normalize_date(target_date)
    rows = sheet_loader()
    selected = [row for row in rows if normalize_date(row.get("date")) == day]
    if not selected:
        raise ValueError(f"アジア大会 sheet has no rows for date: {day}")
    return selected


def _result_projection(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_language": record.get("source_language", ""),
        "date": record.get("date", ""),
        "time": record.get("time", ""),
        "venue": record.get("venue_name", ""),
        "sport": record.get("discipline_name", ""),
        "discipline_code": record.get("discipline_code", ""),
        "event": record.get("event_name", ""),
        "phase": record.get("phase_name", ""),
        "round": record.get("round_name", ""),
        "session": record.get("session_name", ""),
        "is_head_to_head": bool(record.get("is_head_to_head")),
        "is_team_event": bool(
            record.get("is_team_event", bool(record.get("is_head_to_head")))
        ),
        "competitors": record.get("competitors"),
        "matchup": record.get("matchup", ""),
        "session_info_candidate": build_session_info_candidate(record),
    }


def reconcile_sheet_row(
    sheet_row: dict[str, str], results: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Classify one Sheet row using exact normalized comparison keys."""

    records = list(results)
    sheet_date = normalize_date(sheet_row.get("date"))
    sheet_time = normalize_time(sheet_row.get("time"))
    sheet_venue = normalize_venue(sheet_row.get("venue"))
    sheet_sport = normalize_sport(sheet_row.get("event_name"))

    date_candidates = [
        record for record in records if normalize_date(record.get("date")) == sheet_date
    ]
    time_candidates = [
        record
        for record in date_candidates
        if normalize_time(record.get("time")) == sheet_time
    ]
    venue_candidates = [
        record
        for record in time_candidates
        if normalize_venue(record.get("venue_name")) == sheet_venue
    ]
    matches = [
        record
        for record in venue_candidates
        if normalize_sport(
            record.get("discipline_name"), record.get("discipline_code")
        )
        == sheet_sport
    ]
    date_venue_sport_candidates = [
        record
        for record in date_candidates
        if normalize_venue(record.get("venue_name")) == sheet_venue
        and normalize_sport(
            record.get("discipline_name"), record.get("discipline_code")
        )
        == sheet_sport
    ]
    date_time_sport_candidates = [
        record
        for record in time_candidates
        if normalize_sport(
            record.get("discipline_name"), record.get("discipline_code")
        )
        == sheet_sport
    ]

    stage_counts = (
        f"date={len(date_candidates)}, date_time={len(time_candidates)}, "
        f"date_time_venue={len(venue_candidates)}, full_key={len(matches)}"
    )
    if len(matches) == 1:
        classification = MATCH
        reason = f"date/time exact + venue alias + sport alias ({stage_counts})"
    elif len(matches) > 1:
        classification = AMBIGUOUS
        reason = f"multiple Results units share the full normalized key ({stage_counts})"
    elif date_venue_sport_candidates:
        classification = NOT_FOUND
        reason = (
            "time did not match within date/venue/sport "
            f"(nearby={len(date_venue_sport_candidates)}; {stage_counts})"
        )
    elif date_time_sport_candidates:
        classification = NOT_FOUND
        reason = (
            "venue alias did not match within date/time/sport "
            f"(nearby={len(date_time_sport_candidates)}; {stage_counts})"
        )
    elif venue_candidates:
        classification = NOT_FOUND
        reason = (
            "sport alias did not match within date/time/venue "
            f"(nearby={len(venue_candidates)}; {stage_counts})"
        )
    elif not date_candidates:
        classification = NOT_FOUND
        reason = f"date did not match ({stage_counts})"
    elif not time_candidates:
        classification = NOT_FOUND
        reason = f"time did not match within date ({stage_counts})"
    elif not venue_candidates:
        classification = NOT_FOUND
        reason = f"venue alias did not match within date/time ({stage_counts})"
    else:
        classification = NOT_FOUND
        reason = f"no Results unit matched at least three comparison keys ({stage_counts})"

    projected = [_result_projection(record) for record in matches]
    nearby_records: list[dict[str, Any]] = []
    if classification == NOT_FOUND:
        nearby_records = (
            date_venue_sport_candidates
            or date_time_sport_candidates
            or venue_candidates
        )
    return {
        "classification": classification,
        "candidate_count": len(matches),
        "reason": reason,
        "sheet": {
            "date": sheet_row.get("date", ""),
            "time": sheet_row.get("time", ""),
            "venue": sheet_row.get("venue", ""),
            "event_name": sheet_row.get("event_name", ""),
        },
        "results_candidates": projected,
        "nearby_results": [_result_projection(record) for record in nearby_records],
        # A future writer may use this only after checking MATCH.  AMBIGUOUS is
        # intentionally never collapsed to one candidate.
        "session_info_candidate": (
            projected[0]["session_info_candidate"] if classification == MATCH else ""
        ),
    }


def reconcile_day(
    sheet_rows: Iterable[dict[str, str]], results: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    records = list(results)
    return [reconcile_sheet_row(row, records) for row in sheet_rows]


def summarize(reconciliations: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(item.get("classification") for item in reconciliations)
    return {result: counts.get(result, 0) for result in RECONCILIATION_RESULTS}


def run_dry_run(
    target_date: str,
    *,
    sheet_loader: Callable[[], list[dict[str, str]]] | None = None,
    day_fetcher: Callable[[str], Any] | None = None,
    daily_fetcher: Callable[[str, str], list[dict[str, Any]]] | None = None,
    overall_timeout: float = DRY_RUN_OVERALL_TIMEOUT_SECONDS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    overall_timeout = float(overall_timeout)
    if overall_timeout <= 0:
        raise ValueError("dry-run overall timeout must be greater than zero")
    started = time.monotonic()
    deadline = started + overall_timeout
    day = normalize_date(target_date)
    stage = "start"
    _emit_progress(
        progress,
        "dry_run_progress stage=start "
        f"date={day} overall_timeout_s={overall_timeout:g} sheet_write=false",
    )
    try:
        stage = "sheet_fetch"
        _emit_progress(progress, f"dry_run_progress stage=sheet_fetch_start date={day}")
        if sheet_loader is None:
            sheet_hard_timeout = _remaining_hard_timeout(
                deadline, SHEET_HARD_TIMEOUT_SECONDS, stage
            )

            def bounded_sheet_loader() -> list[dict[str, str]]:
                return load_asia_sheet_rows_read_only(
                    hard_timeout=sheet_hard_timeout,
                    progress=progress,
                )

            selected_sheet_loader = bounded_sheet_loader
        else:
            selected_sheet_loader = sheet_loader
        sheet_rows = load_sheet_day(day, sheet_loader=selected_sheet_loader)
        _emit_progress(
            progress,
            f"dry_run_progress stage=sheet_fetch_done date={day} rows={len(sheet_rows)}",
        )

        stage = "results_fetch"
        results = fetch_normalized_day(
            day,
            day_fetcher=day_fetcher,
            daily_fetcher=daily_fetcher,
            progress=progress,
            deadline=deadline,
        )

        stage = "reconcile"
        _remaining_hard_timeout(deadline, overall_timeout, stage)
        _emit_progress(
            progress,
            "dry_run_progress stage=reconcile_start "
            f"date={day} sheet_rows={len(sheet_rows)} results_records={len(results)}",
        )
        reconciliations = reconcile_day(sheet_rows, results)
        summary = summarize(reconciliations)
        report = {
            "dry_run": True,
            "sheet_write": False,
            "date": day,
            "sheet_schema": list(ASIA_OPERATIONAL_COLUMNS),
            "summary": summary,
            "rows": reconciliations,
        }
        _emit_progress(
            progress,
            "dry_run_progress stage=complete "
            f"date={day} elapsed_s={time.monotonic() - started:.3f} "
            f"MATCH={summary[MATCH]} AMBIGUOUS={summary[AMBIGUOUS]} "
            f"NOT_FOUND={summary[NOT_FOUND]} sheet_write=false",
        )
        return report
    except Exception as exc:
        _emit_progress(
            progress,
            "dry_run_progress stage=failed "
            f"current_stage={stage} date={day} "
            f"elapsed_s={time.monotonic() - started:.3f} "
            f"error_type={type(exc).__name__} error={exc}",
        )
        raise


def _append_competitor_diagnostics(
    lines: list[str], candidate: dict[str, Any]
) -> None:
    if not candidate["is_head_to_head"]:
        return
    lines.append(f"    matchup={candidate['matchup']}")
    competitors = candidate.get("competitors") or {}
    for side in ("home", "away"):
        competitor = competitors.get(side) or {}
        if competitor:
            lines.append(
                f"    {side}: org={competitor.get('organization', '')} "
                f"display_name={competitor.get('display_name', '')} "
                f"api_name={competitor.get('name', '')}"
            )


def render_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"dry_run=true sheet_write=false date={report['date']}",
        (
            f"SUMMARY MATCH={summary[MATCH]} AMBIGUOUS={summary[AMBIGUOUS]} "
            f"NOT_FOUND={summary[NOT_FOUND]}"
        ),
    ]
    for index, item in enumerate(report["rows"], start=1):
        sheet = item["sheet"]
        lines.extend(
            [
                "",
                (
                    f"[{index}] {item['classification']} "
                    f"candidate_count={item['candidate_count']}"
                ),
                (
                    "  Sheet: "
                    f"date={sheet['date']} time={sheet['time']} venue={sheet['venue']} "
                    f"event_name={sheet['event_name']}"
                ),
                f"  Reason: {item['reason']}",
            ]
        )
        for candidate_index, candidate in enumerate(item["results_candidates"], start=1):
            lines.extend(
                [
                    (
                        f"  Results[{candidate_index}]: date={candidate['date']} "
                        f"time={candidate['time']} venue={candidate['venue']} "
                        f"sport={candidate['sport']}"
                    ),
                    (
                        f"    phase={candidate['phase']} round={candidate['round']} "
                        f"session={candidate['session']}"
                    ),
                ]
            )
            _append_competitor_diagnostics(lines, candidate)
            lines.append(
                f"    session_info_candidate={candidate['session_info_candidate']}"
            )
        if item["classification"] == NOT_FOUND:
            lines.append("  Results: none")
            for candidate_index, candidate in enumerate(item["nearby_results"], start=1):
                lines.extend(
                    [
                        (
                            f"  Nearby Results[{candidate_index}] (not selected): "
                            f"date={candidate['date']} time={candidate['time']} "
                            f"venue={candidate['venue']} sport={candidate['sport']}"
                        ),
                        (
                            f"    phase={candidate['phase']} round={candidate['round']} "
                            f"session={candidate['session']}"
                        ),
                    ]
                )
                _append_competitor_diagnostics(lines, candidate)
                lines.append(
                    "    session_info_candidate_not_selected="
                    f"{candidate['session_info_candidate']}"
                )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", help="target date in YYYY-MM-DD")
    parser.add_argument(
        "--format", choices=("text", "json"), default="text", dest="output_format"
    )
    parser.add_argument(
        "--overall-timeout",
        type=float,
        default=DRY_RUN_OVERALL_TIMEOUT_SECONDS,
        help=(
            "hard wall-clock limit for all external reads "
            f"(default: {DRY_RUN_OVERALL_TIMEOUT_SECONDS:g}s)"
        ),
    )
    args = parser.parse_args()
    try:
        report = run_dry_run(
            args.date,
            overall_timeout=args.overall_timeout,
            progress=_stderr_progress,
        )
    except Exception as exc:
        print(
            f"dry_run_error error_type={type(exc).__name__} error={exc}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from None
    if args.output_format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))


if __name__ == "__main__":
    main()
