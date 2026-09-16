#!/usr/bin/env python3
"""Fetch and normalize the Aichi-Nagoya 2026 official Results API.

This module deliberately does not write to the operational CSV or Google Sheets.
The official Results feed is kept as a separate input until its merge policy is
defined.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import signal
import threading
import time
import zlib
from datetime import date, datetime
from typing import Any, Callable, Iterator

import requests


RESULTS_API_ROOT_URL = "https://back.results.asiangames2026.org/s/AG2026"
RESULTS_DEFAULT_LANGUAGE = "ja"
RESULTS_SUPPORTED_LANGUAGES = ("ja", "en")
RESULTS_API_BASE_URL = f"{RESULTS_API_ROOT_URL}/{RESULTS_DEFAULT_LANGUAGE}"
RESULTS_SITE_URL = "https://results.asiangames2026.org"
RESULTS_REQUEST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": RESULTS_SITE_URL,
    "Referer": f"{RESULTS_SITE_URL}/",
    "User-Agent": "Mozilla/5.0",
}
RESULTS_CONNECT_TIMEOUT_SECONDS = 5.0
RESULTS_READ_TIMEOUT_SECONDS = 15.0
RESULTS_REQUEST_TIMEOUT = (
    RESULTS_CONNECT_TIMEOUT_SECONDS,
    RESULTS_READ_TIMEOUT_SECONDS,
)
RESULTS_HARD_TIMEOUT_SECONDS = 20.0
DISCIPLINE_CODE_RE = re.compile(r"[A-Z0-9]{2,10}")

# Japanese display names keyed by the official Results ``Org`` code.  These are
# organization/team labels, not a general-purpose translation table.  Unknown
# codes deliberately fall back to the API Name, and individual athlete names
# are never replaced with an organization name.
TEAM_ORG_NAME_JA = {
    "AFG": "アフガニスタン",
    "BAN": "バングラデシュ",
    "BHU": "ブータン",
    "BRN": "バーレーン",
    "BRU": "ブルネイ・ダルサラーム",
    "CAM": "カンボジア",
    "CHN": "中華人民共和国",
    "HKG": "ホンコン・チャイナ",
    "INA": "インドネシア",
    "IND": "インド",
    "IRI": "イラン・イスラム共和国",
    "IRQ": "イラク",
    "JOR": "ヨルダン",
    "JPN": "日本",
    "KAZ": "カザフスタン",
    "KGZ": "キルギス",
    "KOR": "大韓民国",
    "KSA": "サウジアラビア",
    "KUW": "クウェート",
    "LAO": "ラオス人民民主共和国",
    "LBN": "レバノン",
    "MAC": "マカオ・チャイナ",
    "MAS": "マレーシア",
    "MDV": "モルディブ",
    "MGL": "モンゴル",
    "MYA": "ミャンマー",
    "NEP": "ネパール",
    "OMA": "オマーン",
    "PAK": "パキスタン",
    "PLE": "パレスチナ",
    "PHI": "フィリピン",
    "PRK": "朝鮮民主主義人民共和国",
    "QAT": "カタール",
    "SGP": "シンガポール",
    "SRI": "スリランカ",
    "SYR": "シリア・アラブ共和国",
    "THA": "タイ",
    "TJK": "タジキスタン",
    "TKM": "トルクメニスタン",
    "TLS": "東ティモール",
    "TPE": "チャイニーズ・タイペイ",
    "UAE": "アラブ首長国連邦",
    "UZB": "ウズベキスタン",
    "VIE": "ベトナム",
    "YEM": "イエメン",
}


class ResultsPayloadError(ValueError):
    """Raised when a Results API response cannot be decoded or normalized."""


class ExternalRequestTimeout(TimeoutError):
    """Raised when an external request exceeds its hard wall-clock deadline."""


@contextlib.contextmanager
def external_request_timeout(seconds: float, label: str) -> Iterator[None]:
    """Apply a POSIX wall-clock deadline in addition to requests' I/O timeout.

    ``requests`` connect/read timeouts do not strictly bound DNS resolution,
    redirects, or a response that keeps trickling bytes.  The CLI runs in the
    main thread on Linux, where ``SIGALRM`` supplies the final hard stop.
    """

    seconds = float(seconds)
    if seconds <= 0:
        raise ExternalRequestTimeout(f"{label} hard timeout expired before request")
    if (
        threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "SIGALRM")
        or not hasattr(signal, "setitimer")
    ):
        # Library callers in non-main threads still retain the explicit
        # requests connect/read timeout.  The production CLI uses this guard.
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def raise_timeout(_signum: int, _frame: Any) -> None:
        raise ExternalRequestTimeout(
            f"{label} exceeded hard timeout of {seconds:.1f}s"
        )

    signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            remaining = max(previous_timer[0] - (time.monotonic() - started), 0.000001)
            signal.setitimer(signal.ITIMER_REAL, remaining, previous_timer[1])


def _emit_progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _timeout_parts(timeout: float | tuple[float, float]) -> tuple[float, float]:
    if isinstance(timeout, tuple):
        return float(timeout[0]), float(timeout[1])
    return float(timeout), float(timeout)


def decode_results_payload(raw: bytes | str) -> Any:
    """Restore and decode a JSON payload returned by the official Results API.

    The API serializes compressed bytes as Latin-1 characters and then sends that
    string as UTF-8. Reversing those two character encodings reconstructs the zlib
    stream.
    """

    try:
        wire_text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        packed = wire_text.encode("latin-1")
    except (UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise ResultsPayloadError("Results payload character encoding is invalid") from exc

    try:
        json_bytes = zlib.decompress(packed)
    except zlib.error as exc:
        raise ResultsPayloadError("Results payload is not a valid zlib stream") from exc

    try:
        return json.loads(json_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultsPayloadError("Results payload does not contain valid UTF-8 JSON") from exc


def _get_response_bytes(response: Any) -> bytes:
    raw = getattr(response, "content", None)
    if isinstance(raw, bytes):
        return raw
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.encode("utf-8")
    raise ResultsPayloadError("Results response has neither byte content nor text")


def fetch_results_payload(
    path: str,
    *,
    http_get: Callable[..., Any] = requests.get,
    timeout: float | tuple[float, float] = RESULTS_REQUEST_TIMEOUT,
    hard_timeout: float = RESULTS_HARD_TIMEOUT_SECONDS,
    progress: Callable[[str], None] | None = None,
    language: str = RESULTS_DEFAULT_LANGUAGE,
) -> Any:
    """Fetch one API path and return its expanded JSON value."""

    if not path.startswith("/") or ".." in path or "://" in path:
        raise ValueError(f"invalid Results API path: {path!r}")
    language = normalize_results_language(language)
    base_url = f"{RESULTS_API_ROOT_URL}/{language}"
    url = f"{base_url}{path}"
    connect_timeout, read_timeout = _timeout_parts(timeout)
    started = time.monotonic()
    _emit_progress(
        progress,
        "external_http_start source=results "
        f"language={language} endpoint={path} connect_timeout_s={connect_timeout:g} "
        f"read_timeout_s={read_timeout:g} hard_timeout_s={hard_timeout:g}",
    )
    try:
        with external_request_timeout(hard_timeout, f"Results API {path}"):
            response = http_get(url, headers=RESULTS_REQUEST_HEADERS, timeout=timeout)
            response.raise_for_status()
            value = decode_results_payload(_get_response_bytes(response))
    except Exception as exc:
        _emit_progress(
            progress,
            "external_http_error source=results "
            f"language={language} endpoint={path} "
            f"elapsed_s={time.monotonic() - started:.3f} "
            f"error_type={type(exc).__name__} error={exc}",
        )
        raise
    _emit_progress(
        progress,
        "external_http_done source=results "
        f"language={language} endpoint={path} "
        f"elapsed_s={time.monotonic() - started:.3f}",
    )
    return value


def _date_text(target_date: date | datetime | str) -> str:
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    if isinstance(target_date, date):
        return target_date.isoformat()
    text = str(target_date).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid Results schedule date: {target_date!r}") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"Results schedule date must be YYYY-MM-DD: {target_date!r}")
    return text


def normalize_discipline_code(discipline: str) -> str:
    code = str(discipline).strip().upper()
    if not DISCIPLINE_CODE_RE.fullmatch(code):
        raise ValueError(f"invalid Results discipline code: {discipline!r}")
    return code


def normalize_results_language(language: str) -> str:
    normalized = str(language or "").strip().lower()
    if normalized not in RESULTS_SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported Results API language: {language!r}")
    return normalized


def fetch_schedule_matrix(**kwargs: Any) -> Any:
    """Fetch the all-sports schedule matrix."""

    return fetch_results_payload("/ALL/schedule/matrix", **kwargs)


def fetch_day_schedule(target_date: date | datetime | str, **kwargs: Any) -> Any:
    """Fetch the all-sports overview for one date."""

    return fetch_results_payload(f"/ALL/schedule/day/{_date_text(target_date)}", **kwargs)


def fetch_discipline_daily(
    discipline: str,
    target_date: date | datetime | str,
    **kwargs: Any,
) -> Any:
    """Fetch the unmodified expanded daily payload for one discipline."""

    code = normalize_discipline_code(discipline)
    day = _date_text(target_date)
    return fetch_results_payload(f"/{code}/schedule/daily/{day}", **kwargs)


def extract_discipline_codes(payload: Any) -> list[str]:
    """Return unique ``Disc`` codes from an expanded day response, in source order."""

    found: list[str] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            discipline = value.get("Disc")
            if isinstance(discipline, str):
                code = discipline.strip().upper()
                if DISCIPLINE_CODE_RE.fullmatch(code) and code not in seen and code != "ALL":
                    seen.add(code)
                    found.append(code)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return found


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _nested_competitor(
    record: dict[str, Any], key: str, *, use_team_org_name: bool = False
) -> dict[str, str]:
    value = record.get(key)
    if not isinstance(value, dict):
        value = {}
    name = _text(value.get("Name"))
    organization = _text(value.get("Org")).upper()
    organization_name = TEAM_ORG_NAME_JA.get(organization, "")
    if use_team_org_name and organization_name:
        display_name = organization_name
        display_name_source = "org_code"
    else:
        display_name = name
        display_name_source = "api_name_fallback" if name else ""
    return {
        "name": name,
        "organization": organization,
        "display_name": display_name,
        "display_name_source": display_name_source,
    }


def _normalized_start(value: Any) -> tuple[str, str, str]:
    raw = _text(value)
    if not raw:
        return "", "", ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResultsPayloadError(f"invalid DateTimeRaw: {raw!r}") from exc
    return raw, parsed.date().isoformat(), parsed.strftime("%H:%M:%S")


def normalize_daily_unit(
    record: dict[str, Any],
    *,
    requested_discipline: str | None = None,
    source_language: str = "",
) -> dict[str, Any]:
    """Normalize one discipline daily unit without converting it to the 7-column DB row."""

    if not isinstance(record, dict):
        raise ResultsPayloadError("daily schedule unit is not an object")
    requested_code = (
        normalize_discipline_code(requested_discipline) if requested_discipline else ""
    )
    source_code = _text(record.get("Disc")).upper()
    discipline_code = source_code or requested_code
    if not discipline_code or not DISCIPLINE_CODE_RE.fullmatch(discipline_code):
        raise ResultsPayloadError(f"daily schedule unit has invalid Disc: {source_code!r}")
    if requested_code and source_code and requested_code != source_code:
        raise ResultsPayloadError(
            f"daily schedule discipline mismatch: requested={requested_code} actual={source_code}"
        )

    start_at, schedule_date, start_time = _normalized_start(record.get("DateTimeRaw"))
    is_head_to_head = record.get("isH2H") is True
    event_code = _text(record.get("Event"))
    is_team_event = "TEAM" in event_code.upper()
    home = _nested_competitor(record, "Home", use_team_org_name=is_team_event)
    away = _nested_competitor(record, "Away", use_team_org_name=is_team_event)
    competitors = {"home": home, "away": away} if is_head_to_head else None
    matchup = ""
    if is_head_to_head and home["display_name"] and away["display_name"]:
        matchup = f"{home['display_name']} vs {away['display_name']}"

    phase_name = _text(record.get("PhaseDesc"))
    phase_short_name = _text(record.get("PhaseDescS"))
    round_name = _text(record.get("PhaseDescA")) or phase_name
    session_name = _text(record.get("UnitDesc"))
    session_short_name = _text(record.get("UnitDescS"))
    session_label = _text(record.get("UnitDescA"))

    return {
        "source_language": source_language,
        "key": _text(record.get("Key")),
        "result_code": _text(record.get("ResCode")),
        "discipline_code": discipline_code,
        "discipline_name": _text(record.get("DiscDesc")),
        "start_at": start_at,
        "date": schedule_date,
        "time": start_time,
        "status": _text(record.get("Status")),
        "status_description": _text(record.get("StatusDesc")),
        "venue_code": _text(record.get("Venue")),
        "venue_name": _text(record.get("VenueDesc")),
        "venue_short_name": _text(record.get("VenueDescS")),
        "location_code": _text(record.get("Loc")),
        "location_name": _text(record.get("LocDesc")),
        "event_code": event_code,
        "event_name": _text(record.get("EventDesc")),
        "phase_code": _text(record.get("Phase")),
        "phase_name": phase_name,
        "phase_short_name": phase_short_name,
        "round_name": round_name,
        "session_name": session_name,
        "session_short_name": session_short_name,
        "session_label": session_label,
        "session_number": _text(record.get("UnitNum")),
        "is_phase": record.get("IsPhase") is True,
        "is_head_to_head": is_head_to_head,
        "is_team_event": is_team_event,
        "competition_kind": "head_to_head" if is_head_to_head else "session",
        "competitors": competitors,
        "matchup": matchup,
    }


def normalize_discipline_daily(
    payload: Any,
    *,
    requested_discipline: str | None = None,
    source_language: str = "",
) -> list[dict[str, Any]]:
    """Normalize every unit in one discipline daily response."""

    if not isinstance(payload, list):
        raise ResultsPayloadError("discipline daily JSON root must be a list")
    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(payload):
        try:
            normalized.append(
                normalize_daily_unit(
                    record,
                    requested_discipline=requested_discipline,
                    source_language=source_language,
                )
            )
        except ResultsPayloadError as exc:
            raise ResultsPayloadError(f"invalid daily schedule unit at index {index}: {exc}") from exc
    return normalized


def fetch_normalized_discipline_daily(
    discipline: str,
    target_date: date | datetime | str,
    *,
    language: str = RESULTS_DEFAULT_LANGUAGE,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch, expand, and normalize a discipline daily response."""

    code = normalize_discipline_code(discipline)
    language = normalize_results_language(language)
    payload = fetch_discipline_daily(code, target_date, language=language, **kwargs)
    return normalize_discipline_daily(
        payload,
        requested_discipline=code,
        source_language=language,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    matrix_parser = subparsers.add_parser("matrix")
    day_parser = subparsers.add_parser("day")
    day_parser.add_argument("date")
    daily_parser = subparsers.add_parser("daily")
    daily_parser.add_argument("discipline")
    daily_parser.add_argument("date")
    daily_parser.add_argument("--raw", action="store_true", help="print expanded source JSON")
    for command_parser in (matrix_parser, day_parser, daily_parser):
        command_parser.add_argument(
            "--language",
            choices=RESULTS_SUPPORTED_LANGUAGES,
            default=RESULTS_DEFAULT_LANGUAGE,
        )
    args = parser.parse_args()

    if args.command == "matrix":
        value = fetch_schedule_matrix(language=args.language)
    elif args.command == "day":
        value = fetch_day_schedule(args.date, language=args.language)
    elif args.raw:
        value = fetch_discipline_daily(
            args.discipline, args.date, language=args.language
        )
    else:
        value = fetch_normalized_discipline_daily(
            args.discipline, args.date, language=args.language
        )
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
