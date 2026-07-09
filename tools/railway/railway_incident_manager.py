"""Railway incident state manager for suppressing repeated Gemma notifications."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = ROOT / "data" / "railway" / "incidents" / "railway_incidents.json"

SEVERITY_RANK = {
    "": 0,
    "normal": 0,
    "info": 1,
    "warning": 2,
    "warn": 2,
    "delay_warning": 2,
    "critical": 3,
    "suspension": 3,
    "resolved": 0,
}
STATUS_RANK = {
    "": 0,
    "active": 1,
    "delay": 1,
    "warning": 2,
    "suspended": 3,
    "stopped": 3,
    "resolved": 0,
}
MEANINGLESS_PATTERNS = (
    re.compile(r"[0-9０-９]{1,2}時[0-9０-９]{1,2}分(?:頃)?"),
    re.compile(r"[0-9０-９]{1,3}\s*分(?:程度|ほど)?"),
    re.compile(r"最大(?:遅れ)?[0-9０-９]{1,3}分(?:程度|ほど)?"),
    re.compile(r"対象列車(?:数)?[：:\s]*[0-9０-９]+"),
)
REASON_KEYWORDS = (
    ("earthquake", ("地震",)),
    ("heavy_rain", ("雨規制", "大雨", "雨量", "降雨")),
    ("person_injury", ("人身事故",)),
    ("suspension", ("運転見合わせ", "運転を見合わせ")),
    ("vehicle_check", ("車両点検",)),
    ("track_check", ("線路点検", "設備点検", "安全確認")),
    ("power_failure", ("停電", "架線")),
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime | str | None = None) -> str:
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return current.isoformat(timespec="seconds")
    if value:
        return str(value)
    return utc_now().isoformat(timespec="seconds")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "incidents": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"railway_incident: state_load_failed path={path} error={type(exc).__name__}")
        return {"version": 1, "incidents": []}
    if not isinstance(data, dict):
        return {"version": 1, "incidents": []}
    incidents = data.get("incidents")
    if not isinstance(incidents, list):
        data["incidents"] = []
    data.setdefault("version", 1)
    return data


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)


@contextlib.contextmanager
def state_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            import fcntl  # type: ignore[import-not-found]

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            yield


def save_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(path, state)


def normalize_message(text: str) -> str:
    normalized = _text(text)
    normalized = normalized.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    for pattern in MEANINGLESS_PATTERNS:
        normalized = pattern.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def normalize_reason(event: dict[str, Any]) -> str:
    explicit = _text(event.get("reason"))
    text = explicit or _text(event.get("message") or event.get("alert"))
    for label, keywords in REASON_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return label
    return normalize_message(text)[:80] or "unknown"


def normalize_section(value: Any) -> str:
    section = _text(value)
    if not section:
        return "unknown"
    section = section.replace("駅", "")
    for separator in ("〜", "～", "-", "－", "―", "ー"):
        section = section.replace(separator, "-")
    return section


def incident_fingerprint(event: dict[str, Any]) -> str:
    parts = [
        _text(event.get("operator")) or "unknown_operator",
        _text(event.get("line")) or "unknown_line",
        normalize_reason(event),
        normalize_section(event.get("affected_section")),
    ]
    return "\x1f".join(parts)


def message_fingerprint(event: dict[str, Any]) -> str:
    text = normalize_message(_text(event.get("message") or event.get("alert")))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def terminal_risk_keys(risks: Any) -> set[str]:
    if not isinstance(risks, list):
        return set()
    keys: set[str] = set()
    for risk in risks:
        if not isinstance(risk, dict):
            continue
        key = "|".join(
            [
                _text(risk.get("train_name")),
                _text(risk.get("train_number")),
                _text(risk.get("risk_area")),
            ]
        )
        if key.strip("|"):
            keys.add(key)
    return keys


def severity_rank(value: Any) -> int:
    return SEVERITY_RANK.get(_text(value), 1 if _text(value) else 0)


def status_rank(value: Any) -> int:
    return STATUS_RANK.get(_text(value), 1 if _text(value) else 0)


def next_incident_id(state: dict[str, Any], event: dict[str, Any], fingerprint: str, now: datetime) -> str:
    operator = re.sub(r"[^a-z0-9]+", "_", _text(event.get("operator")).lower()).strip("_") or "operator"
    line = re.sub(r"[^a-z0-9]+", "_", _text(event.get("line")).lower()).strip("_") or "line"
    reason = re.sub(r"[^a-z0-9]+", "_", normalize_reason(event).lower()).strip("_") or "incident"
    date_key = now.strftime("%Y%m%d")
    count = 1
    for incident in state.get("incidents", []):
        if isinstance(incident, dict) and str(incident.get("incident_id", "")).startswith(f"{operator}_{line}_{date_key}_{reason}_"):
            count += 1
    return f"{operator}_{line}_{date_key}_{reason}_{count:03d}"


def find_open_incident(state: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    for incident in reversed(state.get("incidents", [])):
        if not isinstance(incident, dict):
            continue
        if incident.get("fingerprint") == fingerprint and incident.get("status") != "resolved":
            return incident
    return None


def event_from_alert(alert: str, *, now: datetime | None = None, position_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    line, body = split_alert(alert)
    event = {
        "operator": "JR Central" if "新幹線" in line or "JR東海" in line else "",
        "line": line or "鉄道運行情報",
        "status": "active",
        "reason": normalize_reason({"message": body}),
        "affected_section": extract_section(body),
        "message": body,
        "detected_at": iso_time(now),
    }
    if position_summary:
        event.update(
            {
                "max_delay_min": position_summary.get("max_delay_min", 0),
                "terminal_connection_risks": position_summary.get("terminal_connection_risks", []),
                "severity_alerts": position_summary.get("severity_alerts", []),
            }
        )
    return event


def split_alert(alert: str) -> tuple[str, str]:
    text = _text(alert)
    for separator in (":", "："):
        if separator in text:
            line, body = text.split(separator, 1)
            return line.strip(), body.strip()
    return text, text


def extract_section(text: str) -> str:
    match = re.search(r"([^\s、。]+(?:駅)?[〜～\-－―ー][^\s、。]+(?:駅)?)", text)
    return match.group(1) if match else ""


def build_incident_record(
    state: dict[str, Any],
    event: dict[str, Any],
    *,
    fingerprint: str,
    now: datetime,
) -> dict[str, Any]:
    incident_id = next_incident_id(state, event, fingerprint, now)
    return {
        "incident_id": incident_id,
        "fingerprint": fingerprint,
        "operator": _text(event.get("operator")),
        "line": _text(event.get("line")),
        "status": _text(event.get("status")) or "active",
        "reason": normalize_reason(event),
        "affected_section": normalize_section(event.get("affected_section")),
        "first_detected_at": iso_time(now),
        "last_seen_at": iso_time(now),
        "last_notified_at": "",
        "last_message_fingerprint": message_fingerprint(event),
        "severity": _text(event.get("severity")) or infer_severity(event),
        "max_delay_min": _int(event.get("max_delay_min")),
        "terminal_connection_risks": event.get("terminal_connection_risks") if isinstance(event.get("terminal_connection_risks"), list) else [],
        "notification_count": 0,
    }


def infer_severity(event: dict[str, Any]) -> str:
    if _int(event.get("max_delay_min")) >= 30 or event.get("severity_alerts"):
        return "warning"
    status = _text(event.get("status"))
    if status in {"suspended", "stopped"}:
        return "critical"
    if event.get("terminal_connection_risks"):
        return "warning"
    return _text(event.get("severity")) or "info"


def evaluate_change(incident: dict[str, Any], event: dict[str, Any]) -> tuple[bool, str]:
    new_status = _text(event.get("status")) or "active"
    old_status = _text(incident.get("status")) or "active"
    if new_status == "resolved" and old_status != "resolved":
        return True, "resolved"
    if status_rank(new_status) > status_rank(old_status):
        return True, "status_worsened"

    old_severity = _text(incident.get("severity"))
    new_severity = _text(event.get("severity")) or infer_severity(event)
    if severity_rank(new_severity) > severity_rank(old_severity):
        return True, "severity_increased"

    old_delay = _int(incident.get("max_delay_min"))
    new_delay = _int(event.get("max_delay_min"))
    if old_delay < 30 <= new_delay:
        return True, "severity_increased"

    old_risks = terminal_risk_keys(incident.get("terminal_connection_risks"))
    new_risks = terminal_risk_keys(event.get("terminal_connection_risks"))
    if new_risks - old_risks:
        return True, "terminal_connection_risk_started"

    old_section = normalize_section(incident.get("affected_section"))
    new_section = normalize_section(event.get("affected_section"))
    if old_section != "unknown" and new_section != "unknown" and old_section != new_section:
        return True, "affected_section_expanded"

    return False, "no_meaningful_change"


def update_incident(incident: dict[str, Any], event: dict[str, Any], *, now: datetime, notified: bool) -> None:
    incident["status"] = _text(event.get("status")) or incident.get("status") or "active"
    incident["reason"] = normalize_reason(event)
    incident["affected_section"] = normalize_section(event.get("affected_section")) or incident.get("affected_section", "")
    incident["last_seen_at"] = iso_time(now)
    incident["last_message_fingerprint"] = message_fingerprint(event)
    incident["severity"] = _text(event.get("severity")) or infer_severity(event)
    incident["max_delay_min"] = max(_int(incident.get("max_delay_min")), _int(event.get("max_delay_min")))
    if isinstance(event.get("terminal_connection_risks"), list):
        incident["terminal_connection_risks"] = event.get("terminal_connection_risks")
    if notified:
        incident["last_notified_at"] = iso_time(now)
        incident["notification_count"] = _int(incident.get("notification_count")) + 1


def evaluate_event(
    event: dict[str, Any],
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    fingerprint = incident_fingerprint(event)
    with state_lock(state_path):
        state = load_state(state_path)
        incident = find_open_incident(state, fingerprint)
        if incident is None:
            incident = build_incident_record(state, event, fingerprint=fingerprint, now=current)
            state.setdefault("incidents", []).append(incident)
            should_notify = True
            reason = "created"
        else:
            should_notify, reason = evaluate_change(incident, event)
        update_incident(incident, event, now=current, notified=should_notify)
        save_state(state_path, state)

    if should_notify and reason == "created":
        print(f"railway_incident: created incident_id={incident['incident_id']}")
    elif should_notify and reason == "resolved":
        print(f"railway_incident: resolved incident_id={incident['incident_id']}")
    elif should_notify:
        print(f"railway_incident: notify incident_id={incident['incident_id']} reason={reason}")
    else:
        print(f"railway_incident: suppressed incident_id={incident['incident_id']} reason={reason}")
    return {
        "incident_id": incident["incident_id"],
        "should_notify": should_notify,
        "reason": reason,
        "incident": dict(incident),
    }
