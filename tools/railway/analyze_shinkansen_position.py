"""Analyze JR Central Shinkansen train position snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = ROOT / "data" / "railway" / "shinkansen_position"
DEFAULT_RULES_PATH = ROOT / "data" / "railway" / "shinkansen_terminal_connection_rules.yml"

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


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    try:
        return int(value)
    except ValueError:
        return value


def load_terminal_connection_rules(path: Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"normal_delay_threshold_min": 30, "terminal_connection_rules": []}
    data: dict[str, Any] = {"terminal_connection_rules": []}
    current: dict[str, Any] | None = None
    in_rules = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "terminal_connection_rules:":
            in_rules = True
            continue
        if in_rules and stripped.startswith("- "):
            if current:
                data["terminal_connection_rules"].append(current)
            current = {}
            content = stripped[2:].strip()
            if ":" in content:
                key, value = content.split(":", 1)
                current[key.strip()] = _parse_scalar(value)
            continue
        if in_rules and current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = _parse_scalar(value)
            continue
        if not in_rules and ":" in stripped:
            key, value = stripped.split(":", 1)
            data[key.strip()] = _parse_scalar(value)
    if current:
        data["terminal_connection_rules"].append(current)
    return data


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


def tokaido_station_codes(constants: dict[str, Any]) -> set[str]:
    raw_tokaido = constants.get("stationTokaido")
    if isinstance(raw_tokaido, list):
        return {_text(item) for item in raw_tokaido if _text(item)}
    order = station_order(constants)
    if not order:
        return set()
    if "15" in order:
        return set(order[: order.index("15") + 1])
    return set(order)


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


def location_station_codes(station_code: Any, bound: str, section: str, constants: dict[str, Any]) -> list[str]:
    code = _text(station_code)
    if not code:
        return []
    if section == "at_station":
        return [code]
    order = station_order(constants)
    if code not in order:
        return [code]
    index = order.index(code)
    if bound == "2" and index + 1 < len(order):
        return [code, order[index + 1]]
    if bound == "1" and index - 1 >= 0:
        return [code, order[index - 1]]
    return [code]


def is_tokaido_section(station_codes: list[str], constants: dict[str, Any]) -> bool:
    tokaido_codes = tokaido_station_codes(constants)
    if not station_codes or not tokaido_codes:
        return True
    return all(code in tokaido_codes for code in station_codes)


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
    station_codes = location_station_codes(station_code, bound, section, constants)
    tokaido_section = is_tokaido_section(station_codes, constants)
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
        "tokaido_section": tokaido_section,
        "ignored_reason": "" if tokaido_section else "山陽区間のため対象外",
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


def build_severity_alerts(trains: list[dict[str, Any]], *, threshold_min: int) -> list[dict[str, Any]]:
    alerts = []
    for train in trains:
        delay = _int(train.get("delay_min"))
        if delay < threshold_min:
            continue
        alerts.append(
            {
                "train_name": train.get("train_type", ""),
                "train_number": train.get("train_number", ""),
                "direction": train.get("direction", ""),
                "delay_min": delay,
                "position": train.get("position", ""),
                "reason": f"東海道新幹線区間で{threshold_min}分以上の遅延",
            }
        )
    return alerts


def build_terminal_connection_risks(trains: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risks = []
    for train in trains:
        delay = _int(train.get("delay_min"))
        for rule in rules:
            if _text(rule.get("train_name")) != _text(train.get("train_type")):
                continue
            if _text(rule.get("train_number")) != _text(train.get("train_number")):
                continue
            rule_direction = _text(rule.get("direction"))
            if rule_direction and rule_direction != _text(train.get("direction")):
                continue
            threshold = _int(rule.get("threshold_min"))
            if delay < threshold:
                continue
            risks.append(
                {
                    "train_name": train.get("train_type", ""),
                    "train_number": train.get("train_number", ""),
                    "direction": train.get("direction", ""),
                    "delay_min": delay,
                    "position": train.get("position", ""),
                    "risk_area": rule.get("risk_area", ""),
                    "threshold_min": threshold,
                    "reason": rule.get("reason", ""),
                }
            )
    return risks


def build_summary(snapshot: dict[str, Any], *, rules_path: Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    trains = extract_trains(snapshot)
    rules_data = load_terminal_connection_rules(rules_path)
    normal_threshold = _int(rules_data.get("normal_delay_threshold_min"), 30)
    terminal_rules = rules_data.get("terminal_connection_rules")
    if not isinstance(terminal_rules, list):
        terminal_rules = []
    tokaido_trains = [train for train in trains if train.get("tokaido_section")]
    ignored_trains = [train for train in trains if train.get("ignored_reason")]
    delayed = [train for train in tokaido_trains if _int(train.get("delay_min")) > 0]
    max_delay = max((_int(train.get("delay_min")) for train in tokaido_trains), default=0)
    payload, _common = unwrap_snapshot(snapshot)
    info = payload.get("trainLocationInfo") if isinstance(payload.get("trainLocationInfo"), dict) else {}
    return {
        "source": "shinkansen_position",
        "line": "tokaido_shinkansen",
        "fetched_at": _text(snapshot.get("fetched_at")),
        "data_datetime": info.get("datetime", ""),
        "total_trains": len(trains),
        "tokaido_trains": len(tokaido_trains),
        "max_delay_min": max_delay,
        "normal_delay_threshold_min": normal_threshold,
        "severity_alerts": build_severity_alerts(tokaido_trains, threshold_min=normal_threshold),
        "terminal_connection_risks": build_terminal_connection_risks(tokaido_trains, terminal_rules),
        "delayed_trains": [
            {
                "train_no": train.get("train_no", ""),
                "direction": train.get("direction", ""),
                "delay_min": train.get("delay_min", 0),
                "position": train.get("position", ""),
            }
            for train in delayed
        ],
        "ignored_trains": [
            {
                "train_no": train.get("train_no", ""),
                "direction": train.get("direction", ""),
                "position": train.get("position", ""),
                "delay_min": train.get("delay_min", 0),
                "ignored_reason": train.get("ignored_reason", ""),
            }
            for train in ignored_trains
        ],
    }


def summary_to_yaml(summary: dict[str, Any]) -> str:
    lines = [
        f"source: {summary.get('source', '')}",
        f"line: {summary.get('line', '')}",
        f"max_delay_min: {summary.get('max_delay_min', 0)}",
    ]
    for key in ("severity_alerts", "terminal_connection_risks", "delayed_trains", "ignored_trains"):
        append_yaml_list(lines, key, summary.get(key))
    return "\n".join(lines)


def append_yaml_list(lines: list[str], key: str, value: Any) -> None:
    lines.append(f"{key}:")
    rows = value if isinstance(value, list) else []
    if not rows:
        lines[-1] = f"{key}: []"
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        first = True
        for item_key, item_value in row.items():
            prefix = "- " if first else "  "
            first = False
            if isinstance(item_value, int):
                rendered = str(item_value)
            else:
                rendered = json.dumps(_text(item_value), ensure_ascii=False)
            lines.append(f"{prefix}{item_key}: {rendered}")


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
