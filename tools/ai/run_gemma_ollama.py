#!/usr/bin/env python3
"""Ollama上のGemma 4Bでジェンマ課長コメントを生成する。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / "data" / "ai"
REPORT_PATH = AI_DIR / "gemma_report.txt"
PROFILE_PATH = AI_DIR / "gemma_profile.yml"
TEXT_OUTPUT_PATH = AI_DIR / "gemma_comment.txt"
JSON_OUTPUT_PATH = AI_DIR / "gemma_comment.json"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"


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


def build_prompt(report: str, profile: dict[str, Any]) -> str:
    profile_json = json.dumps(profile, ensure_ascii=False, indent=2)
    return f"""あなたはジェンマ課長です。

以下のプロフィールと日報をもとに、短いコメントだけを作ってください。

生成ルール:
- 3～5行
- 箇条書き中心
- 自信がない内容は断定しない
- 候補は candidate とする
- 本番データを勝手に確定しない
- 運転再開≠復旧
- ツッコミは最大1回
- スギケツバットは毎回出さない

profile:
{profile_json}

report:
{report}
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
    prompt = build_prompt(report, profile)
    response = call_ollama(prompt)

    if response is None:
        print("Gemma4B未起動")
        return 0

    comment = str(response.get("response", "")).strip()
    result = {
        "generated_at": now_iso(),
        "model": MODEL,
        "comment": comment,
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
