#!/usr/bin/env python3
"""1時間ごとの運行日誌を1日単位の日誌へまとめる。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
DAILY_MEMORY_DIR = AI_DIR / "daily_memory"
DAILY_SUMMARY_DIR = AI_DIR / "daily_summary"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"


def today_key() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def build_prompt(date_key: str, daily_memory: dict[str, Any]) -> str:
    source_json = json.dumps(daily_memory, ensure_ascii=False, indent=2)
    return f"""あなたはジェンマ課長です。

data/ai/daily_memory/{date_key}.json に蓄積された1時間ごとの要約を、1日単位の日誌にまとめてください。

出力形式:
🤖 ジェンマ課長日誌 {date_key}

・...
・...

ひとこと:
...

ルール:
- 3〜7行程度
- 不明なことは断定しない
- ログが少ない場合は「未確認」と明示する
- candidate を利用する
- ツッコミは最大1回
- スギケツバットは毎回出さない
- 本番データを勝手に確定しない
- 運転再開≠復旧

daily_memory:
{source_json}
"""


def call_ollama(prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 320},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None

    data = json.loads(response_body)
    if not isinstance(data, dict):
        return ""
    return str(data.get("response", "")).strip()


def normalize_daily_summary(date_key: str, text: str) -> str:
    blocked_phrases = ("特筆すべき", "異常な兆候")
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not any(phrase in line for phrase in blocked_phrases)
    ]
    if not lines:
        lines = [
            f"🤖 ジェンマ課長日誌 {date_key}",
            "・日次記憶はありますが、要約内容は未確認です。",
            "・candidate: 追加ログがあれば再要約します。",
        ]

    if not lines[0].startswith("🤖 ジェンマ課長日誌"):
        lines.insert(0, f"🤖 ジェンマ課長日誌 {date_key}")

    body = lines[1:]
    normalized_body: list[str] = []
    comment_seen = False
    for line in body:
        if line.startswith("ひとこと"):
            if comment_seen:
                continue
            comment_seen = True
            normalized_body.append("ひとこと:")
            continue
        if line == "運転再開≠復旧です😇" and not comment_seen:
            normalized_body.extend(["ひとこと:", line])
            comment_seen = True
            continue
        if line.startswith(("・", "-", "*", "ひとこと")):
            normalized_body.append(line)
        else:
            normalized_body.append(f"・{line}")

    if normalized_body and normalized_body[-1] == "ひとこと:":
        normalized_body.pop()

    compact = [lines[0], *normalized_body]
    return "\n".join(compact[:9]).rstrip() + "\n"


def write_outputs(date_key: str, summary_text: str, source_path: Path) -> None:
    DAILY_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = DAILY_SUMMARY_DIR / f"{date_key}.txt"
    json_path = DAILY_SUMMARY_DIR / f"{date_key}.json"
    txt_path.write_text(summary_text, encoding="utf-8")

    payload = {
        "date": date_key,
        "model": MODEL,
        "source": str(source_path.relative_to(ROOT)),
        "summary": summary_text,
    }
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"wrote: {txt_path.relative_to(ROOT)}")
    print(f"wrote: {json_path.relative_to(ROOT)}")


def main() -> int:
    date_key = sys.argv[1] if len(sys.argv) > 1 else today_key()
    memory_path = DAILY_MEMORY_DIR / f"{date_key}.json"
    if not memory_path.exists():
        print("日次記憶なし")
        return 0

    daily_memory = load_json(memory_path)
    if not isinstance(daily_memory, dict):
        print("日次記憶なし")
        return 0

    summary = call_ollama(build_prompt(date_key, daily_memory))
    if summary is None:
        print("Gemma4B未起動")
        return 0

    summary_text = normalize_daily_summary(date_key, summary)
    write_outputs(date_key, summary_text, memory_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
