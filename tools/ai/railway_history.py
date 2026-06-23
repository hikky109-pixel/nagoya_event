#!/usr/bin/env python3
"""鉄道ベータインシデント履歴をYAMLで保存する。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from railway_line_normalizer import normalize_line_name
    from railway_severity import detect_railway_severity
except ModuleNotFoundError:
    from tools.ai.railway_line_normalizer import normalize_line_name
    from tools.ai.railway_severity import detect_railway_severity


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def line_from_alert(alert: str) -> str:
    return normalize_line_name(alert)


def body_from_alert(alert: str) -> str:
    for separator in (":", "："):
        if separator in alert:
            return clean_text(alert.split(separator, 1)[1])
    return clean_text(alert)


def reason_label(alert: str) -> str:
    text = body_from_alert(alert)
    labels = (
        ("人立入り", ("人が立ち入った", "人立入り")),
        ("折り返し列車遅れ", ("折り返し列車の遅れ",)),
        ("車両点検", ("車両点検",)),
        ("踏切安全確認", ("踏切安全確認",)),
        ("線路点検", ("線路点検",)),
        ("信号確認", ("信号確認",)),
        ("架線点検", ("架線点検",)),
        ("運転見合わせ", ("運転見合わせ",)),
        ("運休", ("運休",)),
        ("再開見込みなし", ("再開見込みなし",)),
        ("再開見込み未定", ("再開見込み未定",)),
    )
    for label, keywords in labels:
        if any(keyword in text for keyword in keywords):
            return label
    return text


def alerts_by_line(alerts: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for alert in alerts:
        text = clean_text(alert)
        if not text:
            continue
        line = line_from_alert(text)
        grouped.setdefault(line, [])
        if text not in grouped[line]:
            grouped[line].append(text)
    return grouped


def load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return load_history_simple(path)

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data if isinstance(data, list) else []


def load_history_simple(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_reasons = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- line:"):
            current = {"line": unquote_yaml(stripped.split(":", 1)[1].strip()), "reasons": []}
            records.append(current)
            in_reasons = False
            continue
        if current is None:
            continue
        if stripped == "reasons:":
            in_reasons = True
            current.setdefault("reasons", [])
            continue
        if in_reasons and stripped.startswith("- "):
            current.setdefault("reasons", []).append(unquote_yaml(stripped[2:].strip()))
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = parse_yaml_scalar(value.strip())
            in_reasons = False
    return records


def parse_yaml_scalar(value: str) -> Any:
    if value in ("null", "~", ""):
        return None
    if value.isdigit():
        return int(value)
    return unquote_yaml(value)


def unquote_yaml(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"')
    return value


def quote_yaml(value: Any) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_history(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for record in records:
        lines.append(f"- line: {quote_yaml(normalize_line_name(str(record.get('line') or '')))}")
        lines.append(f"  severity: {quote_yaml(record.get('severity'))}")
        lines.append(f"  started_at: {quote_yaml(record.get('started_at'))}")
        recovered_at = record.get("recovered_at")
        if recovered_at:
            lines.append(f"  recovered_at: {quote_yaml(recovered_at)}")
        else:
            lines.append("  recovered_at: null")
        duration = record.get("duration_minutes")
        lines.append(f"  duration_minutes: {duration if isinstance(duration, int) else 'null'}")
        lines.append("  reasons:")
        for reason in record.get("reasons") or []:
            lines.append(f"    - {quote_yaml(reason)}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def open_record(records: list[dict[str, Any]], line: str) -> dict[str, Any] | None:
    for record in reversed(records):
        if record.get("line") == line and not record.get("recovered_at"):
            return record
    return None


def merge_reasons(existing: list[Any], alerts: list[str]) -> list[str]:
    reasons = [clean_text(reason) for reason in existing if clean_text(reason)]
    for alert in alerts:
        reason = reason_label(alert)
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def update_open_incidents(records: list[dict[str, Any]], current_alerts: list[str], now: datetime) -> None:
    for line, alerts in alerts_by_line(current_alerts).items():
        record = open_record(records, line)
        severity = detect_railway_severity(alerts)
        if record is None:
            records.append(
                {
                    "line": line,
                    "severity": severity,
                    "started_at": now.isoformat(timespec="seconds"),
                    "recovered_at": None,
                    "duration_minutes": None,
                    "reasons": merge_reasons([], alerts),
                }
            )
            continue
        record["severity"] = detect_railway_severity([*record.get("reasons", []), *alerts])
        record["reasons"] = merge_reasons(record.get("reasons", []), alerts)


def close_open_incidents(records: list[dict[str, Any]], previous_alerts: list[str], now: datetime) -> None:
    lines = alerts_by_line(previous_alerts)
    for line, alerts in lines.items():
        record = open_record(records, line)
        if record is None:
            started_at = now.isoformat(timespec="seconds")
            record = {
                "line": line,
                "severity": detect_railway_severity(alerts),
                "started_at": started_at,
                "recovered_at": None,
                "duration_minutes": None,
                "reasons": merge_reasons([], alerts),
            }
            records.append(record)
        record["recovered_at"] = now.isoformat(timespec="seconds")
        started = datetime.fromisoformat(str(record.get("started_at")))
        record["duration_minutes"] = max(0, int((now - started).total_seconds() // 60))
        record["reasons"] = merge_reasons(record.get("reasons", []), alerts)


def record_railway_history_change(
    path: Path,
    previous_alerts: list[str],
    current_alerts: list[str],
    change_type: str,
    now: datetime,
) -> None:
    if change_type == "skipped_overnight":
        return
    records = load_history(path)
    if change_type == "recovered":
        close_open_incidents(records, previous_alerts, now)
    elif change_type in ("initial", "changed"):
        if change_type == "changed":
            previous_lines = alerts_by_line(previous_alerts)
            current_lines = alerts_by_line(current_alerts)
            recovered_alerts: list[str] = []
            for line, alerts in previous_lines.items():
                if line not in current_lines:
                    recovered_alerts.extend(alerts)
            if recovered_alerts:
                close_open_incidents(records, recovered_alerts, now)
        update_open_incidents(records, current_alerts, now)
    else:
        return
    save_history(path, records)
