"""Analyze JR Central Shinkansen train position snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = ROOT / "data" / "railway" / "shinkansen_position"

BOUND_TO_DIRECTION = {
    "1": "up",
    "2": "down",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return {}
    return data


def latest_snapshot_path(directory: Path = DEFAULT_INPUT_DIR) -> Path | None:
    if not directory.exists():
        return None
    files = sorted(directory.glob("*_shinkansen_position.json"))
    return files[-1] if files else None


def unwrap_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else snapshot
    common = snapshot.get("common") if isinstance(snapshot.get("common"), dict) else {}
    return payload if isinstance(payload, dict) else {}, common


def common_constants(common: dict[str, Any]) -> dict[str, Any]:
    constants = common.get("constant") if isinstance(common.get("constant"), dict) else {}
    return constants if isinstance(constants, dict) else {}


def station_order(constants: dict[str, Any]) -> list[str]:
    order = constants.get("stationOrder")
    if isinstance(order, list):
        return [_text(item) for item in order if _text(item)]
    return []


def station_name(station_code: Any, constants: dict[str, Any]) -> str:
    stations = constants.get("station") if isinstance(constants.get("station"), dict) else {}
    code = _text(station_code)
    return _text(stations.get(code)) or code


def train_name(train_code: Any, constants: dict[str, Any]) -> str:
    trains = constants.get("train") if isinstance(constants.get("train"), dict) else {}
    code = _text(train_code)
    return _text(trains.get(code)) or code


def between_position(station_code: Any, bound: str, constants: dict[str, Any]) -> str:
    code = _text(station_code)
    order = station_order(constants)
    name = station_name(code, constants)
    if code not in order:
        return f"{name}付近" if name else ""
    index = order.index(code)
    if bound == "2" and index + 1 < len(order):
        return f"{name}→{station_name(order[index + 1], constants)}"
    if bound == "1" and index - 1 >= 0:
        return f"{name}→{station_name(order[index - 1], constants)}"
    return f"{name}付近"


def normalize_train(
    train: dict[str, Any],
    *,
    bound: str,
    section: str,
    station_code: Any,
    constants: dict[str, Any],
) -> dict[str, Any]:
    train_type = train_name(train.get("train"), constants)
    train_number = _text(train.get("trainNumber"))
    delay = _int(train.get("delay"))
    if section == "at_station":
        base_position = station_name(station_code, constants)
        track = _text(train.get("track"))
        position = f"{base_position} {track}番線" if track and track != "0" else base_position
    else:
        position = between_position(station_code, bound, constants)
    return {
        "train_no": f"{train_type}{train_number}" if train_type or train_number else "",
        "train_type": train_type,
        "train_number": train_number,
        "direction": BOUND_TO_DIRECTION.get(bound, bound),
        "bound": bound,
        "section": section,
        "station_code": _text(station_code),
        "position": position,
        "delay_min": delay,
        "track": _text(train.get("track")),
        "sot": bool(train.get("sot")) if "sot" in train else False,
    }


def extract_trains(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    payload, common = unwrap_snapshot(snapshot)
    constants = common_constants(common)
    info = payload.get("trainLocationInfo") if isinstance(payload.get("trainLocationInfo"), dict) else {}
    trains: list[dict[str, Any]] = []
    sections = (("atStation", "at_station"), ("betweenStation", "between_station"))
    for raw_section, section_name in sections:
        section = info.get(raw_section) if isinstance(info.get(raw_section), dict) else {}
        bounds = section.get("bounds") if isinstance(section.get("bounds"), dict) else {}
        for bound, stations in bounds.items():
            if not isinstance(stations, list):
                continue
            for station in stations:
                if not isinstance(station, dict):
                    continue
                station_code = station.get("station")
                raw_trains = station.get("trains") if isinstance(station.get("trains"), list) else []
                for train in raw_trains:
                    if isinstance(train, dict):
                        trains.append(
                            normalize_train(
                                train,
                                bound=_text(bound),
                                section=section_name,
                                station_code=station_code,
                                constants=constants,
                            )
                        )
    return trains


def build_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    trains = extract_trains(snapshot)
    delayed = [train for train in trains if _int(train.get("delay_min")) > 0]
    max_delay = max((_int(train.get("delay_min")) for train in trains), default=0)
    payload, _common = unwrap_snapshot(snapshot)
    info = payload.get("trainLocationInfo") if isinstance(payload.get("trainLocationInfo"), dict) else {}
    return {
        "source": "shinkansen_position",
        "line": "tokaido_shinkansen",
        "fetched_at": _text(snapshot.get("fetched_at")),
        "data_datetime": info.get("datetime", ""),
        "total_trains": len(trains),
        "max_delay_min": max_delay,
        "delayed_trains": [
            {
                "train_no": train.get("train_no", ""),
                "direction": train.get("direction", ""),
                "delay_min": train.get("delay_min", 0),
                "position": train.get("position", ""),
            }
            for train in delayed
        ],
    }


def summary_to_yaml(summary: dict[str, Any]) -> str:
    lines = [
        f"source: {summary.get('source', '')}",
        f"line: {summary.get('line', '')}",
        f"max_delay_min: {summary.get('max_delay_min', 0)}",
        "delayed_trains:",
    ]
    delayed = summary.get("delayed_trains") if isinstance(summary.get("delayed_trains"), list) else []
    if not delayed:
        lines[-1] = "delayed_trains: []"
        return "\n".join(lines)
    for train in delayed:
        if not isinstance(train, dict):
            continue
        lines.append(f"- train_no: {json.dumps(_text(train.get('train_no')), ensure_ascii=False)}")
        lines.append(f"  direction: {json.dumps(_text(train.get('direction')), ensure_ascii=False)}")
        lines.append(f"  delay_min: {_int(train.get('delay_min'))}")
        lines.append(f"  position: {json.dumps(_text(train.get('position')), ensure_ascii=False)}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保存済み新幹線走行位置JSONを解析する。")
    parser.add_argument("path", nargs="?", type=Path, help="解析するsnapshot JSON。省略時は最新ファイル。")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="最新ファイル検索ディレクトリ。")
    parser.add_argument("--summary-yaml", action="store_true", help="Gemma投入候補のYAML風summaryだけを出力する。")
    parser.add_argument("--trains", action="store_true", help="正規化した全列車一覧をJSONで出力する。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = args.path or latest_snapshot_path(args.input_dir)
    if path is None:
        print(f"shinkansen_position_snapshot_not_found: {args.input_dir}", file=sys.stderr)
        return 1
    try:
        snapshot = load_snapshot(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"shinkansen_position_analyze_failed: {exc}", file=sys.stderr)
        return 1

    if args.trains:
        print(json.dumps(extract_trains(snapshot), ensure_ascii=False, indent=2))
        return 0

    summary = build_summary(snapshot)
    if args.summary_yaml:
        print(summary_to_yaml(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
