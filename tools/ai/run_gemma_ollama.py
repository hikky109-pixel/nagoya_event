#!/usr/bin/env python3
"""Ollama上のGemma 4Bでジェンマ課長コメントを生成する。"""

from __future__ import annotations

import json
import hashlib
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

try:
    from jrc_zairai_targets import jrc_target_line_display, jrc_target_line_url
    from get_jrc_shinkansen_plan_notice import get_jrc_shinkansen_plan_notice
    from log_utils import log
    from railway_filters import (
        classify_railway_pre_llm_notification,
        filter_added_railway_alerts,
        has_major_railway_incident,
        load_structured_filter_state,
        save_structured_filter_state,
    )
    from railway_history import record_railway_history_change
    from railway_status_normalizer import (
        get_all_railway_alerts_snapshot,
        get_last_jrc_zairai_structured_events,
    )
    from railway_severity import detect_railway_severity
    from weather_severity import detect_weather_severity, is_minor_weather
    from railway_state import (
        critical_transport_alerts,
        critical_transport_overnight_monitoring_active,
        diff_alerts,
        load_railway_incident_first_seen,
        load_railway_last_notify,
        load_railway_state,
        load_railway_state_metadata,
        morning_carryover_repost_candidates,
        railway_notify_allowed,
        save_railway_last_notify,
        save_railway_state,
        update_railway_incident_first_seen,
    )
except ModuleNotFoundError:
    from tools.ai.jrc_zairai_targets import jrc_target_line_display, jrc_target_line_url
    from tools.ai.get_jrc_shinkansen_plan_notice import get_jrc_shinkansen_plan_notice
    from tools.ai.log_utils import log
    from tools.ai.railway_filters import (
        classify_railway_pre_llm_notification,
        filter_added_railway_alerts,
        has_major_railway_incident,
        load_structured_filter_state,
        save_structured_filter_state,
    )
    from tools.ai.railway_history import record_railway_history_change
    from tools.ai.railway_status_normalizer import (
        get_all_railway_alerts_snapshot,
        get_last_jrc_zairai_structured_events,
    )
    from tools.ai.railway_severity import detect_railway_severity
    from tools.ai.weather_severity import detect_weather_severity, is_minor_weather
    from tools.ai.railway_state import (
        critical_transport_alerts,
        critical_transport_overnight_monitoring_active,
        diff_alerts,
        load_railway_incident_first_seen,
        load_railway_last_notify,
        load_railway_state,
        load_railway_state_metadata,
        morning_carryover_repost_candidates,
        railway_notify_allowed,
        save_railway_last_notify,
        save_railway_state,
        update_railway_incident_first_seen,
    )

try:
    from tools.weather.weather_normalizer import get_all_weather_alerts, get_all_weather_snapshot
except ModuleNotFoundError:
    from weather_normalizer import get_all_weather_alerts, get_all_weather_snapshot


AI_DIR = ROOT / "data" / "ai"
REPORT_PATH = AI_DIR / "gemma_report.txt"
PROFILE_PATH = AI_DIR / "gemma_profile.yml"
STYLE_PATH = ROOT / "config" / "gemma_style.yml"
TEXT_OUTPUT_PATH = AI_DIR / "gemma_comment.txt"
JSON_OUTPUT_PATH = AI_DIR / "gemma_comment.json"
RAILWAY_STATE_PATH = AI_DIR / "railway_beta_state.json"
RAILWAY_LAST_NOTIFY_PATH = AI_DIR / "railway_beta_last_notify.json"
WEATHER_STATE_PATH = AI_DIR / "weather_state.json"
WEATHER_DEBUG_DIR = ROOT / "data" / "debug" / "weather"
RAILWAY_HISTORY_PATH = AI_DIR / "railway_history.yml"
RAILWAY_ZAIRAI_FILTER_STATE_PATH = AI_DIR / "railway_zairai_filter_state.json"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = config.OLLAMA_MODEL
RAILWAY_BETA_EXCLUDE_MARKERS = (
    "取得失敗",
    "運行情報提供停止",
)
AONAMI_DEMAND_REASON = "金城ふ頭方面は代替交通が少ない"
IMPORTANT_ACTIVE_TARGET_MARKERS = (
    "shinkansen",
    "新幹線",
    "東海道新幹線",
    "山陽新幹線",
    "JR東海在来線",
    "中央線",
    "関西線",
    "東海道線",
    "武豊線",
    "飯田線",
    "名鉄",
    "地下鉄",
    "近鉄",
)
IMPORTANT_ACTIVE_AREA_MARKERS = (
    "名古屋",
    "名古屋駅",
    "名古屋駅～八田駅",
    "名古屋市内",
    "八田",
    "東京",
    "新大阪",
    "静岡",
    "京都",
    "新横浜",
    "三河安城",
    "豊橋",
    "岐阜羽島",
    "米原",
)
IMPORTANT_ACTIVE_INCIDENT_MARKERS = (
    "遅れ",
    "遅延",
    "急病",
    "救護",
    "車内確認",
    "安全確認",
    "車両点検",
)
RAILWAY_BETA_FORBIDDEN_OUTPUTS = (
    "おはようございます",
    "本日も",
    "状況を確認しました",
    "報告ありがとうございます",
    "〇〇さん",
    "皆さん",
    "引き続き",
    "慎重に進めましょう",
    "判断しましょう",
    "支障をきたす",
    "確認されました",
    "情報収集",
    "影響範囲",
    "モニタリング",
    "継続します",
    "発生。",
    "状況把握",
    "引き続き注視",
    "名古屋方面の移動・乗換に影響する可能性があります。",
    "名古屋方面の移動に大きな影響が予想されます。",
    "確認します",
    "調査中です",
    "少し考えています",
    "最新情報にご留意ください",
    "交通情報ベータより取得",
    "交通情報ベータに基づいています",
    "公式サイトをご確認ください",
    "詳細は未確認です",
    "ジェンマ課長日報",
)
RAILWAY_SEVERITY_EMOJIS = {
    "info": "🔵",
    "warning": "🟡",
    "critical": "🔴",
}
COMMENT_SIGNAL_KEYWORDS = (
    "インシデント",
    "障害",
    "事故",
    "通行止",
    "交通規制",
    "規制",
    "渋滞",
    "オービス",
    "名駅繁忙",
    "繁忙",
    "入構",
    "大型イベント",
    "需要",
    "IGアリーナ",
    "バンテリン",
    "御園座",
    "ドラゴンズ関連ログ",
    "道路交通案件",
)
COMMENT_NO_SIGNAL_MARKERS = (
    "新規情報なし",
    "特記事項なし",
    "特記事項はありません",
    "本日も安定稼働",
    "安定稼働です",
    "引き続き見守ります",
    "見守ります",
    "大きな変化は未確認",
    "平常運転",
    "状況を把握",
    "モニタリング",
    "現時点で特別な影響",
    "影響は確認されていません",
)
COMMENT_ZERO_EVENT_PATTERNS = (
    r"イベント\s*(?:は|が|[:：])?\s*0\s*件",
    r"イベント\s*(?:は|が)?\s*ゼロ",
    r"イベントは発生していません",
)
COMMENT_MONITORING_MARKERS = (
    "監視",
    "注視",
    "見守",
)
RAILWAY_INFO_URLS = {
    "JR東海道新幹線": "https://traininfo.jr-central.co.jp/shinkansen/sp/ja/index.html",
    "JR東海在来線": "https://traininfo.jr-central.co.jp/zairaisen/index.html",
    "名鉄": "https://top.meitetsu.co.jp/em/",
    "名古屋市営地下鉄": "https://www.kotsu.city.nagoya.jp/rp/emergency/",
    "近鉄": "https://www.kintetsu.jp/unkou/unkou.html",
    "あおなみ線": "https://www.aonamiline.co.jp/railinfo",
    "リニモ": "https://www.linimo.jp/delay/",
    "城北線": "https://tkj-i.co.jp/status/",
}
JST = timezone(timedelta(hours=9), "JST")
QUIET_HOURS_START = time(1, 0)
QUIET_HOURS_END = time(5, 0)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return load_simple_yaml(path)

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.relative_to(ROOT)} is not a YAML mapping.")
    return data


def load_gemma_style(path: Path = STYLE_PATH) -> dict[str, Any]:
    try:
        return load_profile(path)
    except Exception:
        return {}


def gemma_style_phrases(style: dict[str, Any]) -> list[str]:
    phrases = style.get("forbidden_phrases")
    if not isinstance(phrases, list):
        return []
    return [
        " ".join(str(phrase or "").split())
        for phrase in phrases
        if " ".join(str(phrase or "").split())
    ]


def build_gemma_style_block(style: dict[str, Any]) -> str:
    if not style:
        return ""

    tone = style.get("tone") if isinstance(style.get("tone"), dict) else {}
    rules = style.get("rules") if isinstance(style.get("rules"), list) else []
    forbidden = gemma_style_phrases(style)
    good_examples = style.get("good_style_examples")
    bad_examples = style.get("bad_style_examples")
    max_sentences = int(tone.get("max_sentences") or 3)
    emoji_limit = int(tone.get("emoji_limit") or 2)

    lines = [
        "【Gemma課長 出力規定】",
        "・事実のみ。推測禁止。",
        "・情報が無ければ空文字。",
        "・不要な挨拶、締め文、ビジネス報告書風の表現は禁止。",
        f"・最大{max_sentences}文。絵文字は最大{emoji_limit}個。",
    ]
    lines.extend(f"・{rule}" for rule in rules)
    if forbidden:
        lines.extend(["", "【禁止句】"])
        lines.extend(f"・{phrase}" for phrase in forbidden)
    if isinstance(good_examples, list) and good_examples:
        lines.extend(["", "【良い例】"])
        for example in good_examples:
            if isinstance(example, dict):
                lines.append(f"入力: {example.get('input', '')}")
                lines.append(f"出力: {example.get('output', '')}")
    if isinstance(bad_examples, list) and bad_examples:
        lines.extend(["", "【悪い例】"])
        lines.extend(f"・{example}" for example in bad_examples)
    lines.extend(["", "以下のデータを評価してください:"])
    return "\n".join(lines)


def is_gemma_quiet_hours(now: datetime | None = None) -> bool:
    current = now or datetime.now(JST)
    if current.tzinfo is not None:
        current = current.astimezone(JST)
    return QUIET_HOURS_START <= current.time() < QUIET_HOURS_END


def allow_gemma_during_quiet_hours(
    railway_beta_alerts: list[str],
    weather_beta_alerts: list[str],
) -> bool:
    # Future critical weather or infrastructure overrides belong here.
    return False


def load_simple_yaml(path: Path) -> dict[str, Any]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    lines = [
        (len(line) - len(line.lstrip(" ")), line.strip())
        for line in raw_lines
        if line.strip() and not line.lstrip().startswith("#")
    ]

    def scalar(value: str) -> Any:
        text = value.strip()
        if not text:
            return ""
        if text in ("true", "false"):
            return text == "true"
        if text in ("null", "~"):
            return None
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
            if text[0] == '"':
                return json.loads(text)
            return text[1:-1].replace("''", "'")
        return text

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines) or lines[index][0] < indent:
            return {}, index
        is_list = lines[index][0] == indent and lines[index][1].startswith("- ")
        container: Any = [] if is_list else {}

        while index < len(lines):
            line_indent, text = lines[index]
            if line_indent < indent:
                break
            if line_indent > indent:
                raise ValueError(f"Unexpected indentation in {path.relative_to(ROOT)}: {text}")

            if is_list:
                if not text.startswith("- "):
                    break
                item_text = text[2:].strip()
                if not item_text:
                    item, index = parse_block(index + 1, indent + 2)
                    container.append(item)
                    continue
                if ":" in item_text:
                    key, value = item_text.split(":", 1)
                    item = {key.strip(): scalar(value)}
                    index += 1
                    while index < len(lines) and lines[index][0] == indent + 2:
                        child_text = lines[index][1]
                        if ":" not in child_text:
                            raise ValueError(f"Unsupported YAML line in {path.relative_to(ROOT)}: {child_text}")
                        child_key, child_value = child_text.split(":", 1)
                        item[child_key.strip()] = scalar(child_value)
                        index += 1
                    container.append(item)
                    continue
                container.append(scalar(item_text))
                index += 1
                continue

            if text.startswith("- ") or ":" not in text:
                raise ValueError(f"Unsupported YAML line in {path.relative_to(ROOT)}: {text}")
            key, value = text.split(":", 1)
            key = key.strip()
            value = value.strip()
            index += 1
            if value:
                container[key] = scalar(value)
            elif index < len(lines) and lines[index][0] > indent:
                container[key], index = parse_block(index, lines[index][0])
            else:
                container[key] = {}
        return container, index

    parsed, index = parse_block(0, lines[0][0] if lines else 0)
    if index != len(lines) or not isinstance(parsed, dict):
        raise ValueError(f"{path.relative_to(ROOT)} is not a YAML mapping.")
    return parsed


def public_railway_alerts(alerts: list[str]) -> list[str]:
    public_alerts: list[str] = []
    for alert in alerts:
        text = " ".join(str(alert or "").split())
        if not text:
            continue
        if any(marker in text for marker in RAILWAY_BETA_EXCLUDE_MARKERS):
            continue
        public_alerts.append(text)
    return public_alerts


def monitoring_public_railway_alerts(alerts: list[str], now: datetime | None = None) -> list[str]:
    public_alerts = public_railway_alerts(alerts)
    current = now or datetime.now(JST)
    if current.tzinfo is not None:
        current = current.astimezone(JST)
    if time(0, 0) <= current.time() < time(5, 0):
        return [
            alert
            for alert in public_alerts
            if not alert.startswith("東海道新幹線:")
        ]
    return public_alerts


def is_railway_beta_active(now: datetime | None = None) -> bool:
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is not None:
        now = now.astimezone(JST)

    current_time = now.time()
    return current_time >= time(5, 0) or current_time < time(1, 0)


def is_railway_monitoring_active(
    now: datetime | None = None,
    state_path: Path = RAILWAY_STATE_PATH,
) -> tuple[bool, str]:
    current = now or datetime.now(JST)
    if current.tzinfo is not None:
        current = current.astimezone(JST)
    if is_railway_beta_active(current):
        if current.time() < time(5, 0) and current.time() >= time(0, 0):
            return True, "normal_hours_before_0100"
        return True, "normal_hours"
    _state_exists, previous_alerts = load_railway_state(state_path)
    metadata = load_railway_state_metadata(state_path)
    return critical_transport_overnight_monitoring_active(
        now=current,
        previous_alerts=previous_alerts,
        critical_transport_recovered_at=str(
            metadata.get("critical_transport_recovered_at") or ""
        ),
    )


def load_railway_beta_alerts(now: datetime | None = None) -> list[str]:
    alerts, _updated_at_by_alert, _source_url_by_alert, _level_by_alert = load_railway_beta_snapshot(now)
    return alerts


def load_railway_beta_snapshot(
    now: datetime | None = None,
) -> tuple[list[str], dict[str, datetime], dict[str, str], dict[str, str]]:
    active, _reason = is_railway_monitoring_active(now)
    if not active:
        return [], {}, {}, {}

    try:
        alerts, updated_at_by_alert, source_url_by_alert, level_by_alert = get_all_railway_alerts_snapshot()
        public_alerts = monitoring_public_railway_alerts(alerts, now)
        return (
            public_alerts,
            {
                alert: updated_at
                for alert, updated_at in updated_at_by_alert.items()
                if alert in public_alerts
            },
            {
                alert: source_url
                for alert, source_url in source_url_by_alert.items()
                if alert in public_alerts
            },
            {
                alert: level
                for alert, level in level_by_alert.items()
                if alert in public_alerts
            },
        )
    except Exception:
        return [], {}, {}, {}


def load_weather_beta_alerts(now: datetime | None = None) -> list[str]:
    try:
        return get_all_weather_alerts(now)
    except Exception:
        return []


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def railway_official_hash(
    alerts: list[str],
    structured_events: list[dict[str, Any]] | None = None,
) -> str:
    event_payload = []
    for event in structured_events or []:
        event_payload.append(
            {
                "line_id": event.get("line_id", ""),
                "line": event.get("line", ""),
                "status_id": event.get("status_id", ""),
                "cause": event.get("cause", ""),
                "section_from": event.get("section_from", ""),
                "section_to": event.get("section_to", ""),
                "direction": event.get("direction", ""),
                "accident_time": event.get("accident_time", ""),
                "prospect_time": event.get("prospect_time", ""),
                "resume_time": event.get("resume_time", ""),
                "message": event.get("message", ""),
                "recover_message": event.get("recover_message", ""),
            }
        )
    return _json_hash(
        {
            "normalized_alerts": [" ".join(str(alert or "").split()) for alert in alerts],
            "structured_events": event_payload,
        }
    )


def important_active_no_official_change_override_alerts(alerts: list[str]) -> list[str]:
    matched = []
    for alert in alerts:
        text = " ".join(str(alert or "").split())
        if not text:
            continue
        if not any(marker in text for marker in IMPORTANT_ACTIVE_TARGET_MARKERS):
            continue
        if any(marker in text for marker in IMPORTANT_ACTIVE_AREA_MARKERS) and any(
            marker in text for marker in IMPORTANT_ACTIVE_INCIDENT_MARKERS
        ):
            matched.append(text)
    return matched


def _weather_history_path(debug_dir: Path, now: datetime) -> Path:
    base = debug_dir / f"{now:%Y%m%d_%H%M%S}.json"
    if not base.exists():
        return base
    for index in range(1, 100):
        candidate = debug_dir / f"{now:%Y%m%d_%H%M%S}_{index}.json"
        if not candidate.exists():
            return candidate
    return debug_dir / f"{now:%Y%m%d_%H%M%S}_{now.microsecond}.json"


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def save_weather_debug(
    snapshot: dict[str, Any],
    *,
    now: datetime,
    severity: str,
    notify_allowed: bool,
    suppress_reason: str,
    debug_dir: Path = WEATHER_DEBUG_DIR,
) -> dict[str, Any]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    normalized_alerts = snapshot.get("normalized_alerts")
    if not isinstance(normalized_alerts, list):
        normalized_alerts = []
    raw_jma = snapshot.get("raw_jma", {})
    raw_openmeteo = snapshot.get("raw_openmeteo", {})
    result = {
        "timestamp": now.astimezone(JST).isoformat(timespec="seconds"),
        "source": snapshot.get("source", ["JMA", "Open-Meteo"]),
        "raw": {
            "JMA": raw_jma,
            "Open-Meteo": raw_openmeteo,
        },
        "raw_jma": raw_jma,
        "raw_openmeteo": raw_openmeteo,
        "normalized": normalized_alerts,
        "normalized_alerts": normalized_alerts,
        "alerts": normalized_alerts,
        "severity": severity,
        "notify_allowed": bool(notify_allowed),
        "suppress_reason": suppress_reason,
        "suppressed_reason": suppress_reason,
        "source_errors": snapshot.get("source_errors", []),
    }
    result["hash"] = _json_hash(
        {
            "raw_jma": raw_jma,
            "raw_openmeteo": raw_openmeteo,
            "normalized_alerts": normalized_alerts,
        }
    )
    latest_path = debug_dir / "latest.json"
    history_path = _weather_history_path(debug_dir, now.astimezone(JST))
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    latest_path.write_text(payload + "\n", encoding="utf-8")
    history_path.write_text(payload + "\n", encoding="utf-8")
    log(
        "weather_debug_saved: "
        f"latest={_display_path(latest_path)} history={_display_path(history_path)}"
    )
    return result


def record_weather_decision(
    snapshot: dict[str, Any],
    *,
    now: datetime,
    severity: str,
    notify_allowed: bool,
    suppress_reason: str,
) -> dict[str, Any]:
    log(f"weather_notify_allowed: {'true' if notify_allowed else 'false'}")
    log(
        "weather_notify_reason: "
        f"{'notify' if notify_allowed else suppress_reason or 'suppressed'}"
    )
    if not notify_allowed:
        log(f"weather_notify_suppressed: reason={suppress_reason}")
    alerts = snapshot.get("normalized_alerts")
    if isinstance(alerts, list) and any("雨終了予測" in str(alert) for alert in alerts):
        log("weather_end_detected: true")
    return save_weather_debug(
        snapshot,
        now=now,
        severity=severity,
        notify_allowed=notify_allowed,
        suppress_reason=suppress_reason,
    )


def load_weather_state(path: Path = WEATHER_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_weather_state(
    alerts: list[str],
    weather_hash: str,
    now: datetime,
    path: Path = WEATHER_STATE_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "updated_at": now.astimezone(JST).isoformat(timespec="seconds"),
                "alerts": alerts,
                "weather_hash": weather_hash,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def weather_change_type(previous_alerts: list[str], current_alerts: list[str]) -> str:
    previous = [" ".join(str(alert or "").split()) for alert in previous_alerts if str(alert or "").strip()]
    current = [" ".join(str(alert or "").split()) for alert in current_alerts if str(alert or "").strip()]
    if current and current != previous:
        return "changed"
    if previous and not current:
        return "removed_silent"
    return "no change"


def load_weather_beta_snapshot(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(JST)
    if current.tzinfo is not None:
        current = current.astimezone(JST)
    try:
        snapshot = get_all_weather_snapshot(current)
    except Exception as exc:
        log(f"weather_source_failed: source=all error={type(exc).__name__}")
        snapshot = {
            "source": ["JMA", "Open-Meteo"],
            "raw_jma": {},
            "raw_openmeteo": {},
            "normalized_alerts": [],
            "source_errors": [{"source": "all", "error": type(exc).__name__}],
        }
    alerts = snapshot.get("normalized_alerts")
    if not isinstance(alerts, list):
        alerts = []
    snapshot["normalized_alerts"] = alerts
    for error in snapshot.get("source_errors", []):
        if isinstance(error, dict):
            log(
                "weather_source_failed: "
                f"source={error.get('source', '')} error={error.get('error', '')}"
            )
    return snapshot


def railway_alert_prefix(alert: str) -> str:
    text = " ".join(str(alert or "").split())
    for separator in (":", "："):
        if separator in text:
            return " ".join(text.split(separator, 1)[0].split())
    return text


def railway_info_source(alert: str, source_url: str = "") -> tuple[str, str, str]:
    prefix = railway_alert_prefix(alert)
    if "東海道新幹線" in prefix:
        return "JR東海道新幹線", "JR東海道新幹線", RAILWAY_INFO_URLS["JR東海道新幹線"]
    if "JR東海在来線" in prefix:
        display = jrc_target_line_display(alert)
        url = jrc_target_line_url(alert)
        if display and url:
            title = f"JR {display}"
            url_label = "JR " + display.splitlines()[0]
            return title, url_label, url
        return "JR 在来線", "JR 在来線", RAILWAY_INFO_URLS["JR東海在来線"]
    meitetsu_match = re.match(r"名鉄\s+(.+)", prefix)
    if meitetsu_match:
        line = " ".join(meitetsu_match.group(1).split())
        title = f"名鉄{line}"
        return title, title, source_url or RAILWAY_INFO_URLS["名鉄"]
    if prefix.startswith("名古屋市営地下鉄"):
        return prefix, "名古屋市営地下鉄", source_url or RAILWAY_INFO_URLS["名古屋市営地下鉄"]
    for label in (
        "名鉄",
        "近鉄",
        "あおなみ線",
        "リニモ",
        "城北線",
    ):
        if prefix == label or prefix.startswith(f"{label} "):
            return label, label, source_url or RAILWAY_INFO_URLS[label]
    return "鉄道運行情報", "", ""


def official_alert_body(alert: str) -> str:
    for separator in (":", "："):
        if separator in alert:
            return " ".join(alert.split(separator, 1)[1].split())
    return " ".join(alert.split())


def display_railway_alert(alert: str) -> str:
    text = " ".join(str(alert or "").split())
    if text.startswith("JR東海在来線 "):
        return "JR " + text.removeprefix("JR東海在来線 ")
    if text.startswith("JR東海在来線:") or text.startswith("JR東海在来線："):
        return "JR 在来線" + text[len("JR東海在来線"):]
    return text


def grouped_railway_alerts(
    alerts: list[str],
    source_url_by_alert: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    source_url_by_alert = source_url_by_alert or {}
    groups: list[dict[str, Any]] = []
    group_index: dict[tuple[Any, ...], int] = {}

    for alert in alerts:
        text = " ".join(str(alert or "").split())
        if not text:
            continue

        title, url_label, url = railway_info_source(text, source_url_by_alert.get(text, ""))
        body = official_alert_body(text)
        if not body:
            continue

        meitetsu_match = re.match(r"名鉄\s+([^:：]+)[:：]", text)
        target_line = " ".join(meitetsu_match.group(1).split()) if meitetsu_match else ""
        if target_line:
            title = "名鉄"
            url_label = "名鉄"
            key = ("meitetsu", url, body)
        else:
            key = (title, url_label, url)

        if key not in group_index:
            group_index[key] = len(groups)
            groups.append(
                {
                    "title": title,
                    "url_label": url_label,
                    "url": url,
                    "messages": [],
                    "target_lines": [],
                    "alerts": [],
                    "identity": key,
                }
            )

        group = groups[group_index[key]]
        messages = group["messages"]
        if body not in messages:
            messages.append(body)
        if target_line and target_line not in group["target_lines"]:
            group["target_lines"].append(target_line)
        group["alerts"].append(text)

    return groups


def railway_group_body_lines(group: dict[str, Any]) -> list[str]:
    target_lines = group.get("target_lines") or []
    messages = group.get("messages") or []
    if target_lines:
        lines = ["対象路線:"]
        lines.extend(f"・{line}" for line in target_lines)
        lines.append("")
        for message in messages:
            lines.extend(f"・{part}" for part in message.split(" / ") if part)
        return lines
    lines = [f"・{message}" for message in messages]
    if group.get("title") == "あおなみ線" and any(
        keyword in message
        for message in messages
        for keyword in ("強風", "台風", "運転見合わせ", "運転を見合わせ", "運休")
    ):
        lines.extend(["", f"需要補正: {AONAMI_DEMAND_REASON}"])
    return lines


def railway_severity_emoji(severity: str) -> str:
    return RAILWAY_SEVERITY_EMOJIS.get(severity, RAILWAY_SEVERITY_EMOJIS["info"])


def railway_alert_timestamp(
    alerts: list[str],
    updated_at_by_alert: dict[str, datetime],
    fallback: datetime,
) -> datetime:
    timestamps: list[datetime] = []
    for alert in alerts:
        updated_at = updated_at_by_alert.get(alert)
        if not isinstance(updated_at, datetime):
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=JST)
        timestamps.append(updated_at.astimezone(JST))
    selected = max(timestamps) if timestamps else fallback
    if selected.tzinfo is None:
        selected = selected.replace(tzinfo=JST)
    return selected.astimezone(JST)


def format_railway_current_time(timestamp: datetime, today: datetime) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=JST)
    if today.tzinfo is None:
        today = today.replace(tzinfo=JST)
    timestamp_jst = timestamp.astimezone(JST)
    today_jst = today.astimezone(JST)
    if timestamp_jst.date() == today_jst.date():
        return f"（{timestamp_jst:%H:%M}現在）"
    return (
        f"（{timestamp_jst.month}月{timestamp_jst.day}日 "
        f"{timestamp_jst:%H:%M}現在）"
    )


def build_railway_beta_comment(
    railway_beta_alerts: list[str],
    checked_at: datetime | None = None,
    updated_at_by_alert: dict[str, datetime] | None = None,
    source_url_by_alert: dict[str, str] | None = None,
) -> str:
    checked_at = checked_at or datetime.now(JST)
    updated_at_by_alert = updated_at_by_alert or {}
    source_url_by_alert = source_url_by_alert or {}
    blocks: list[str] = []
    for group in grouped_railway_alerts(railway_beta_alerts, source_url_by_alert):
        title = group["title"]
        url_label = group["url_label"]
        url = group["url"]
        messages = group["messages"]
        if not messages:
            continue
        severity = detect_railway_severity(messages)
        timestamp = railway_alert_timestamp(
            group["alerts"],
            updated_at_by_alert,
            checked_at,
        )
        lines = [
            f"{railway_severity_emoji(severity)} {title}",
            format_railway_current_time(timestamp, checked_at),
            "",
        ]
        lines.extend(railway_group_body_lines(group))
        if url_label and url:
            lines.extend(["", f"🔗 {url_label}", url])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip()


def build_railway_change_comment(
    added_alerts: list[str],
    current_alerts: list[str],
    checked_at: datetime | None = None,
    updated_at_by_alert: dict[str, datetime] | None = None,
    source_url_by_alert: dict[str, str] | None = None,
) -> str:
    checked_at = checked_at or datetime.now(JST)
    updated_at_by_alert = updated_at_by_alert or {}
    source_url_by_alert = source_url_by_alert or {}
    added_group_keys = {
        group["identity"]
        for group in grouped_railway_alerts(added_alerts, source_url_by_alert)
    }
    blocks: list[str] = []
    for group in grouped_railway_alerts(current_alerts, source_url_by_alert):
        if group["identity"] not in added_group_keys:
            continue
        title = group["title"]
        url_label = group["url_label"]
        url = group["url"]
        messages = group["messages"]
        severity = detect_railway_severity(messages)
        timestamp = railway_alert_timestamp(
            group["alerts"],
            updated_at_by_alert,
            checked_at,
        )
        lines = [
            f"{railway_severity_emoji(severity)} {title}",
            format_railway_current_time(timestamp, checked_at),
            "",
        ]
        lines.extend(railway_group_body_lines(group))
        if url_label and url:
            lines.extend(["", f"🔗 {url_label}", url])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip()


def build_railway_state_comment(
    state_exists: bool,
    previous_alerts: list[str],
    current_alerts: list[str],
    checked_at: datetime | None = None,
    updated_at_by_alert: dict[str, datetime] | None = None,
    source_url_by_alert: dict[str, str] | None = None,
    previous_zairai_events: list[dict[str, Any]] | None = None,
    current_zairai_events: list[dict[str, Any]] | None = None,
) -> tuple[str, str, list[str], list[str]]:
    raw_added_alerts, removed_alerts = diff_alerts(previous_alerts, current_alerts)
    candidates = current_alerts if not state_exists else raw_added_alerts
    added_alerts, filter_decisions = filter_added_railway_alerts(
        candidates,
        previous_alerts,
        previous_zairai_events,
        current_zairai_events,
    )
    for decision in filter_decisions:
        source = decision["source"]
        if source not in ("shinkansen", "zairai"):
            continue
        prefix = (
            "railway_shinkansen_filter_reason"
            if source == "shinkansen"
            else "railway_zairai_change_reason"
        )
        action = "notify" if decision["notify"] else "suppress"
        log(f"{prefix}: {action} reason={decision['reason']}")

    if not state_exists and added_alerts:
        return (
            build_railway_beta_comment(
                added_alerts,
                checked_at,
                updated_at_by_alert,
                source_url_by_alert,
            ),
            "initial",
            added_alerts,
            [],
        )
    if not state_exists and current_alerts:
        return "", "changed", [], []
    if previous_alerts and not current_alerts:
        return "", "recovered", [], previous_alerts
    if added_alerts:
        return (
            build_railway_change_comment(
                added_alerts,
                current_alerts,
                checked_at,
                updated_at_by_alert,
                source_url_by_alert,
            ),
            "changed",
            added_alerts,
            removed_alerts,
        )
    if removed_alerts:
        return "", "changed", [], removed_alerts
    if raw_added_alerts:
        return "", "changed", [], []
    return "", "unchanged", [], []


def build_railway_beta_block(alerts: list[str]) -> str:
    if not alerts:
        return ""

    alert_lines = "\n".join(f"- {alert}" for alert in alerts)
    return f"""交通情報ベータ:
{alert_lines}

交通情報ベータの扱い:
- この情報はベータ機能による自動取得です。
- 取得タイミングや各社サイトの更新状況により、実際の状況と異なる場合があります。
- 上の交通情報は省略せず、取得できた事実を最大限活用してください。
- AIによる原因の補完、復旧見込みの創作、影響範囲の拡大解釈は禁止です。
- 運転再開の判断、鉄道会社への指示、上司・部下っぽい報告は禁止です。
- 鉄道会社や運転士への指示は禁止です。
- 朝礼、日報、挨拶、社内報告、防災本部、管理職の文体は禁止です。
- 禁止語: おはようございます / 本日も / 状況を確認しました / 報告ありがとうございます / 〇〇さん / 皆さん / 引き続き / 慎重に進めましょう / 判断しましょう
- 禁止語: 支障をきたす / 確認されました / 情報収集 / 影響範囲 / モニタリング / 継続します / 発生。 / 状況把握 / 引き続き注視
- 交通情報ベータがある場合は、公共交通情報として挨拶なし・前置きなしで書いてください。
- 交通情報ベータが同じ路線で複数ある場合は、ページ掲載順を維持して「・」の箇条書きにしてください。
- 行動指示は禁止です。
- 書く内容は、取得できた事実のみです。
- 表現例:
🔵 JR 東海道線

（08:25現在）

・尾張一宮～木曽川駅間で列車遅延
"""


def build_weather_beta_block(alerts: list[str]) -> str:
    if not alerts:
        return ""

    alerts_json = json.dumps(alerts, ensure_ascii=False, indent=2)
    return f"""【天気ベータ】
以下は名古屋中心部の営業に影響する可能性がある気象情報です。
- 普段の天気予報ではありません
- 営業判断に関係しそうな異常・直近変化だけです
- 大げさにせず短く書いてください
- 取得失敗や不明点は書かないでください
weather_beta_alerts:
{alerts_json}
"""


def public_weather_message(alert: str) -> str:
    text = " ".join(str(alert or "").split())
    replacements = {
        "名古屋中心部で1時間以内に雨開始予測": "名古屋中心部で1時間以内に雨が降り始める可能性があります。",
        "名古屋中心部で1時間以内に雨が強まる可能性": "名古屋中心部で1時間以内に雨が強まる可能性があります。",
        "名古屋中心部で1時間以内に雷の可能性": "名古屋中心部で1時間以内に雷の可能性があります。",
    }
    if text in replacements:
        return replacements[text]
    if text and text[-1] not in "。！？":
        return text + "。"
    return text


def build_weather_beta_comment(alerts: list[str], severity: str | None = None) -> str:
    weather_severity = severity or detect_weather_severity(alerts)
    emoji = {
        "weather_info": "☔",
        "weather_alert": "⛈️",
        "weather_critical": "🚨",
    }.get(weather_severity, "☔")

    messages: list[str] = []
    for alert in alerts:
        text = " ".join(str(alert or "").split())
        if not text or "需要" in text or "ピークアウト" in text:
            continue
        message = public_weather_message(text)
        if message and message not in messages:
            messages.append(message)
    if not messages:
        return ""
    lines = [f"{emoji} {messages[0]}"]
    lines.extend(f"・{message}" for message in messages[1:3])
    return "\n".join(lines)


def build_prompt(
    report: str,
    profile: dict[str, Any],
    railway_beta_alerts: list[str] | None = None,
    weather_beta_alerts: list[str] | None = None,
    style: dict[str, Any] | None = None,
) -> str:
    profile_json = json.dumps(profile, ensure_ascii=False, indent=2)
    railway_alerts = railway_beta_alerts or []
    railway_beta_block = build_railway_beta_block(railway_alerts)
    weather_beta_block = build_weather_beta_block(weather_beta_alerts or [])
    railway_priority_rule = (
        "交通情報ベータがあるため、日報コメントではなく公共交通情報の掲示文を最優先で作ってください。\n"
        "プロフィール、挨拶、朝礼、雑談、ツッコミ、日報要約、防災本部風の表現は出さないでください。"
        if railway_alerts
        else ""
    )
    style_block = build_gemma_style_block(style or {})
    return f"""{style_block}

あなたはジェンマ課長です。

以下のプロフィールと日報をもとに、短いコメントだけを作ってください。

{railway_priority_rule}

生成ルール:
- 3～5行
- 箇条書き中心
- 自信がない内容は断定しない
- 候補は candidate とする
- 本番データを勝手に確定しない
- 運転再開≠復旧
- 運転再開の判断、鉄道会社への指示はしない
- 「〇〇候補さん」「皆さん」は使わない
- 「おはようございます」「本日も」「状況を確認しました」「報告ありがとうございます」「〇〇さん」「引き続き」「慎重に進めましょう」「判断しましょう」は使わない
- 「支障をきたす」「確認されました」「情報収集」「影響範囲」「モニタリング」「継続します」「発生。」「状況把握」「引き続き注視」は使わない
- 上司・部下っぽい報告文にしない
- 鉄道遅延は、取得した事実だけを短く伝える
- 交通情報ベータがある場合は公共交通情報として書き、挨拶なし・前置きなしで事象を箇条書きにする
- 交通情報ベータに解説、推測、注意喚起を付けない
- ツッコミは最大1回
- スギケツバットは毎回出さない
- 交通情報ベータがある場合だけ、交通情報にも短く触れる
- 天気ベータがある場合だけ、名古屋中心部の需要変化にも短く触れる

profile:
{profile_json}

report:
{report}

{railway_beta_block}
{weather_beta_block}
"""


def actionable_report_text(report: str) -> str:
    lines = []
    for line in str(report or "").splitlines():
        compact = " ".join(line.split())
        if not compact or "0件" in compact:
            continue
        lines.append(compact)
    return " ".join(lines)


def should_generate_comment(report: str, railway_beta_alerts: list[str], weather_beta_alerts: list[str]) -> bool:
    if railway_beta_alerts or weather_beta_alerts:
        return True

    text = " ".join(str(report or "").split())
    if not text:
        return False
    signal_text = actionable_report_text(report)
    if any(marker in text for marker in COMMENT_NO_SIGNAL_MARKERS):
        return any(keyword in signal_text for keyword in COMMENT_SIGNAL_KEYWORDS)
    return any(keyword in signal_text for keyword in COMMENT_SIGNAL_KEYWORDS)


def is_minor_weather_only(
    railway_beta_alerts: list[str],
    weather_beta_alerts: list[str],
) -> bool:
    if railway_beta_alerts or not weather_beta_alerts:
        return False
    return is_minor_weather(weather_beta_alerts)


def is_empty_status_comment(comment: str, forbidden_phrases: list[str] | None = None) -> bool:
    text = " ".join(str(comment or "").split())
    if not text:
        return True
    markers = [*COMMENT_NO_SIGNAL_MARKERS, *(forbidden_phrases or [])]
    return any(marker in text for marker in markers)


def sentence_count(comment: str) -> int:
    raw = str(comment or "")
    if not raw.strip():
        return 0
    punctuation_sentences = [
        part.strip()
        for part in re.split(r"[。！？!?]+", " ".join(raw.split()))
        if part.strip()
    ]
    nonempty_lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return max(len(punctuation_sentences), len(nonempty_lines))


def emoji_count(comment: str) -> int:
    return len(re.findall(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", comment))


def report_event_counts(report: str) -> set[int]:
    return {
        int(value)
        for value in re.findall(r"イベント[^\n\d]{0,12}(\d+)\s*件", str(report or ""))
    }


def comment_event_counts(comment: str) -> set[int]:
    return {
        int(value)
        for value in re.findall(r"イベント[^\n\d]{0,12}(\d+)\s*件", str(comment or ""))
    }


def gemma_style_guard_reasons(
    comment: str,
    style: dict[str, Any],
    report: str,
) -> list[str]:
    text = " ".join(str(comment or "").split())
    if not text:
        return []

    reasons: list[str] = []
    forbidden = gemma_style_phrases(style)
    matched_forbidden = [phrase for phrase in forbidden if phrase in text]
    if matched_forbidden:
        reasons.append(f"forbidden_phrase:{matched_forbidden[0]}")

    if any(re.search(pattern, text) for pattern in COMMENT_ZERO_EVENT_PATTERNS):
        reasons.append("event_count_zero")
    if any(marker in text for marker in COMMENT_NO_SIGNAL_MARKERS):
        reasons.append("empty_status_comment")

    factual_terms = (
        "事故",
        "遅延",
        "運休",
        "運転",
        "通行",
        "規制",
        "雨",
        "雷",
        "雪",
        "イベント",
        "混雑",
        "需要",
    )
    if any(marker in text for marker in COMMENT_MONITORING_MARKERS) and not any(
        term in text for term in factual_terms
    ):
        reasons.append("monitoring_only")

    claimed_counts = comment_event_counts(text)
    known_counts = report_event_counts(report)
    if claimed_counts and not claimed_counts.issubset(known_counts):
        reasons.append("unsupported_event_count")

    tone = style.get("tone") if isinstance(style.get("tone"), dict) else {}
    max_sentences = int(tone.get("max_sentences") or 3)
    if sentence_count(text) > max_sentences:
        reasons.append(f"too_many_sentences:{sentence_count(text)}")
    if bool(tone.get("allow_emoji", True)):
        emoji_limit = int(tone.get("emoji_limit") or 2)
        if emoji_count(text) > emoji_limit:
            reasons.append(f"too_many_emoji:{emoji_count(text)}")
    elif emoji_count(text):
        reasons.append("emoji_not_allowed")

    return list(dict.fromkeys(reasons))


def validate_railway_beta_comment(comment: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for forbidden in RAILWAY_BETA_FORBIDDEN_OUTPUTS:
        if forbidden in comment:
            errors.append(forbidden)
    return (not errors, errors)


def write_comment_result(result: dict[str, Any], comment: str) -> None:
    AI_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_OUTPUT_PATH.write_text(comment + ("\n" if comment else ""), encoding="utf-8")
    with JSON_OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")


def call_ollama(prompt: str) -> dict[str, Any] | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None

    data = json.loads(response_body)
    if not isinstance(data, dict):
        raise ValueError("Ollama response is not a JSON object.")
    return data


def main() -> int:
    report = REPORT_PATH.read_text(encoding="utf-8")
    profile = load_profile(PROFILE_PATH)
    style = load_gemma_style()
    now_jst = datetime.now(JST)
    log(f"ollama_model: {MODEL}")
    try:
        get_jrc_shinkansen_plan_notice(now=now_jst)
    except Exception as exc:
        log(f"shinkansen_plan_notice_error: {type(exc).__name__}: {exc}")
    railway_beta_is_active, railway_monitoring_reason = is_railway_monitoring_active(now_jst)
    (
        railway_beta_alerts,
        railway_updated_at_by_alert,
        railway_source_url_by_alert,
        railway_level_by_alert,
    ) = load_railway_beta_snapshot(now_jst)
    railway_beta_display_alerts = [
        display_railway_alert(alert) for alert in railway_beta_alerts
    ]
    weather_snapshot = load_weather_beta_snapshot(now_jst)
    weather_beta_alerts = weather_snapshot.get("normalized_alerts")
    if not isinstance(weather_beta_alerts, list):
        weather_beta_alerts = []
    weather_severity = detect_weather_severity(weather_beta_alerts)
    previous_weather_state = load_weather_state()
    previous_weather_alerts = previous_weather_state.get("alerts")
    if not isinstance(previous_weather_alerts, list):
        previous_weather_alerts = []
    weather_hash = _json_hash(
        {
            "normalized_alerts": weather_beta_alerts,
        }
    )
    weather_change = weather_change_type(previous_weather_alerts, weather_beta_alerts)
    save_weather_state(weather_beta_alerts, weather_hash, now_jst)
    if not railway_beta_is_active:
        log(f"railway_beta_alerts: skipped overnight reason={railway_monitoring_reason}")
    elif railway_beta_alerts:
        log(f"railway_beta_alerts: {len(railway_beta_alerts)} reason={railway_monitoring_reason}")
    else:
        log(f"railway_beta_alerts: 0 reason={railway_monitoring_reason}")
    log(f"weather_beta_alerts: {len(weather_beta_alerts)}")
    if weather_beta_alerts:
        log(f"weather_alerts_detected: {len(weather_beta_alerts)}")
    log(f"weather_hash: {weather_hash[:12]}")
    log(f"weather_beta_comment: {weather_change}")

    if not railway_beta_is_active:
        log("railway_beta_comment: skipped overnight")
        railway_severity = detect_railway_severity([])
    else:
        state_exists, previous_railway_alerts = load_railway_state(RAILWAY_STATE_PATH)
        state_metadata = load_railway_state_metadata(RAILWAY_STATE_PATH)
        morning_reposted_date = str(
            state_metadata.get("morning_reposted_date") or ""
        )
        critical_transport_recovered_at = str(
            state_metadata.get("critical_transport_recovered_at") or ""
        )
        existing_incident_first_seen = load_railway_incident_first_seen(
            RAILWAY_STATE_PATH
        )
        incident_first_seen_at = update_railway_incident_first_seen(
            railway_beta_alerts,
            existing_incident_first_seen,
            now_jst,
        )
        last_notify = load_railway_last_notify(RAILWAY_LAST_NOTIFY_PATH)
        previous_zairai_events = load_structured_filter_state(
            RAILWAY_ZAIRAI_FILTER_STATE_PATH
        )
        current_zairai_events = get_last_jrc_zairai_structured_events()
        railway_official_current_hash = railway_official_hash(
            railway_beta_alerts,
            current_zairai_events,
        )
        previous_railway_official_hash = str(
            state_metadata.get("official_hash") or ""
        )
        previous_railway_impact = str(state_metadata.get("impact") or "")
        railway_pre_notify_allowed, railway_pre_notify_reason = (
            classify_railway_pre_llm_notification(
                previous_alerts=previous_railway_alerts,
                current_alerts=railway_beta_alerts,
                previous_official_hash=previous_railway_official_hash,
                current_official_hash=railway_official_current_hash,
                previous_impact=previous_railway_impact,
            )
        )
        current_railway_impact = (
            "major"
            if has_major_railway_incident(railway_beta_alerts)
            else "low_impact"
            if railway_beta_alerts
            else ""
        )
        if critical_transport_alerts(railway_beta_alerts):
            next_critical_transport_recovered_at = ""
        elif critical_transport_alerts(previous_railway_alerts):
            next_critical_transport_recovered_at = now_jst.isoformat(timespec="seconds")
        else:
            next_critical_transport_recovered_at = critical_transport_recovered_at
        railway_severity = detect_railway_severity(railway_beta_alerts or previous_railway_alerts)
        important_override_alerts = important_active_no_official_change_override_alerts(
            railway_beta_alerts
        )
        previous_important_override_hash = str(
            state_metadata.get("important_active_no_official_change_override_hash") or ""
        )
        important_active_no_official_change_override = (
            railway_pre_notify_reason in ("no_official_change", "low_impact")
            and bool(important_override_alerts)
            and previous_important_override_hash != railway_official_current_hash
        )
        duplicate_important_active_override = (
            railway_pre_notify_reason in ("no_official_change", "low_impact")
            and bool(important_override_alerts)
            and previous_important_override_hash == railway_official_current_hash
        )

        if important_active_no_official_change_override:
            log(
                "railway_notify_allowed: true "
                "reason=important_active_no_official_change_override"
            )
            comment = build_railway_beta_comment(
                important_override_alerts,
                now_jst,
                railway_updated_at_by_alert,
                railway_source_url_by_alert,
            )
            ok, errors = validate_railway_beta_comment(comment)
            if not ok:
                log(f"railway_beta_comment_guard: {errors}")
                comment = ""
            save_railway_state(
                RAILWAY_STATE_PATH,
                railway_beta_alerts,
                now_jst,
                railway_level_by_alert,
                morning_reposted_date,
                incident_first_seen_at,
                critical_transport_recovered_at=next_critical_transport_recovered_at,
                official_hash=railway_official_current_hash,
                impact=current_railway_impact,
                important_active_no_official_change_override_hash=(
                    railway_official_current_hash
                    if comment
                    else previous_important_override_hash
                ),
                shinkansen_no_official_change_override_hash=(
                    railway_official_current_hash
                    if comment and any("新幹線" in alert for alert in important_override_alerts)
                    else str(state_metadata.get("shinkansen_no_official_change_override_hash") or "")
                ),
            )
            save_structured_filter_state(
                RAILWAY_ZAIRAI_FILTER_STATE_PATH,
                current_zairai_events,
            )
            if comment:
                save_railway_last_notify(
                    RAILWAY_LAST_NOTIFY_PATH,
                    railway_severity,
                    now_jst,
                )
            result = {
                "generated_at": now_iso(),
                "model": "python:important_active_no_official_change_override",
                "comment": comment,
                "railway_beta_alerts": railway_beta_alerts,
                "railway_beta_display_alerts": railway_beta_display_alerts,
                "railway_beta_previous_alerts": previous_railway_alerts,
                "railway_beta_previous_display_alerts": [
                    display_railway_alert(alert) for alert in previous_railway_alerts
                ],
                "railway_beta_override_alerts": important_override_alerts,
                "railway_beta_source_urls": railway_source_url_by_alert,
                "railway_beta_levels": railway_level_by_alert,
                "railway_beta_change_type": "important_active_no_official_change_override",
                "railway_beta_change_reason": "important_active_no_official_change_override",
                "railway_beta_notification": bool(comment),
                "railway_notify_allowed": bool(comment),
                "railway_official_hash": railway_official_current_hash,
                "severity": railway_severity,
                "weather_beta_alerts": weather_beta_alerts,
                "weather_severity": weather_severity,
                "done": bool(comment),
                "ollama_skipped": True,
                "llm_skipped": True,
                "silent_reason": "important_active_no_official_change_override",
            }
            write_comment_result(result, comment)
            log(
                "railway_beta_comment: important_active_no_official_change_override"
                if comment
                else "railway_beta_comment: empty"
            )
            record_weather_decision(
                weather_snapshot,
                now=now_jst,
                severity=weather_severity,
                notify_allowed=False,
                suppress_reason="railway_notification_takes_priority" if comment else "railway_override_empty",
            )
            log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {RAILWAY_STATE_PATH.relative_to(ROOT)}")
            return 0

        if duplicate_important_active_override:
            save_railway_state(
                RAILWAY_STATE_PATH,
                railway_beta_alerts,
                now_jst,
                railway_level_by_alert,
                morning_reposted_date,
                incident_first_seen_at,
                critical_transport_recovered_at=next_critical_transport_recovered_at,
                official_hash=railway_official_current_hash,
                impact=current_railway_impact,
            )
            save_structured_filter_state(
                RAILWAY_ZAIRAI_FILTER_STATE_PATH,
                current_zairai_events,
            )
            result = {
                "generated_at": now_iso(),
                "model": "python:railway_pre_llm_filter",
                "comment": "",
                "railway_beta_alerts": railway_beta_alerts,
                "railway_beta_display_alerts": railway_beta_display_alerts,
                "railway_beta_previous_alerts": previous_railway_alerts,
                "railway_beta_previous_display_alerts": [
                    display_railway_alert(alert) for alert in previous_railway_alerts
                ],
                "railway_beta_override_alerts": important_override_alerts,
                "railway_beta_source_urls": railway_source_url_by_alert,
                "railway_beta_levels": railway_level_by_alert,
                "railway_beta_change_type": "duplicate_important_active_override",
                "railway_beta_change_reason": "duplicate_important_active_override",
                "railway_beta_comment": "duplicate_important_active_override",
                "railway_beta_notification": False,
                "railway_notify_allowed": False,
                "railway_official_hash": railway_official_current_hash,
                "severity": railway_severity,
                "weather_beta_alerts": weather_beta_alerts,
                "weather_severity": weather_severity,
                "done": False,
                "ollama_skipped": True,
                "llm_skipped": True,
                "silent_reason": "duplicate_important_active_override",
            }
            write_comment_result(result, "")
            log("railway_notify_suppressed: duplicate_important_active_override")
            log("railway_beta_comment: duplicate_important_active_override")
            record_weather_decision(
                weather_snapshot,
                now=now_jst,
                severity=weather_severity,
                notify_allowed=False,
                suppress_reason="duplicate_important_active_override",
            )
            log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {RAILWAY_STATE_PATH.relative_to(ROOT)}")
            return 0

        if railway_pre_notify_reason in ("no_official_change", "low_impact"):
            save_railway_state(
                RAILWAY_STATE_PATH,
                railway_beta_alerts,
                now_jst,
                railway_level_by_alert,
                morning_reposted_date,
                incident_first_seen_at,
                critical_transport_recovered_at=next_critical_transport_recovered_at,
                official_hash=railway_official_current_hash,
                impact=current_railway_impact,
            )
            save_structured_filter_state(
                RAILWAY_ZAIRAI_FILTER_STATE_PATH,
                current_zairai_events,
            )
            result = {
                "generated_at": now_iso(),
                "model": "python:railway_pre_llm_filter",
                "comment": "",
                "railway_beta_alerts": railway_beta_alerts,
                "railway_beta_display_alerts": railway_beta_display_alerts,
                "railway_beta_previous_alerts": previous_railway_alerts,
                "railway_beta_previous_display_alerts": [
                    display_railway_alert(alert) for alert in previous_railway_alerts
                ],
                "railway_beta_source_urls": railway_source_url_by_alert,
                "railway_beta_levels": railway_level_by_alert,
                "railway_beta_change_type": railway_pre_notify_reason,
                "railway_beta_notification": False,
                "railway_notify_allowed": False,
                "railway_official_hash": railway_official_current_hash,
                "severity": railway_severity,
                "weather_beta_alerts": weather_beta_alerts,
                "weather_severity": weather_severity,
                "done": False,
                "ollama_skipped": True,
                "llm_skipped": True,
                "silent_reason": railway_pre_notify_reason,
            }
            write_comment_result(result, "")
            log(f"railway_notify_suppressed: {railway_pre_notify_reason}")
            log(f"railway_llm_skipped: true reason={railway_pre_notify_reason}")
            record_weather_decision(
                weather_snapshot,
                now=now_jst,
                severity=weather_severity,
                notify_allowed=False,
                suppress_reason=f"railway_{railway_pre_notify_reason}",
            )
            log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {RAILWAY_STATE_PATH.relative_to(ROOT)}")
            return 0

        if railway_pre_notify_reason == "recovered_silent":
            save_railway_state(
                RAILWAY_STATE_PATH,
                railway_beta_alerts,
                now_jst,
                railway_level_by_alert,
                morning_reposted_date,
                incident_first_seen_at,
                critical_transport_recovered_at=next_critical_transport_recovered_at,
                official_hash=railway_official_current_hash,
                impact=current_railway_impact,
            )
            save_structured_filter_state(
                RAILWAY_ZAIRAI_FILTER_STATE_PATH,
                current_zairai_events,
            )
            result = {
                "generated_at": now_iso(),
                "model": "python:railway_pre_llm_filter",
                "comment": "",
                "railway_beta_alerts": railway_beta_alerts,
                "railway_beta_display_alerts": railway_beta_display_alerts,
                "railway_beta_previous_alerts": previous_railway_alerts,
                "railway_beta_previous_display_alerts": [
                    display_railway_alert(alert) for alert in previous_railway_alerts
                ],
                "railway_beta_change_type": "recovered_silent",
                "railway_beta_notification": False,
                "railway_notify_allowed": False,
                "railway_official_hash": railway_official_current_hash,
                "severity": railway_severity,
                "weather_beta_alerts": weather_beta_alerts,
                "weather_severity": weather_severity,
                "done": False,
                "ollama_skipped": True,
                "llm_skipped": True,
                "silent_reason": "recovered_silent",
            }
            write_comment_result(result, "")
            log("railway_beta_comment: recovered_silent")
            record_weather_decision(
                weather_snapshot,
                now=now_jst,
                severity=weather_severity,
                notify_allowed=False,
                suppress_reason="railway_recovered_silent",
            )
            log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {RAILWAY_STATE_PATH.relative_to(ROOT)}")
            return 0

        if railway_pre_notify_reason == "major_incident":
            log("railway_notify_allowed: major_incident")

        comment, change_type, added_alerts, removed_alerts = build_railway_state_comment(
            state_exists,
            previous_railway_alerts,
            railway_beta_alerts,
            now_jst,
            railway_updated_at_by_alert,
            railway_source_url_by_alert,
            previous_zairai_events,
            current_zairai_events,
        )
        carryover_alerts, carryover_reason = morning_carryover_repost_candidates(
            previous_alerts=previous_railway_alerts,
            current_alerts=railway_beta_alerts,
            now=now_jst,
            morning_reposted_date=morning_reposted_date,
            incident_first_seen_at=incident_first_seen_at,
            last_notify=last_notify,
        )
        if change_type == "unchanged" and not comment and carryover_alerts:
            comment = build_railway_beta_comment(
                carryover_alerts,
                now_jst,
                railway_updated_at_by_alert,
                railway_source_url_by_alert,
            )
            change_type = "carryover_morning_repost"
            added_alerts = carryover_alerts
            removed_alerts = []
            morning_reposted_date = now_jst.date().isoformat()
            log(
                "morning_carryover_repost: true "
                f"reason={carryover_reason}"
            )
        else:
            if change_type != "unchanged":
                carryover_reason = "regular_change_takes_priority"
            log(
                "morning_carryover_repost: false "
                f"reason={carryover_reason}"
            )
        save_railway_state(
            RAILWAY_STATE_PATH,
            railway_beta_alerts,
            now_jst,
            railway_level_by_alert,
            morning_reposted_date,
            incident_first_seen_at,
            critical_transport_recovered_at=next_critical_transport_recovered_at,
            official_hash=railway_official_current_hash,
            impact=current_railway_impact,
        )
        save_structured_filter_state(
            RAILWAY_ZAIRAI_FILTER_STATE_PATH,
            current_zairai_events,
        )
        record_railway_history_change(
            RAILWAY_HISTORY_PATH,
            previous_railway_alerts,
            railway_beta_alerts,
            change_type,
            now_jst,
        )
        if change_type == "recovered":
            if railway_pre_notify_reason == "major_recovered":
                notification_severity = "recovery"
                notify_allowed, cooldown_remaining = railway_notify_allowed(
                    last_notify,
                    notification_severity,
                    now_jst,
                    change_type,
                )
                comment = ""
                if notify_allowed:
                    comment = "🔵 鉄道運行情報\n\n前回の障害は平常運転に戻りました。"
                    save_railway_last_notify(
                        RAILWAY_LAST_NOTIFY_PATH,
                        notification_severity,
                        now_jst,
                    )
                    log("railway_notify_allowed: major_recovered")
                else:
                    log(
                        "railway_notify_suppressed: cooldown "
                        f"{notification_severity} {cooldown_remaining}s remaining"
                    )
                ok, errors = validate_railway_beta_comment(comment)
                if not ok:
                    log(f"railway_beta_comment_guard: {errors}")
                    comment = ""
                result = {
                    "generated_at": now_iso(),
                    "model": "python:railway_beta_state_diff",
                    "comment": comment,
                    "railway_beta_alerts": railway_beta_alerts,
                    "railway_beta_display_alerts": railway_beta_display_alerts,
                    "railway_beta_previous_alerts": previous_railway_alerts,
                    "railway_beta_previous_display_alerts": [
                        display_railway_alert(alert) for alert in previous_railway_alerts
                    ],
                    "railway_beta_added_alerts": added_alerts,
                    "railway_beta_added_display_alerts": [
                        display_railway_alert(alert) for alert in added_alerts
                    ],
                    "railway_beta_removed_alerts": removed_alerts,
                    "railway_beta_removed_display_alerts": [
                        display_railway_alert(alert) for alert in removed_alerts
                    ],
                    "railway_beta_source_urls": railway_source_url_by_alert,
                    "railway_beta_levels": railway_level_by_alert,
                    "railway_beta_change_type": "recovered",
                    "railway_beta_notification": bool(comment),
                    "railway_notify_allowed": bool(comment) and notify_allowed,
                    "railway_notify_cooldown_remaining_seconds": (
                        cooldown_remaining if not notify_allowed else 0
                    ),
                    "severity": notification_severity,
                    "weather_beta_alerts": weather_beta_alerts,
                    "weather_severity": weather_severity,
                    "done": bool(comment),
                    "ollama_skipped": True,
                    "llm_skipped": True,
                }
                write_comment_result(result, comment)
                record_weather_decision(
                    weather_snapshot,
                    now=now_jst,
                    severity=weather_severity,
                    notify_allowed=False,
                    suppress_reason=(
                        "railway_recovery_notification"
                        if comment
                        else "railway_recovery_no_notification"
                    ),
                )
                log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
                log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
                log(f"wrote: {RAILWAY_STATE_PATH.relative_to(ROOT)}")
                return 0

            result = {
                "generated_at": now_iso(),
                "model": "python:railway_beta_state_diff",
                "comment": "",
                "railway_beta_alerts": railway_beta_alerts,
                "railway_beta_display_alerts": railway_beta_display_alerts,
                "railway_beta_previous_alerts": previous_railway_alerts,
                "railway_beta_previous_display_alerts": [
                    display_railway_alert(alert) for alert in previous_railway_alerts
                ],
                "railway_beta_added_alerts": added_alerts,
                "railway_beta_added_display_alerts": [
                    display_railway_alert(alert) for alert in added_alerts
                ],
                "railway_beta_removed_alerts": removed_alerts,
                "railway_beta_removed_display_alerts": [
                    display_railway_alert(alert) for alert in removed_alerts
                ],
                "railway_beta_source_urls": railway_source_url_by_alert,
                "railway_beta_levels": railway_level_by_alert,
                "railway_beta_change_type": "recovered_silent",
                "railway_beta_notification": False,
                "railway_notify_allowed": False,
                "severity": railway_severity,
                "weather_beta_alerts": weather_beta_alerts,
                "weather_severity": weather_severity,
                "done": False,
                "ollama_skipped": True,
                "llm_skipped": True,
            }
            write_comment_result(result, "")
            log("railway_beta_comment: recovered_silent")
            record_weather_decision(
                weather_snapshot,
                now=now_jst,
                severity=weather_severity,
                notify_allowed=False,
                suppress_reason="railway_recovered_silent",
            )
            log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {RAILWAY_STATE_PATH.relative_to(ROOT)}")
            return 0

        if comment or change_type == "changed":
            notification_severity = detect_railway_severity(railway_beta_alerts or removed_alerts)
            notify_allowed, cooldown_remaining = railway_notify_allowed(
                last_notify,
                notification_severity,
                now_jst,
                change_type,
            )
            if comment and not notify_allowed:
                log(f"railway_notify_suppressed: cooldown {notification_severity} {cooldown_remaining}s remaining")
                comment = ""
            elif comment and change_type != "unchanged":
                log("railway_notify_allowed: state changed")
            elif comment:
                log("railway_notify_allowed: yes")

            ok, errors = validate_railway_beta_comment(comment)
            if not ok:
                log(f"railway_beta_comment_guard: {errors}")
                comment = ""
            if comment:
                save_railway_last_notify(
                    RAILWAY_LAST_NOTIFY_PATH,
                    "recovery" if change_type == "recovered" else notification_severity,
                    now_jst,
                )
                if 5 <= now_jst.hour < 6:
                    morning_reposted_date = now_jst.date().isoformat()
                    save_railway_state(
                        RAILWAY_STATE_PATH,
                        railway_beta_alerts,
                        now_jst,
                        railway_level_by_alert,
                        morning_reposted_date,
                        incident_first_seen_at,
                        critical_transport_recovered_at=next_critical_transport_recovered_at,
                        official_hash=railway_official_current_hash,
                        impact=current_railway_impact,
                    )
            result = {
                "generated_at": now_iso(),
                "model": "python:railway_beta_state_diff",
                "comment": comment,
                "railway_beta_alerts": railway_beta_alerts,
                "railway_beta_display_alerts": railway_beta_display_alerts,
                "railway_beta_previous_alerts": previous_railway_alerts,
                "railway_beta_previous_display_alerts": [
                    display_railway_alert(alert) for alert in previous_railway_alerts
                ],
                "railway_beta_added_alerts": added_alerts,
                "railway_beta_added_display_alerts": [
                    display_railway_alert(alert) for alert in added_alerts
                ],
                "railway_beta_removed_alerts": removed_alerts,
                "railway_beta_removed_display_alerts": [
                    display_railway_alert(alert) for alert in removed_alerts
                ],
                "railway_beta_source_urls": railway_source_url_by_alert,
                "railway_beta_levels": railway_level_by_alert,
                "railway_beta_change_type": change_type,
                "railway_beta_change_reason": (
                    carryover_reason
                    if change_type == "carryover_morning_repost"
                    else ""
                ),
                "morning_reposted_date": morning_reposted_date,
                "railway_beta_notification": bool(comment),
                "railway_notify_allowed": bool(comment) and notify_allowed,
                "railway_notify_cooldown_remaining_seconds": cooldown_remaining if not notify_allowed else 0,
                "severity": notification_severity,
                "weather_beta_alerts": weather_beta_alerts,
                "weather_severity": weather_severity,
                "done": bool(comment),
                "ollama_skipped": True,
            }

            write_comment_result(result, comment)
            if comment:
                log(f"railway_beta_comment: {change_type}")
            elif change_type == "changed":
                log("railway_beta_comment: removed_silent")
            else:
                log("railway_beta_comment: no change")
            record_weather_decision(
                weather_snapshot,
                now=now_jst,
                severity=weather_severity,
                notify_allowed=False,
                suppress_reason=(
                    "railway_notification_takes_priority"
                    if comment
                    else "railway_state_diff_no_weather_notification"
                ),
            )
            log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {RAILWAY_STATE_PATH.relative_to(ROOT)}")
            return 0

    if is_gemma_quiet_hours(now_jst) and not allow_gemma_during_quiet_hours(
        railway_beta_alerts,
        weather_beta_alerts,
    ):
        result = {
            "generated_at": now_iso(),
            "model": "python:silent_quiet_hours",
            "comment": "",
            "railway_beta_alerts": railway_beta_alerts,
            "railway_beta_display_alerts": railway_beta_display_alerts,
            "railway_beta_source_urls": railway_source_url_by_alert,
            "railway_beta_levels": railway_level_by_alert,
            "severity": railway_severity,
            "weather_beta_alerts": weather_beta_alerts,
            "weather_severity": weather_severity,
            "done": False,
            "ollama_skipped": True,
            "silent_reason": "quiet_hours",
        }
        write_comment_result(result, "")
        log("gemma_comment: skipped quiet_hours")
        record_weather_decision(
            weather_snapshot,
            now=now_jst,
            severity=weather_severity,
            notify_allowed=False,
            suppress_reason="quiet_hours",
        )
        log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
        log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    if is_minor_weather_only(railway_beta_alerts, weather_beta_alerts):
        result = {
            "generated_at": now_iso(),
            "model": "python:silent_minor_weather",
            "comment": "",
            "railway_beta_alerts": railway_beta_alerts,
            "railway_beta_display_alerts": railway_beta_display_alerts,
            "railway_beta_source_urls": railway_source_url_by_alert,
            "railway_beta_levels": railway_level_by_alert,
            "severity": railway_severity,
            "weather_beta_alerts": weather_beta_alerts,
            "weather_severity": weather_severity,
            "done": False,
            "ollama_skipped": True,
            "silent_reason": "minor_weather_only",
        }
        write_comment_result(result, "")
        log("gemma_comment: skipped minor_weather_only")
        record_weather_decision(
            weather_snapshot,
            now=now_jst,
            severity=weather_severity,
            notify_allowed=False,
            suppress_reason="minor_weather_only",
        )
        log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
        log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    if weather_beta_alerts and weather_change == "no change":
        result = {
            "generated_at": now_iso(),
            "model": "python:weather_beta_no_change",
            "comment": "",
            "weather_beta_alerts": weather_beta_alerts,
            "weather_severity": weather_severity,
            "weather_beta_notification": False,
            "done": False,
            "ollama_skipped": True,
        }
        write_comment_result(result, "")
        log("weather_beta_comment: no change")
        record_weather_decision(
            weather_snapshot,
            now=now_jst,
            severity=weather_severity,
            notify_allowed=False,
            suppress_reason="weather_no_change",
        )
        log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
        log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    if weather_beta_alerts and not railway_beta_alerts:
        comment = build_weather_beta_comment(weather_beta_alerts, weather_severity)
        result = {
            "generated_at": now_iso(),
            "model": "python:weather_beta",
            "comment": comment,
            "railway_beta_alerts": railway_beta_alerts,
            "railway_beta_display_alerts": railway_beta_display_alerts,
            "railway_beta_source_urls": railway_source_url_by_alert,
            "railway_beta_levels": railway_level_by_alert,
            "severity": railway_severity,
            "weather_beta_alerts": weather_beta_alerts,
            "weather_severity": weather_severity,
            "weather_beta_notification": bool(comment),
            "done": bool(comment),
            "ollama_skipped": True,
        }
        write_comment_result(result, comment)
        log(f"weather_beta_comment: {weather_change}")
        record_weather_decision(
            weather_snapshot,
            now=now_jst,
            severity=weather_severity,
            notify_allowed=bool(comment),
            suppress_reason="" if comment else "empty_weather_comment",
        )
        log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
        log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    if not should_generate_comment(report, railway_beta_alerts, weather_beta_alerts):
        result = {
            "generated_at": now_iso(),
            "model": "python:silent_empty",
            "comment": "",
            "railway_beta_alerts": railway_beta_alerts,
            "railway_beta_display_alerts": railway_beta_display_alerts,
            "railway_beta_source_urls": railway_source_url_by_alert,
            "railway_beta_levels": railway_level_by_alert,
            "severity": railway_severity,
            "weather_beta_alerts": weather_beta_alerts,
            "weather_severity": weather_severity,
            "done": False,
            "ollama_skipped": True,
            "silent_reason": "no_actionable_info",
        }
        write_comment_result(result, "")
        log("gemma_comment: skipped no_actionable_info")
        record_weather_decision(
            weather_snapshot,
            now=now_jst,
            severity=weather_severity,
            notify_allowed=False,
            suppress_reason="no_actionable_info",
        )
        log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
        log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    prompt = build_prompt(report, profile, railway_beta_alerts, weather_beta_alerts, style)
    response = call_ollama(prompt)

    if response is None:
        log("Gemma4B未起動")
        return 0

    comment = str(response.get("response", "")).strip()
    style_guard_reasons = gemma_style_guard_reasons(comment, style, report)
    if style_guard_reasons:
        log(f"gemma_style_guard_suppressed: {', '.join(style_guard_reasons)}")
        comment = ""
    ok, errors = validate_railway_beta_comment(comment)
    if not ok:
        log(f"comment_guard: {errors}")
        comment = ""
    result = {
        "generated_at": now_iso(),
        "model": MODEL,
        "comment": comment,
        "railway_beta_alerts": railway_beta_alerts,
        "railway_beta_display_alerts": railway_beta_display_alerts,
        "railway_beta_source_urls": railway_source_url_by_alert,
        "railway_beta_levels": railway_level_by_alert,
        "severity": railway_severity,
        "weather_beta_alerts": weather_beta_alerts,
        "weather_severity": weather_severity,
        "done": bool(response.get("done")) and bool(comment),
    }

    write_comment_result(result, comment)

    record_weather_decision(
        weather_snapshot,
        now=now_jst,
        severity=weather_severity,
        notify_allowed=bool(comment) and bool(weather_beta_alerts),
        suppress_reason="" if comment and weather_beta_alerts else "gemma_comment_empty_or_no_weather_alerts",
    )
    log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
    log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
