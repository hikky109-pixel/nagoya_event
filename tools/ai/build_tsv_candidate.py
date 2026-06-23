#!/usr/bin/env python3
"""OCR結果から人間確認用のTSV候補を生成する。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OCR_CASE_DIR = ROOT / "data" / "ai" / "ocr_case"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

sys.path.insert(0, str(ROOT))
from tools.ai.normalize_tsv import log_normalize_result, normalize_tsv_with_stats  # noqa: E402
from tools.ai.output_guard import validate_output  # noqa: E402
from tools.ai import tsv_memory  # noqa: E402


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def iter_ocr_cases() -> list[Path]:
    if not OCR_CASE_DIR.exists():
        return []
    return sorted(OCR_CASE_DIR.glob("*.json"))


def build_prompt(ocr_case: dict[str, Any]) -> str:
    source_json = json.dumps(ocr_case, ensure_ascii=False, indent=2)
    return f"""OCR結果です。

誤認識を含む可能性があります。

断定せず、
候補として扱ってください。

イベント情報と思われるものだけ抽出してください。

交通規制PDFでも、花火・祭り・公演など開催イベントが読み取れる場合は、イベント1件として抽出してください。

優先する時刻:
- 花火打上時刻
- 祭り、催事、式典の開始時刻
- 公演、ライブ、試合の開演/開始時刻

優先しない時刻:
- 交通規制開始/終了時刻
- 通行止め時間
- 迂回案内の時間
- 警備、設営、撤収の時間

交通規制の情報しか読めず、開催イベント名や開催時刻が分からない場合はTSV行を作らないでください。

TSV形式で出力してください。

列:
date
start_time
end_time
venue
title
status

status は candidate 固定。

ヘッダー行、説明文、Markdownコードブロックは不要です。
TSV行だけを出力してください。

OCR case:
{source_json}
"""


def call_ollama(prompt: str) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 500},
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


def process_ocr_case(path: Path) -> dict[str, Any] | None:
    ocr_case = load_json(path)
    if not isinstance(ocr_case, dict):
        return None
    ocr_text = str(ocr_case.get("ocr_text", "")).strip()
    if not ocr_text or ocr_text.startswith("OCR失敗"):
        return None

    response = call_ollama(build_prompt(ocr_case))
    if response is None:
        return {"error": "Gemma4B未起動"}

    ok, errors = validate_output(ocr_text, response)
    if ok:
        print("gemma_output_guard: ok")
    else:
        print("gemma_output_guard:")
        print(errors)
        print("gemma hallucination:", errors)
        response = ""

    normalized = normalize_tsv_with_stats(response, source_text=ocr_text)
    log_normalize_result(normalized)
    tsv_text = normalized.text
    tsv_path, json_path, meta = tsv_memory.save_tsv_candidate(str(path.relative_to(ROOT)), tsv_text)
    return {
        "tsv_path": str(tsv_path.relative_to(ROOT)),
        "json_path": str(json_path.relative_to(ROOT)),
        "rows": meta["rows"],
    }


def main() -> int:
    processed = 0
    total_rows = 0
    for path in iter_ocr_cases():
        result = process_ocr_case(path)
        if result is None:
            continue
        if result.get("error") == "Gemma4B未起動":
            print("Gemma4B未起動")
            return 0
        processed += 1
        total_rows += int(result["rows"])
        print(f"wrote: {result['tsv_path']}")
        print(f"wrote: {result['json_path']}")

    print(f"tsv_candidates: {processed}")
    print(f"rows: {total_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
