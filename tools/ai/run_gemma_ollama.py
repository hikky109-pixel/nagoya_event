#!/usr/bin/env python3
"""Ollama上のGemma 4Bでジェンマ課長コメントを生成する。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from railway_status_normalizer import get_all_railway_alerts
except ModuleNotFoundError:
    from tools.ai.railway_status_normalizer import get_all_railway_alerts

try:
    from tools.weather.weather_normalizer import get_all_weather_alerts
except ModuleNotFoundError:
    from weather_normalizer import get_all_weather_alerts


AI_DIR = ROOT / "data" / "ai"
REPORT_PATH = AI_DIR / "gemma_report.txt"
PROFILE_PATH = AI_DIR / "gemma_profile.yml"
TEXT_OUTPUT_PATH = AI_DIR / "gemma_comment.txt"
JSON_OUTPUT_PATH = AI_DIR / "gemma_comment.json"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"
RAILWAY_BETA_EXCLUDE_MARKERS = (
    "取得失敗",
    "運行情報提供停止",
)
JST = timezone(timedelta(hours=9), "JST")


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
    if not is_railway_beta_active(now):
        return []

    try:
        return public_railway_alerts(get_all_railway_alerts())
    except Exception:
        return []


def load_weather_beta_alerts(now: datetime | None = None) -> list[str]:
    try:
        return get_all_weather_alerts(now)
    except Exception:
        return []


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
- 朝礼、日報、挨拶、社内報告の文体は禁止です。
- 禁止語: おはようございます / 本日も / 状況を確認しました / 報告ありがとうございます / 〇〇さん / 皆さん / 引き続き / 慎重に進めましょう / 判断しましょう
- 交通情報ベータがある場合は、公共交通情報として挨拶なし・前置きなしで書いてください。
- 交通情報ベータがある場合は、3行以内にしてください。
- 箇条書きは使っても構いません。
- 書く内容は、取得できた事実 + 名古屋方面の移動/乗換影響のみです。
- 表現例:
🚋 JR東海道線
尾張一宮～木曽川駅間で列車遅延。
名古屋方面の移動・乗換に影響する可能性があります。
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
) -> str:
    profile_json = json.dumps(profile, ensure_ascii=False, indent=2)
    railway_alerts = railway_beta_alerts or []
    railway_beta_block = build_railway_beta_block(railway_alerts)
    weather_beta_block = build_weather_beta_block(weather_beta_alerts or [])
    railway_priority_rule = (
        "交通情報ベータがあるため、日報コメントではなく公共交通情報の掲示文を最優先で作ってください。\n"
        "プロフィール、挨拶、朝礼、雑談、ツッコミ、日報要約は出さないでください。"
        if railway_alerts
        else ""
    )
    return f"""あなたはジェンマ課長です。

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
- 上司・部下っぽい報告文にしない
- 鉄道遅延は、事実と名古屋方面の移動・乗換への影響可能性だけを短く伝える
- 交通情報ベータがある場合は公共交通情報として書き、挨拶なし・前置きなし・3行以内にする
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
    now_jst = datetime.now(JST)
    railway_beta_is_active = is_railway_beta_active(now_jst)
    railway_beta_alerts = load_railway_beta_alerts(now_jst)
    weather_beta_alerts = load_weather_beta_alerts(now_jst)
    if not railway_beta_is_active:
        print("railway_beta_alerts: skipped overnight")
    elif railway_beta_alerts:
        print(f"railway_beta_alerts: {len(railway_beta_alerts)}")
    else:
        print("railway_beta_alerts: 0")
    print(f"weather_beta_alerts: {len(weather_beta_alerts)}")
    prompt = build_prompt(report, profile, railway_beta_alerts, weather_beta_alerts)
    response = call_ollama(prompt)

    if response is None:
        print("Gemma4B未起動")
        return 0

    comment = str(response.get("response", "")).strip()
    result = {
        "generated_at": now_iso(),
        "model": MODEL,
        "comment": comment,
        "railway_beta_alerts": railway_beta_alerts,
        "weather_beta_alerts": weather_beta_alerts,
        "done": bool(response.get("done")),
    }

    AI_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_OUTPUT_PATH.write_text(comment + ("\n" if comment else ""), encoding="utf-8")
    with JSON_OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"wrote: {TEXT_OUTPUT_PATH.relative_to(ROOT)}")
    print(f"wrote: {JSON_OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
