#!/usr/bin/env python3
"""Semantic notification filters for JR Central railway updates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SHINKANSEN_PREFIX = "東海道新幹線"
ZAIRAI_PREFIX = "JR東海在来線 "
SHINKANSEN_TICKET_MARKERS = (
    "きっぷ",
    "切符",
    "払いもどし",
    "払戻",
    "払い戻し",
)
SHINKANSEN_PLAN_MARKERS = ("計画運休", "運転計画")
SHINKANSEN_RESUME_MARKERS = (
    "運転再開のお知らせ",
    "運転を再開しました",
    "運転を再開しています",
    "運転を再開",
)
SHINKANSEN_LOW_VALUE_MARKERS = {
    "rain_amount_update": (
        "過去１時間の雨量",
        "過去1時間の雨量",
        "過去２４時間の雨量",
        "過去24時間の雨量",
    ),
    "inspection_update": (
        "点検中",
        "設備点検",
        "安全確認",
        "確認作業",
    ),
    "crew_arrived": ("係員は現地に到着", "係員が現地に到着"),
    "progress_update": ("順調に進んでいます", "順調に進行"),
}
SANYO_ONLY_MARKERS = (
    "山陽新幹線",
    "徳山駅",
    "新山口駅",
    "新岩国駅",
    "広島駅",
    "博多駅",
)
TOKAIDO_IMPACT_MARKERS = (
    "東海道新幹線",
    "東京駅～新大阪駅",
    "東京～新大阪",
    "山陽新幹線から直通する上り",
    "東海道新幹線の上り",
)
RESTART_PATTERN = re.compile(
    r"運転再開(?:見込み)?(?:時刻)?(?:は|を)?[、：:\s]*"
    r"([0-9０-９]{1,2})時([0-9０-９]{1,2})分頃"
)

ZAIRAI_STATUS_RANK = {
    "0009": 0,
    "0006": 1,
    "0011": 1,
    "0005": 2,
    "0007": 2,
    "0008": 2,
    "0010": 2,
    "0001": 3,
    "0002": 3,
    "0003": 3,
    "0004": 3,
}
LOW_IMPACT_MARKERS = (
    "動物衝突",
    "動物が列車に衝突",
    "動物と衝突",
    "折り返し列車の遅れ",
    "車両点検",
    "非常ボタン",
    "踏切安全確認",
    "踏切内で障害物",
)
MAJOR_INCIDENT_MARKERS = (
    "運転見合わせ",
    "運転を見合わせ",
    "抑止",
    "人身事故",
    "長時間運休",
    "重大障害",
    "広範囲",
    "孤立",
    "代替困難",
    "タクシー需要",
)
LIMITED_EXPRESS_LOW_IMPACT_NAMES = ("しなの", "しらさぎ")
MAX_DELAY_PATTERN = re.compile(
    r"(?:最大(?:遅れ)?|最大で|最大)\s*([0-9０-９]{1,3})\s*分(?:程度|ほど)?"
)


def _body(alert: str) -> str:
    text = " ".join(str(alert or "").split())
    for separator in (":", "："):
        if separator in text:
            return text.split(separator, 1)[1].strip()
    return text


def _to_ascii_digits(value: str) -> str:
    return value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _restart_minutes(text: str) -> int | None:
    match = RESTART_PATTERN.search(text)
    if not match:
        return None
    hour = int(_to_ascii_digits(match.group(1)))
    minute = int(_to_ascii_digits(match.group(2)))
    return hour * 60 + minute


def _max_delay_minutes(text: str) -> int | None:
    normalized = _to_ascii_digits(text)
    match = MAX_DELAY_PATTERN.search(normalized)
    if not match:
        return None
    return int(match.group(1))


def has_major_railway_incident(alerts: list[str]) -> bool:
    texts = [" ".join(str(alert or "").split()) for alert in alerts]
    return any(marker in text for text in texts for marker in MAJOR_INCIDENT_MARKERS)


def is_low_impact_railway_alert(alert: str) -> bool:
    text = " ".join(str(alert or "").split())
    if not text or has_major_railway_incident([text]):
        return False
    if any(marker in text for marker in LOW_IMPACT_MARKERS):
        return True
    if _max_delay_minutes(text) is not None and _max_delay_minutes(text) <= 10:
        return True
    if (
        any(name in text for name in LIMITED_EXPRESS_LOW_IMPACT_NAMES)
        and "遅れ" in text
        and not any(marker in text for marker in ("運休", "見合わせ", "人身事故"))
    ):
        return True
    return False


def is_low_impact_railway_alerts(alerts: list[str]) -> bool:
    cleaned = [" ".join(str(alert or "").split()) for alert in alerts if str(alert or "").strip()]
    if not cleaned or has_major_railway_incident(cleaned):
        return False
    return all(is_low_impact_railway_alert(alert) for alert in cleaned)


def classify_railway_pre_llm_notification(
    *,
    previous_alerts: list[str],
    current_alerts: list[str],
    previous_official_hash: str = "",
    current_official_hash: str = "",
    previous_impact: str = "",
) -> tuple[bool, str]:
    previous_clean = [" ".join(str(alert or "").split()) for alert in previous_alerts if str(alert or "").strip()]
    current_clean = [" ".join(str(alert or "").split()) for alert in current_alerts if str(alert or "").strip()]
    if current_clean and previous_official_hash and previous_official_hash == current_official_hash:
        return False, "no_official_change"
    if current_clean and not has_major_railway_incident(current_clean):
        return False, "low_impact"
    if current_clean and has_major_railway_incident(current_clean):
        return True, "major_incident"
    if previous_clean and not current_clean:
        if previous_impact == "low_impact" or is_low_impact_railway_alerts(previous_clean):
            return False, "recovered_silent"
        return True, "major_recovered"
    return False, "no_actionable_railway_alert"


def parse_shinkansen_alert(alert: str) -> dict[str, Any]:
    body = _body(alert)
    ticket_only = any(marker in body for marker in SHINKANSEN_TICKET_MARKERS)
    resumed = any(marker in body for marker in SHINKANSEN_RESUME_MARKERS)
    stopped = any(
        marker in body for marker in ("運転見合わせ", "運転を見合わせ")
    ) and not resumed
    restart_mentioned = "運転再開見込み" in body
    explicit_tokaido = any(marker in body for marker in TOKAIDO_IMPACT_MARKERS)
    sanyo_only = any(marker in body for marker in SANYO_ONLY_MARKERS)
    affects_tokaido = bool(body) and (explicit_tokaido or not sanyo_only)
    return {
        "body": body,
        "ticket_only": ticket_only,
        "planned_suspension": any(marker in body for marker in SHINKANSEN_PLAN_MARKERS),
        "stopped": stopped,
        "resumed": resumed,
        "restart_mentioned": restart_mentioned,
        "restart_minutes": _restart_minutes(body),
        "restart_unknown": restart_mentioned and any(
            marker in body for marker in ("未定", "分かり次第", "決まり次第")
        ),
        "affects_tokaido": affects_tokaido,
    }


def classify_shinkansen_change(
    previous_alert: str | None,
    current_alert: str,
) -> tuple[bool, str]:
    current = parse_shinkansen_alert(current_alert)
    previous = parse_shinkansen_alert(previous_alert or "")

    if current["ticket_only"] and not current["planned_suspension"]:
        return False, "ticket_or_refund_update"
    if current["planned_suspension"] and not previous["planned_suspension"]:
        return True, "planned_suspension"
    if current["stopped"] and not previous["stopped"]:
        return True, "new_suspension"
    if current["affects_tokaido"] and not previous["affects_tokaido"]:
        return True, "tokaido_impact_started"
    if current["restart_mentioned"] and not previous["restart_mentioned"]:
        return True, "restart_estimate_first"
    if current["resumed"] and not previous["resumed"]:
        return True, "service_resumed"

    previous_minutes = previous["restart_minutes"]
    current_minutes = current["restart_minutes"]
    if previous["restart_mentioned"] and current["restart_mentioned"]:
        if previous_minutes is not None and current_minutes is not None:
            if abs(current_minutes - previous_minutes) >= 30:
                return True, "restart_estimate_major_change"
        elif previous["restart_unknown"] != current["restart_unknown"]:
            return True, "restart_estimate_major_change"

    current_body = current["body"]
    previous_body = previous["body"]
    for reason, markers in SHINKANSEN_LOW_VALUE_MARKERS.items():
        if current_body != previous_body and any(marker in current_body for marker in markers):
            return False, reason
    return False, "remark_only_update"


def _structured_by_alert(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(event.get("alert") or ""): event
        for event in events
        if str(event.get("alert") or "")
    }


def _structured_by_key(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(event.get("incident_key") or ""): event
        for event in events
        if str(event.get("incident_key") or "")
    }


def classify_zairai_change(
    alert: str,
    previous_events: list[dict[str, Any]],
    current_events: list[dict[str, Any]],
) -> tuple[bool, str]:
    current = _structured_by_alert(current_events).get(alert)
    if current is None:
        return True, "structured_event_missing_fallback"

    previous = _structured_by_key(previous_events).get(str(current.get("incident_key") or ""))
    current_rank = ZAIRAI_STATUS_RANK.get(str(current.get("status_id") or ""), 1)
    if previous is None:
        return current_rank > 0, "new_abnormal_incident" if current_rank > 0 else "normal_incident"

    previous_rank = ZAIRAI_STATUS_RANK.get(str(previous.get("status_id") or ""), 1)
    if current_rank > previous_rank:
        return True, "status_worsened"
    if not str(previous.get("prospect_time") or "") and str(current.get("prospect_time") or ""):
        return True, "prospect_time_first"
    if str(current.get("resume_time") or "") and (
        str(current.get("resume_time") or "") != str(previous.get("resume_time") or "")
    ):
        return True, "resume_time_set"
    if bool(current.get("trans_info_started")) and not bool(previous.get("trans_info_started")):
        return True, "trans_info_started"
    if str(current.get("message") or "") != str(previous.get("message") or ""):
        return False, "delivery_message_only"
    if str(current.get("recover_message") or "") != str(previous.get("recover_message") or ""):
        return False, "recover_message_only"
    if bool(current.get("has_supplement_info")) != bool(previous.get("has_supplement_info")):
        return False, "supplement_info_only"
    return False, "structured_no_important_change"


def filter_added_railway_alerts(
    added_alerts: list[str],
    previous_alerts: list[str],
    previous_zairai_events: list[dict[str, Any]] | None = None,
    current_zairai_events: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    previous_zairai_events = previous_zairai_events or []
    current_zairai_events = current_zairai_events or []
    previous_shinkansen = next(
        (alert for alert in previous_alerts if alert.startswith(f"{SHINKANSEN_PREFIX}:")),
        None,
    )
    kept: list[str] = []
    decisions: list[dict[str, Any]] = []

    for alert in added_alerts:
        notify = True
        reason = "default_notify"
        source = "other"
        if alert.startswith(f"{SHINKANSEN_PREFIX}:"):
            source = "shinkansen"
            notify, reason = classify_shinkansen_change(previous_shinkansen, alert)
        elif alert.startswith(ZAIRAI_PREFIX):
            source = "zairai"
            notify, reason = classify_zairai_change(
                alert,
                previous_zairai_events,
                current_zairai_events,
            )
        if notify:
            kept.append(alert)
        decisions.append(
            {
                "source": source,
                "notify": notify,
                "reason": reason,
                "alert": alert,
            }
        )
    return kept, decisions


def load_structured_filter_state(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    events = data.get("events") if isinstance(data, dict) else None
    return events if isinstance(events, list) else []


def save_structured_filter_state(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"events": events}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
