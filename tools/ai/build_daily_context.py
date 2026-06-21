#!/usr/bin/env python3
"""Gemma向け daily_context.json を生成する。"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
AI_DIR = DATA_DIR / "ai"
DB_PATH = DATA_DIR / "nagoya_event.db"
ORBIS_PATH = DATA_DIR / "orbis" / "orbis_mobile.csv"
INCIDENTS_DIR = DATA_DIR / "incidents"
WEATHER_PATH = AI_DIR / "weather_summary.json"
X_SUMMARY_PATH = AI_DIR / "x_summary.json"
DRAGONS_PATH = AI_DIR / "dragons_log.yml"
OUTPUT_PATH = AI_DIR / "daily_context.json"


class YamlLine(NamedTuple):
    indent: int
    text: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def try_import_yaml() -> Any | None:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return None
    return yaml


def read_json(path: Path, notes: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        notes.append(f"Failed to read {path.relative_to(ROOT)}: {exc}")
        return {}
    if isinstance(data, dict):
        return data
    notes.append(f"Skipped {path.relative_to(ROOT)} because it is not a JSON object.")
    return {}


def read_yaml(path: Path, yaml_module: Any | None, notes: list[str]) -> Any:
    if not path.exists():
        return None
    try:
        if yaml_module is not None:
            with path.open(encoding="utf-8") as f:
                return yaml_module.safe_load(f) or {}
        return load_simple_yaml(path)
    except (OSError, Exception) as exc:
        notes.append(f"Failed to read {path.relative_to(ROOT)}: {exc}")
        return None


def scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def strip_comment(line: str) -> str:
    in_quote: str | None = None
    for index, char in enumerate(line):
        if char in {"'", '"'}:
            in_quote = None if in_quote == char else char
        if char == "#" and in_quote is None and (index == 0 or line[index - 1].isspace()):
            return line[:index].rstrip()
    return line.rstrip()


def load_simple_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    stripped_text = text.strip()
    if stripped_text == "[]":
        return []
    if stripped_text == "{}":
        return {}

    raw_lines = text.splitlines()
    lines = [
        YamlLine(len(line) - len(line.lstrip(" ")), strip_comment(line).lstrip(" "))
        for line in raw_lines
        if strip_comment(line).strip()
    ]
    if not lines:
        return {}
    data, index = parse_yaml_block(lines, 0, lines[0].indent)
    if index < len(lines):
        raise ValueError(f"Unsupported YAML structure near: {lines[index].text}")
    return data


def parse_yaml_block(lines: list[YamlLine], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    if lines[index].text.startswith("- "):
        return parse_yaml_list(lines, index, indent)
    return parse_yaml_dict(lines, index, indent)


def parse_yaml_dict(lines: list[YamlLine], index: int, indent: int) -> tuple[dict[str, Any], int]:
    data: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if line.indent < indent or line.text.startswith("- "):
            break
        if line.indent > indent:
            raise ValueError(f"Unexpected indentation near: {line.text}")
        key, value = split_yaml_pair(line.text)
        index += 1
        if value == "":
            if index < len(lines) and lines[index].indent > indent:
                data[key], index = parse_yaml_block(lines, index, lines[index].indent)
            else:
                data[key] = {}
        elif value in {">", "|"}:
            data[key], index = parse_yaml_block_scalar(lines, index, indent)
        else:
            data[key] = scalar(value)
    return data, index


def parse_yaml_list(lines: list[YamlLine], index: int, indent: int) -> tuple[list[Any], int]:
    data: list[Any] = []
    while index < len(lines):
        line = lines[index]
        if line.indent < indent or not line.text.startswith("- "):
            break
        if line.indent > indent:
            raise ValueError(f"Unexpected indentation near: {line.text}")

        content = line.text[2:].strip()
        index += 1
        if content in {">", "|"}:
            value, index = parse_yaml_block_scalar(lines, index, indent)
            data.append(value)
        elif ":" in content:
            key, value = split_yaml_pair(content)
            item: dict[str, Any] = {}
            if value == "":
                if index < len(lines) and lines[index].indent > indent:
                    item[key], index = parse_yaml_block(lines, index, lines[index].indent)
                else:
                    item[key] = {}
            else:
                item[key] = scalar(value)
            if index < len(lines) and lines[index].indent > indent:
                child, index = parse_yaml_block(lines, index, lines[index].indent)
                if isinstance(child, dict):
                    item.update(child)
                else:
                    item.setdefault("items", child)
            data.append(item)
        else:
            data.append(scalar(content))
    return data, index


def parse_yaml_block_scalar(
    lines: list[YamlLine],
    index: int,
    parent_indent: int,
) -> tuple[str, int]:
    parts: list[str] = []
    while index < len(lines) and lines[index].indent > parent_indent:
        parts.append(lines[index].text)
        index += 1
    return "\n".join(parts).strip(), index


def split_yaml_pair(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"Expected key/value pair: {text}")
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def read_table(conn: sqlite3.Connection, table_name: str, notes: list[str]) -> list[dict[str, Any]]:
    if not table_exists(conn, table_name):
        notes.append(f"Skipped missing table: {table_name}")
        return []

    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY date, time, venue, title").fetchall()
    return [dict(row) for row in rows]


def read_db(notes: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not DB_PATH.exists():
        return [], []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            events = read_table(conn, "events", notes)
            road_events = read_table(conn, "road_events", notes)
    except sqlite3.Error as exc:
        notes.append(f"Failed to read {DB_PATH.relative_to(ROOT)}: {exc}")
        return [], []
    return events, road_events


def read_csv(path: Path, notes: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error) as exc:
        notes.append(f"Failed to read {path.relative_to(ROOT)}: {exc}")
        return []


def read_incidents(yaml_module: Any | None, notes: list[str]) -> list[dict[str, Any]]:
    if not INCIDENTS_DIR.exists():
        return []

    incidents: list[dict[str, Any]] = []
    for path in sorted(INCIDENTS_DIR.glob("*.yml")):
        data = read_yaml(path, yaml_module, notes)
        if isinstance(data, dict):
            item = {"source_file": str(path.relative_to(ROOT))}
            item.update(data)
            incidents.append(item)
        elif data is not None:
            notes.append(f"Skipped {path.relative_to(ROOT)} because it is not a YAML mapping.")
    return incidents


def build_context() -> dict[str, Any]:
    notes: list[str] = []
    yaml_module = try_import_yaml()
    events, road_events = read_db(notes)

    context: dict[str, Any] = {
        "generated_at": now_iso(),
        "events": events,
        "road_events": road_events,
        "orbis": read_csv(ORBIS_PATH, notes),
        "incidents": read_incidents(yaml_module, notes),
        "weather": read_json(WEATHER_PATH, notes),
        "x_summary": read_json(X_SUMMARY_PATH, notes),
        "dragons": read_yaml(DRAGONS_PATH, yaml_module, notes) or {},
        "notes": notes,
    }
    return context


def main() -> int:
    AI_DIR.mkdir(parents=True, exist_ok=True)
    context = build_context()

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"wrote: {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"events: {len(context['events'])}")
    print(f"road_events: {len(context['road_events'])}")
    print(f"orbis: {len(context['orbis'])}")
    print(f"incidents: {len(context['incidents'])}")
    print(f"weather: {1 if context['weather'] else 0}")
    print(f"x_summary: {1 if context['x_summary'] else 0}")
    print(f"dragons: {1 if context['dragons'] else 0}")
    print(f"notes: {len(context['notes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
