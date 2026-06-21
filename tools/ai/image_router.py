#!/usr/bin/env python3
"""Discord画像添付をOCR前の案件として分類・保存する。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT))
from tools.ai import image_memory  # noqa: E402


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
FILE_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}


def classify_image(filename: str, content_type: str = "", message_text: str = "") -> str:
    text = f"{filename} {content_type} {message_text}".lower()
    if any(word in text for word in ("schedule", "スケジュール", "日程", "予定", "calendar")):
        return "schedule"
    if any(word in text for word in ("table", "表", "一覧", "csv", "tsv")):
        return "table"
    if any(word in text for word in ("screenshot", "スクショ", "画面", "ss")):
        return "screenshot"
    if any(word in text for word in ("document", "資料", "書類", "pdf")):
        return "document"
    return "unknown"


def is_image_attachment(attachment: Any) -> bool:
    filename = str(getattr(attachment, "filename", "") or "")
    content_type = str(getattr(attachment, "content_type", "") or "")
    suffix = Path(filename).suffix.lower()
    return suffix in FILE_EXTENSIONS or content_type.startswith("image/") or content_type == "application/pdf"


def build_case_from_attachment(message: Any, attachment: Any, local_path: str = "") -> dict[str, Any]:
    filename = str(getattr(attachment, "filename", "") or "")
    content_type = str(getattr(attachment, "content_type", "") or "")
    message_text = str(getattr(message, "content", "") or "")
    created_at = getattr(message, "created_at", None)
    if created_at is None:
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    else:
        timestamp = created_at.astimezone().isoformat(timespec="seconds")

    return {
        "type": classify_image(filename, content_type, message_text),
        "filename": filename,
        "url": str(getattr(attachment, "url", "") or ""),
        "local_path": local_path,
        "content_type": content_type,
        "channel": str(getattr(getattr(message, "channel", None), "name", "") or ""),
        "channel_id": str(getattr(getattr(message, "channel", None), "id", "") or ""),
        "message_id": str(getattr(message, "id", "") or ""),
        "timestamp": timestamp,
    }


def save_message_image_cases(message: Any, local_paths: dict[str, str] | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    local_paths = local_paths or {}
    for attachment in getattr(message, "attachments", []) or []:
        if not is_image_attachment(attachment):
            continue
        filename = str(getattr(attachment, "filename", "") or "")
        local_path = local_paths.get(filename, "")
        case = build_case_from_attachment(message, attachment, local_path=local_path)
        path = image_memory.save_image_case(case)
        case["saved_path"] = str(path.relative_to(ROOT))
        cases.append(case)
    return cases


def build_gemma_image_note(case: dict[str, Any]) -> str:
    recent_cases = image_memory.load_recent_cases()
    return "\n".join(
        [
            "画像案件です。",
            "",
            f"種別は {case.get('type', 'unknown')} の可能性があります。",
            "",
            "過去事例も参照してください。",
            f"recent_cases: {json.dumps(recent_cases, ensure_ascii=False)}",
            "",
            "不明なら断定しないこと。",
        ]
    )


def main() -> int:
    payload = sys.stdin.read().strip()
    if not payload:
        print("画像案件入力なし")
        return 0
    data = json.loads(payload)
    if not isinstance(data, dict):
        print("画像案件入力なし")
        return 0
    path = image_memory.save_image_case(data)
    print(f"wrote: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
