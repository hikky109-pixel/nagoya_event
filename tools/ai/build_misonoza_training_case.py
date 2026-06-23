#!/usr/bin/env python3
"""御園座スクレイパー結果をGemma教育用ケースとして保存する。"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPECTED_PATH = ROOT / "csv_events" / "misonoza.csv"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "ai" / "training" / "misonoza"


def now_key() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")


def safe_case_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value.strip())
    return safe.strip("_") or f"misonoza_{now_key()}"


def default_case_id(expected_path: Path) -> str:
    return safe_case_id(f"{expected_path.stem}_{now_key()}")


def detect_delimiter(path: Path, sample: str) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    if path.suffix.lower() == ".csv":
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
    except csv.Error:
        return "\t" if "\t" in sample else ","
    return dialect.delimiter


def table_to_tsv(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return ""

    delimiter = detect_delimiter(path, text[:4096])
    rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
    output_lines: list[str] = []
    for row in rows:
        output_lines.append("\t".join(cell.strip() for cell in row))
    return "\n".join(output_lines).rstrip() + "\n"


def load_ocr_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() != ".json":
        return text.strip() + ("\n" if text.strip() else "")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text.strip() + ("\n" if text.strip() else "")

    if isinstance(data, dict):
        for key in ("ocr_text", "text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip() + "\n"
    return text.strip() + ("\n" if text.strip() else "")


def build_diff(expected_text: str, gemma_text: str | None) -> str:
    if gemma_text is None:
        return "gemma.tsv not provided\n"

    diff_lines = list(
        difflib.unified_diff(
            expected_text.splitlines(),
            gemma_text.splitlines(),
            fromfile="expected.tsv",
            tofile="gemma.tsv",
            lineterm="",
        )
    )
    if not diff_lines:
        return "no diff\n"
    return "\n".join(diff_lines) + "\n"


def write_training_case(
    expected_path: Path,
    output_dir: Path,
    case_id: str | None = None,
    ocr_path: Path | None = None,
    gemma_path: Path | None = None,
) -> dict[str, Path]:
    expected_path = expected_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    resolved_case_id = safe_case_id(case_id) if case_id else default_case_id(expected_path)

    expected_text = table_to_tsv(expected_path)
    gemma_text = table_to_tsv(gemma_path.expanduser().resolve()) if gemma_path is not None else None

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "expected": output_dir / f"{resolved_case_id}_expected.tsv",
        "diff": output_dir / f"{resolved_case_id}_diff.txt",
    }
    paths["expected"].write_text(expected_text, encoding="utf-8")

    if ocr_path is not None:
        paths["input_ocr"] = output_dir / f"{resolved_case_id}_input_ocr.txt"
        paths["input_ocr"].write_text(load_ocr_text(ocr_path.expanduser().resolve()), encoding="utf-8")

    if gemma_text is not None:
        paths["gemma"] = output_dir / f"{resolved_case_id}_gemma.tsv"
        paths["gemma"].write_text(gemma_text, encoding="utf-8")

    paths["diff"].write_text(build_diff(expected_text, gemma_text), encoding="utf-8")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="御園座Gemma教育用ケースを保存する。")
    parser.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED_PATH, help="正解CSV/TSV")
    parser.add_argument("--gemma", type=Path, default=None, help="Gemma出力CSV/TSV")
    parser.add_argument("--ocr", type=Path, default=None, help="OCR生テキストまたはOCRケースJSON")
    parser.add_argument("--case-id", default=None, help="保存ファイル名の接頭辞")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="ケース保存先")
    return parser.parse_args()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    paths = write_training_case(
        expected_path=args.expected,
        output_dir=args.output_dir,
        case_id=args.case_id,
        ocr_path=args.ocr,
        gemma_path=args.gemma,
    )
    for key in sorted(paths):
        print(f"wrote_{key}: {display_path(paths[key])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
