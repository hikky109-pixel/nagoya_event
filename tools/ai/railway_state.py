#!/usr/bin/env python3
"""鉄道ベータ通知の前回状態を読み書きする。"""

from __future__ import annotations

import json
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any


RAILWAY_COOLDOWN_SECONDS = {
    "info": 30 * 60,
    "warning": 15 * 60,
    "critical": 5 * 60,
}
RAILWAY_INCIDENT_IGNORE_PATTERNS: tuple[str, ...] = ()
CRITICAL_TRANSPORT_PREFIXES = (
    "JR東海在来線",
    "名鉄",
    "名古屋市営地下鉄",
)
CRITICAL_TRANSPORT_STABLE_SECONDS = 30 * 60


def clean_alerts(
    alerts: list[str],
    ignore_patterns: tuple[str, ...] = RAILWAY_INCIDENT_IGNORE_PATTERNS,
) -> list[str]:
    cleaned: list[str] = []
    for alert in alerts:
        text = " ".join(str(alert or "").split())
        if any(pattern in text for pattern in ignore_patterns):
            continue
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def split_alert(alert: str) -> tuple[str, str]:
    text = " ".join(str(alert or "").split())
    for separator in (":", "："):
        if separator in text:
            line, incident = text.split(separator, 1)
            return line.strip(), incident.strip()
    return text, text


def incidents_by_line(
    alerts: list[str],
    ignore_patterns: tuple[str, ...] = RAILWAY_INCIDENT_IGNORE_PATTERNS,
) -> dict[str, list[str]]:
    incidents: dict[str, list[str]] = {}
    for alert in clean_alerts(alerts, ignore_patterns):
        line, incident = split_alert(alert)
        if not line or not incident:
            continue
        incidents.setdefault(line, [])
        if incident not in incidents[line]:
            incidents[line].append(incident)
    return incidents


def load_railway_state(path: Path) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, []

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False, []

    if not isinstance(data, dict):
        return False, []

    alerts = data.get("alerts")
    if not isinstance(alerts, list):
        return True, []

    return True, clean_alerts(alerts)


def load_railway_state_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "morning_reposted_date": str(data.get("morning_reposted_date") or ""),
        "critical_transport_recovered_at": str(
            data.get("critical_transport_recovered_at") or ""
        ),
        "official_hash": str(data.get("official_hash") or ""),
        "impact": str(data.get("impact") or ""),
        "shinkansen_no_official_change_override_hash": str(
            data.get("shinkansen_no_official_change_override_hash") or ""
        ),
    }


def is_critical_transport_alert(alert: str) -> bool:
    line, _incident = split_alert(alert)
    return any(
        line == prefix or line.startswith(f"{prefix} ")
        for prefix in CRITICAL_TRANSPORT_PREFIXES
    )


def critical_transport_alerts(alerts: list[str]) -> list[str]:
    return [alert for alert in clean_alerts(alerts) if is_critical_transport_alert(alert)]


def critical_transport_recovery_still_stable(
    recovered_at: str,
    now: datetime,
) -> bool:
    recovered = parse_datetime(recovered_at)
    if recovered is None:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    recovered_local = recovered.astimezone(now.tzinfo)
    return 0 <= (now - recovered_local).total_seconds() < CRITICAL_TRANSPORT_STABLE_SECONDS


def critical_transport_overnight_monitoring_active(
    *,
    now: datetime,
    previous_alerts: list[str],
    critical_transport_recovered_at: str = "",
) -> tuple[bool, str]:
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    current_time = current.timetz().replace(tzinfo=None)
    if current_time >= time(5, 0) or current_time < time(1, 0):
        return True, "normal_hours"
    if critical_transport_alerts(previous_alerts):
        return True, "critical_transport_incident_continuing"
    if critical_transport_recovery_still_stable(critical_transport_recovered_at, current):
        return True, "critical_transport_recovery_stabilizing"
    return False, "overnight_no_critical_transport_incident"


def load_railway_incident_first_seen(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw_first_seen = data.get("incident_first_seen_at")
    if not isinstance(raw_first_seen, dict):
        return {}
    first_seen: dict[str, str] = {}
    for alert, first_seen_at in raw_first_seen.items():
        cleaned = clean_alerts([str(alert)])
        if cleaned and parse_datetime(first_seen_at) is not None:
            first_seen[cleaned[0]] = str(first_seen_at)
    return first_seen


def update_railway_incident_first_seen(
    current_alerts: list[str],
    existing_first_seen: dict[str, str],
    now: datetime,
) -> dict[str, str]:
    now_text = now.isoformat(timespec="seconds")
    updated: dict[str, str] = {}
    for alert in clean_alerts(current_alerts):
        existing = existing_first_seen.get(alert)
        updated[alert] = existing if parse_datetime(existing) is not None else now_text
    return updated


def save_railway_state(
    path: Path,
    alerts: list[str],
    updated_at: datetime | str,
    level_by_alert: dict[str, str] | None = None,
    morning_reposted_date: str = "",
    incident_first_seen_at: dict[str, str] | None = None,
    critical_transport_recovered_at: str = "",
    official_hash: str = "",
    impact: str = "",
    shinkansen_no_official_change_override_hash: str = "",
) -> None:
    if isinstance(updated_at, datetime):
        updated_at_text = updated_at.isoformat(timespec="seconds")
    else:
        updated_at_text = str(updated_at)
    if not shinkansen_no_official_change_override_hash and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if isinstance(existing, dict):
            shinkansen_no_official_change_override_hash = str(
                existing.get("shinkansen_no_official_change_override_hash") or ""
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_alerts = clean_alerts(alerts)
    state: dict[str, Any] = {
        "updated_at": updated_at_text,
        "alerts": cleaned_alerts,
        "incidents": incidents_by_line(cleaned_alerts),
        "levels": {
            alert: str(level_by_alert[alert])
            for alert in cleaned_alerts
            if level_by_alert and level_by_alert.get(alert)
        },
        "morning_reposted_date": str(morning_reposted_date or ""),
        "critical_transport_recovered_at": str(critical_transport_recovered_at or ""),
        "official_hash": str(official_hash or ""),
        "impact": str(impact or ""),
        "shinkansen_no_official_change_override_hash": str(
            shinkansen_no_official_change_override_hash or ""
        ),
        "incident_first_seen_at": {
            alert: str(incident_first_seen_at[alert])
            for alert in cleaned_alerts
            if incident_first_seen_at
            and parse_datetime(incident_first_seen_at.get(alert)) is not None
        },
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def morning_carryover_repost_candidates(
    *,
    previous_alerts: list[str],
    current_alerts: list[str],
    now: datetime,
    morning_reposted_date: str,
    incident_first_seen_at: dict[str, str] | None = None,
    last_notify: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    local_now = now.astimezone(now.tzinfo) if now.tzinfo else now
    today = local_now.date().isoformat()
    if not (5 <= local_now.hour < 6):
        return [], "outside_morning_window"
    if morning_reposted_date == today:
        return [], "already_reposted_today"
    previous_clean = clean_alerts(previous_alerts)
    current_clean = clean_alerts(current_alerts)
    if not current_clean:
        return [], "no_current_abnormal_alerts"
    previous_set = set(previous_clean)
    continuing_alerts = [
        alert for alert in current_clean if alert in previous_set
    ]
    if not continuing_alerts:
        return [], "no_continuing_incident"

    last_sent_at = (last_notify or {}).get("last_sent_at")
    if isinstance(last_sent_at, datetime):
        if last_sent_at.tzinfo is None:
            last_sent_at = last_sent_at.replace(tzinfo=timezone.utc)
        last_sent_local = last_sent_at.astimezone(local_now.tzinfo)
        if (
            last_sent_local.date() == local_now.date()
            and last_sent_local.hour >= 5
            and (local_now - last_sent_local).total_seconds() < 60 * 15
        ):
            return [], "recent_normal_notification"

    quiet_hours_end = local_now.replace(hour=5, minute=0, second=0, microsecond=0)
    eligible_alerts: list[str] = []
    for alert in continuing_alerts:
        first_seen = parse_datetime((incident_first_seen_at or {}).get(alert))
        if first_seen is None:
            continue
        first_seen_local = first_seen.astimezone(local_now.tzinfo)
        if first_seen_local < quiet_hours_end:
            eligible_alerts.append(alert)
    if not eligible_alerts:
        return [], "incident_started_after_quiet_hours"
    return eligible_alerts, "continuing_from_before_quiet_hours"


def morning_carryover_repost_allowed(
    *,
    previous_alerts: list[str],
    current_alerts: list[str],
    now: datetime,
    morning_reposted_date: str,
    incident_first_seen_at: dict[str, str] | None = None,
    last_notify: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    candidates, reason = morning_carryover_repost_candidates(
        previous_alerts=previous_alerts,
        current_alerts=current_alerts,
        now=now,
        morning_reposted_date=morning_reposted_date,
        incident_first_seen_at=incident_first_seen_at,
        last_notify=last_notify,
    )
    return bool(candidates), reason


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def load_railway_last_notify(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    last_sent_at = parse_datetime(data.get("last_sent_at"))
    severity = str(data.get("severity") or "").strip()
    result: dict[str, Any] = {}
    if last_sent_at is not None:
        result["last_sent_at"] = last_sent_at
    if severity:
        result["severity"] = severity
    return result


def save_railway_last_notify(path: Path, severity: str, sent_at: datetime | str) -> None:
    if isinstance(sent_at, datetime):
        sent_at_text = sent_at.isoformat(timespec="seconds")
    else:
        sent_at_text = str(sent_at)

    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_sent_at": sent_at_text,
        "severity": severity,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def railway_notify_allowed(
    last_notify: dict[str, Any],
    severity: str,
    now: datetime,
    change_type: str,
) -> tuple[bool, int]:
    if change_type != "unchanged":
        return True, 0

    cooldown_seconds = RAILWAY_COOLDOWN_SECONDS.get(severity, RAILWAY_COOLDOWN_SECONDS["info"])
    last_sent_at = last_notify.get("last_sent_at")

    if not isinstance(last_sent_at, datetime):
        return True, 0

    elapsed_seconds = int((now - last_sent_at.astimezone(now.tzinfo)).total_seconds())
    remaining_seconds = cooldown_seconds - elapsed_seconds
    if remaining_seconds > 0:
        return False, remaining_seconds
    return True, 0


def diff_alerts(
    previous: list[str],
    current: list[str],
    ignore_patterns: tuple[str, ...] = RAILWAY_INCIDENT_IGNORE_PATTERNS,
) -> tuple[list[str], list[str]]:
    previous_clean = clean_alerts(previous, ignore_patterns)
    current_clean = clean_alerts(current, ignore_patterns)
    previous_incidents = incidents_by_line(previous_clean, ignore_patterns)
    current_incidents = incidents_by_line(current_clean, ignore_patterns)

    added = []
    for alert in current_clean:
        line, incident = split_alert(alert)
        if incident not in previous_incidents.get(line, []):
            added.append(alert)

    removed = []
    for alert in previous_clean:
        line, incident = split_alert(alert)
        if incident not in current_incidents.get(line, []):
            removed.append(alert)
    return added, removed
