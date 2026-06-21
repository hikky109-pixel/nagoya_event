#!/usr/bin/env python3
"""画像案件からOCRテキストを抽出する。"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
IMAGE_CASE_DIR = ROOT / "data" / "ai" / "image_case"
TARGET_TYPES = {"schedule", "table", "document"}

sys.path.insert(0, str(ROOT))
from tools.ai import ocr_memory  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def download_image(url: str, suffix: str = "") -> Path | None:
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".img")
    with temp:
        temp.write(data)
    return Path(temp.name)


def is_pdf_case(image_case: dict[str, Any]) -> bool:
    kind = str(image_case.get("kind", "")).lower()
    filename = str(image_case.get("filename", "")).lower()
    content_type = str(image_case.get("content_type", "")).lower()
    return kind == "pdf" or filename.endswith(".pdf") or content_type == "application/pdf"


def run_tesseract(image_path: Path) -> tuple[str, str, str]:
    from PIL import Image

    with Image.open(image_path) as image:
        return run_tesseract_on_pil(image)


def run_pdf_ocr(pdf_path: Path, max_pages: int = 2) -> tuple[str, int, str, str, str]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        return "", 0, f"pdf_render_failed: pypdfium2 not installed: {exc}", "jpn+eng", ""

    page_texts: list[str] = []
    pages_processed = 0
    ocr_lang = "jpn+eng"
    warning = ""
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        page_count = min(len(pdf), max_pages)
        for index in range(page_count):
            page = pdf[index]
            bitmap = page.render(scale=3)
            pil_image = bitmap.to_pil()
            text, page_lang, page_warning = run_tesseract_on_pil(pil_image)
            if page_warning:
                warning = page_warning
                ocr_lang = page_lang
            page_texts.append(f"— page {index + 1} —\n{text}")
            pages_processed += 1
    except Exception as exc:
        return "", pages_processed, f"pdf_render_failed: {exc}", ocr_lang, warning

    ocr_text = "\n\n".join(page_texts).strip()
    if not ocr_text:
        return "", pages_processed, "empty_ocr_text", ocr_lang, warning
    return ocr_text, pages_processed, "", ocr_lang, warning


def run_tesseract_on_pil(image: Any) -> tuple[str, str, str]:
    import pytesseract

    try:
        return pytesseract.image_to_string(image, lang="jpn+eng").strip(), "jpn+eng", ""
    except Exception:
        return pytesseract.image_to_string(image, lang="eng").strip(), "eng", "japanese_language_not_installed"


def build_ocr_case(
    image_case: dict[str, Any],
    image_case_path: Path,
    ocr_text: str,
    error: str = "",
    pages_processed: int = 1,
    ocr_lang: str = "jpn+eng",
    warning: str = "",
) -> dict[str, Any]:
    ocr_case = {
        "type": image_case.get("type", "unknown"),
        "image_case": str(image_case_path.relative_to(ROOT)),
        "ocr_text": ocr_text,
        "confidence": "unknown",
        "timestamp": now_iso(),
        "pages_processed": pages_processed,
        "ocr_lang": ocr_lang,
    }
    if error:
        ocr_case["error"] = error
    elif not ocr_text.strip():
        ocr_case["error"] = "empty_ocr_text"
    if warning:
        ocr_case["warning"] = warning
    return ocr_case


def process_image_case(path: Path) -> dict[str, Any] | None:
    image_case = load_json(path)
    if not isinstance(image_case, dict):
        return None
    if image_case.get("type") not in TARGET_TYPES:
        return None
    if ocr_memory.output_exists_for(str(path.relative_to(ROOT))):
        return None

    suffix = Path(str(image_case.get("filename", ""))).suffix
    local_path = ROOT / str(image_case.get("local_path", ""))
    image_path = local_path if str(image_case.get("local_path", "")) and local_path.exists() else None
    should_delete_image = False
    if image_path is None:
        url = str(image_case.get("url", ""))
        image_path = download_image(url, suffix=suffix)
        should_delete_image = image_path is not None
    if image_path is None:
        ocr_text = ""
        error = "download_failed"
        pages_processed = 0
        ocr_lang = "jpn+eng"
        warning = ""
    else:
        try:
            if is_pdf_case(image_case):
                ocr_text, pages_processed, error, ocr_lang, warning = run_pdf_ocr(image_path)
            else:
                ocr_text, ocr_lang, warning = run_tesseract(image_path)
                pages_processed = 1
                error = "empty_ocr_text" if not ocr_text.strip() else ""
        except Exception as exc:
            ocr_text = ""
            error = f"ocr_failed: {exc}"
            pages_processed = 0
            ocr_lang = "jpn+eng"
            warning = ""
        finally:
            if should_delete_image:
                try:
                    image_path.unlink()
                except OSError:
                    pass

    ocr_case = build_ocr_case(
        image_case,
        path,
        ocr_text,
        error=error,
        pages_processed=pages_processed,
        ocr_lang=ocr_lang,
        warning=warning,
    )
    saved_path = ocr_memory.save_ocr_case(ocr_case)
    ocr_case["saved_path"] = str(saved_path.relative_to(ROOT))
    return ocr_case


def iter_image_case_paths() -> list[Path]:
    if not IMAGE_CASE_DIR.exists():
        return []
    return sorted(IMAGE_CASE_DIR.glob("*.json"))


def build_gemma_ocr_note(ocr_case: dict[str, Any]) -> str:
    ocr_text = str(ocr_case.get("ocr_text", "")).strip()
    return "\n".join(
        [
            "OCR結果です。",
            "誤認識を含む可能性があります。",
            "断定せず、",
            "候補として扱ってください。",
            "",
            f"type: {ocr_case.get('type', 'unknown')}",
            f"ocr_text: {ocr_text[:1200] if ocr_text else '未取得'}",
        ]
    )


def main() -> int:
    processed = 0
    skipped = 0
    for path in iter_image_case_paths():
        result = process_image_case(path)
        if result is None:
            skipped += 1
            continue
        processed += 1
        print(f"wrote: {result['saved_path']}")

    print(f"ocr_processed: {processed}")
    print(f"ocr_skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
