#!/usr/bin/env python3
"""Ollama上のGemma 4Bでジェンマ課長コメントを生成する。"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from jrc_zairai_targets import jrc_target_line_display, jrc_target_line_url
    from log_utils import log
    from railway_history import record_railway_history_change
    from railway_status_normalizer import get_all_railway_alerts_snapshot
    from railway_severity import detect_railway_severity
    from railway_state import (
        diff_alerts,
        load_railway_last_notify,
        load_railway_state,
        railway_notify_allowed,
        save_railway_last_notify,
        save_railway_state,
    )
except ModuleNotFoundError:
    from tools.ai.jrc_zairai_targets import jrc_target_line_display, jrc_target_line_url
    from tools.ai.log_utils import log
    from tools.ai.railway_history import record_railway_history_change
    from tools.ai.railway_status_normalizer import get_all_railway_alerts_snapshot
    from tools.ai.railway_severity import detect_railway_severity
    from tools.ai.railway_state import (
        diff_alerts,
        load_railway_last_notify,
        load_railway_state,
        railway_notify_allowed,
        save_railway_last_notify,
        save_railway_state,
    )

try:
    from tools.weather.weather_normalizer import get_all_weather_alerts
except ModuleNotFoundError:
    from weather_normalizer import get_all_weather_alerts


AI_DIR = ROOT / "data" / "ai"
REPORT_PATH = AI_DIR / "gemma_report.txt"
PROFILE_PATH = AI_DIR / "gemma_profile.yml"
STYLE_PATH = ROOT / "config" / "gemma_style.yml"
TEXT_OUTPUT_PATH = AI_DIR / "gemma_comment.txt"
JSON_OUTPUT_PATH = AI_DIR / "gemma_comment.json"
RAILWAY_STATE_PATH = AI_DIR / "railway_beta_state.json"
RAILWAY_LAST_NOTIFY_PATH = AI_DIR / "railway_beta_last_notify.json"
RAILWAY_HISTORY_PATH = AI_DIR / "railway_history.yml"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"
RAILWAY_BETA_EXCLUDE_MARKERS = (
    "取得失敗",
    "運行情報提供停止",
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
    return "【Gemma出力スタイル】\n" + json.dumps(style, ensure_ascii=False, indent=2)


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
    data: dict[str, Any] = {}
    current_list: str | None = None

    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- "):
                if current_list is None:
                    raise ValueError(f"List item without a key in {path.relative_to(ROOT)}.")
                data[current_list].append(stripped[2:])
                continue
            if ":" not in stripped:
                raise ValueError(f"Unsupported YAML line in {path.relative_to(ROOT)}: {stripped}")
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                data[key] = value
                current_list = None
            else:
                data[key] = []
                current_list = key
    return data


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


def is_railway_beta_active(now: datetime | None = None) -> bool:
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is not None:
        now = now.astimezone(JST)

    current_time = now.time()
    return current_time >= time(5, 0) or current_time < time(1, 0)


def load_railway_beta_alerts(now: datetime | None = None) -> list[str]:
    alerts, _updated_at_by_alert, _source_url_by_alert, _level_by_alert = load_railway_beta_snapshot(now)
    return alerts


def load_railway_beta_snapshot(
    now: datetime | None = None,
) -> tuple[list[str], dict[str, datetime], dict[str, str], dict[str, str]]:
    if not is_railway_beta_active(now):
        return [], {}, {}, {}

    try:
        alerts, updated_at_by_alert, source_url_by_alert, level_by_alert = get_all_railway_alerts_snapshot()
        public_alerts = public_railway_alerts(alerts)
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


def railway_info_source(alert: str, source_url: str = "") -> tuple[str, str, str]:
    if "東海道新幹線" in alert:
        return "JR東海道新幹線", "JR東海道新幹線", RAILWAY_INFO_URLS["JR東海道新幹線"]
    if "JR東海在来線" in alert:
        display = jrc_target_line_display(alert)
        url = jrc_target_line_url(alert)
        if display and url:
            title = f"JR {display}"
            url_label = "JR " + display.splitlines()[0]
            return title, url_label, url
        return "JR 在来線", "JR 在来線", RAILWAY_INFO_URLS["JR東海在来線"]
    meitetsu_match = re.match(r"名鉄\s+([^:：]+)[:：]", alert)
    if meitetsu_match:
        line = " ".join(meitetsu_match.group(1).split())
        title = f"名鉄{line}"
        return title, title, source_url or RAILWAY_INFO_URLS["名鉄"]
    for label in (
        "名鉄",
        "名古屋市営地下鉄",
        "近鉄",
        "あおなみ線",
        "リニモ",
        "城北線",
    ):
        if label in alert:
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
    return [f"・{message}" for message in messages]


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
            f"（{timestamp:%H:%M}現在）",
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
            f"（{timestamp:%H:%M}現在）",
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
) -> tuple[str, str, list[str], list[str]]:
    added_alerts, removed_alerts = diff_alerts(previous_alerts, current_alerts)
    if not state_exists and current_alerts:
        return (
            build_railway_beta_comment(
                current_alerts,
                checked_at,
                updated_at_by_alert,
                source_url_by_alert,
            ),
            "initial",
            current_alerts,
            [],
        )
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


def is_empty_status_comment(comment: str, forbidden_phrases: list[str] | None = None) -> bool:
    text = " ".join(str(comment or "").split())
    if not text:
        return True
    markers = [*COMMENT_NO_SIGNAL_MARKERS, *(forbidden_phrases or [])]
    return any(marker in text for marker in markers)


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
    style_forbidden_phrases = gemma_style_phrases(style)
    now_jst = datetime.now(JST)
    railway_beta_is_active = is_railway_beta_active(now_jst)
    (
        railway_beta_alerts,
        railway_updated_at_by_alert,
        railway_source_url_by_alert,
        railway_level_by_alert,
    ) = load_railway_beta_snapshot(now_jst)
    railway_beta_display_alerts = [
        display_railway_alert(alert) for alert in railway_beta_alerts
    ]
    weather_beta_alerts = load_weather_beta_alerts(now_jst)
    if not railway_beta_is_active:
        log("railway_beta_alerts: skipped overnight")
    elif railway_beta_alerts:
        log(f"railway_beta_alerts: {len(railway_beta_alerts)}")
    else:
        log("railway_beta_alerts: 0")
    log(f"weather_beta_alerts: {len(weather_beta_alerts)}")

    if not railway_beta_is_active:
        log("railway_beta_comment: skipped overnight")
        railway_severity = detect_railway_severity([])
    else:
        state_exists, previous_railway_alerts = load_railway_state(RAILWAY_STATE_PATH)
        last_notify = load_railway_last_notify(RAILWAY_LAST_NOTIFY_PATH)
        railway_severity = detect_railway_severity(railway_beta_alerts or previous_railway_alerts)
        save_railway_state(RAILWAY_STATE_PATH, railway_beta_alerts, now_jst, railway_level_by_alert)
        comment, change_type, added_alerts, removed_alerts = build_railway_state_comment(
            state_exists,
            previous_railway_alerts,
            railway_beta_alerts,
            now_jst,
            railway_updated_at_by_alert,
            railway_source_url_by_alert,
        )
        record_railway_history_change(
            RAILWAY_HISTORY_PATH,
            previous_railway_alerts,
            railway_beta_alerts,
            change_type,
            now_jst,
        )
        if change_type == "recovered":
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
                "done": False,
                "ollama_skipped": True,
            }
            write_comment_result(result, "")
            log("railway_beta_comment: recovered_silent")
            log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
            log(f"wrote: {RAILWAY_STATE_PATH.relative_to(ROOT)}")
            return 0

        if comment or change_type in ("changed", "unchanged"):
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
                "railway_beta_notification": bool(comment),
                "railway_notify_allowed": bool(comment) and notify_allowed,
                "railway_notify_cooldown_remaining_seconds": cooldown_remaining if not notify_allowed else 0,
                "severity": notification_severity,
                "weather_beta_alerts": weather_beta_alerts,
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
            "done": False,
            "ollama_skipped": True,
            "silent_reason": "quiet_hours",
        }
        write_comment_result(result, "")
        log("gemma_comment: skipped quiet_hours")
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
            "done": False,
            "ollama_skipped": True,
            "silent_reason": "no_actionable_info",
        }
        write_comment_result(result, "")
        log("gemma_comment: skipped no_actionable_info")
        log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
        log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    prompt = build_prompt(report, profile, railway_beta_alerts, weather_beta_alerts, style)
    response = call_ollama(prompt)

    if response is None:
        log("Gemma4B未起動")
        return 0

    comment = str(response.get("response", "")).strip()
    if is_empty_status_comment(comment, style_forbidden_phrases):
        log("gemma_comment_guard: empty_status_comment")
        comment = ""
    if railway_beta_alerts:
        ok, errors = validate_railway_beta_comment(comment)
        if not ok:
            log(f"railway_beta_comment_guard: {errors}")
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
        "done": bool(response.get("done")) and bool(comment),
    }

    write_comment_result(result, comment)

    log(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
    log(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
