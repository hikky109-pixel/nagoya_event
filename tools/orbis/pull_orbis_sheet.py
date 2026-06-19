#!/usr/bin/env python3
"""Google Sheetsからオービス秘伝のタレCSVを取得する。"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


CSV_PATH = BASE_DIR / "data" / "orbis" / "orbis_mobile.csv"
TOKEN_PATH = BASE_DIR / "credentials" / "token.json"
DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "12MNpRn0Krk3WVRFoj37bST2fXBGnomeQ-DQ4N9VA-7c/gviz/tq?tqx=out:csv"
)
SHEET_NAME = "オービス_可搬式"
ORBIS_COLUMNS = ["category", "city", "road", "direction", "location", "note"]


def normalize_row(values: list[str]) -> dict[str, str]:
    row = {}
    for index, column in enumerate(ORBIS_COLUMNS):
        row[column] = values[index].strip() if index < len(values) else ""
    return row


def is_empty_row(row: dict[str, str]) -> bool:
    return not any(value.strip() for value in row.values())


def spreadsheet_id_from_url(url: str) -> str:
    path = urlparse(url).path
    if "/d/" not in path:
        return ""
    return path.split("/d/", 1)[1].split("/", 1)[0]


def default_spreadsheet_id() -> str:
    return os.environ.get("GOOGLE_SHEET_ID") or spreadsheet_id_from_url(DEFAULT_SHEET_URL)


def load_token() -> dict[str, object]:
    if not TOKEN_PATH.exists():
        raise RuntimeError(f"OAuth token not found: {TOKEN_PATH}")
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def token_is_valid(token: dict[str, object]) -> bool:
    access_token = str(token.get("token") or "")
    expiry = str(token.get("expiry") or "")
    if not access_token or not expiry:
        return False

    expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    return expires_at > datetime.now(timezone.utc)


def refresh_token(token: dict[str, object]) -> dict[str, object]:
    refresh_token_value = str(token.get("refresh_token") or "")
    client_id = str(token.get("client_id") or "")
    client_secret = str(token.get("client_secret") or "")

    if not refresh_token_value or not client_id or not client_secret:
        raise RuntimeError(f"OAuth token refresh情報が不足しています: {TOKEN_PATH}")

    body = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token_value,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    request = Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    token["token"] = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc).timestamp() + expires_in
    token["expiry"] = datetime.fromtimestamp(expires_at, timezone.utc).isoformat().replace("+00:00", "Z")

    TOKEN_PATH.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")
    return token


def access_token() -> str:
    token = load_token()
    if not token_is_valid(token):
        token = refresh_token(token)
    return str(token["token"])


def read_sheet_values(spreadsheet_id: str, sheet_name: str) -> list[list[str]]:
    range_name = quote(sheet_name, safe="")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_name}"
    request = Request(url, headers={"Authorization": f"Bearer {access_token()}"})

    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return payload.get("values", [])


def read_orbis_sheet_rows() -> list[dict[str, str]]:
    spreadsheet_id = default_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError("Google spreadsheet ID is not configured")

    rows = read_sheet_values(spreadsheet_id, SHEET_NAME)
    if not rows:
        raise RuntimeError(f"Google Sheetsが空です: {SHEET_NAME}")

    header = [str(value).strip() for value in rows[0]]
    if header != ORBIS_COLUMNS:
        raise RuntimeError(f"オービスSheetヘッダー不一致: {header}")

    records = [normalize_row(row) for row in rows[1:]]
    return [record for record in records if not is_empty_row(record)]


def write_orbis_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ORBIS_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    rows = read_orbis_sheet_rows()
    write_orbis_csv(CSV_PATH, rows)
    print(f"オービスSheet取り込み完了: {len(rows)}件")
    print(f"保存: {CSV_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
