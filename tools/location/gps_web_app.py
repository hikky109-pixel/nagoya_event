#!/usr/bin/env python3
"""ブラウザGeolocationでYahoo PlaceInfoを試す軽量Webアプリ。"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config import DISCORD_BOT_TOKEN, GEMMA_DISCORD_WEBHOOK, GEMMA_WEBHOOK_URL, GPS_REPORT_CHANNEL_ID  # noqa: E402
from tools.location.get_yahoo_placeinfo import get_yahoo_placeinfo  # noqa: E402


REQUEST_TIMEOUT_SECONDS = 10


GPS_HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>現在地テスト</title>
  <style>
    :root { color-scheme: light dark; }
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      background: #f6f7f8;
      color: #202124;
    }
    main {
      width: min(720px, calc(100% - 32px));
      margin: 0 auto;
      padding: 40px 0;
    }
    h1 { font-size: 28px; margin: 0 0 16px; }
    p { line-height: 1.7; margin: 0 0 20px; }
    button {
      width: 100%;
      border: 0;
      border-radius: 8px;
      padding: 14px 18px;
      background: #0b57d0;
      color: #fff;
      font-size: 17px;
      font-weight: 700;
    }
    button:disabled { opacity: .65; }
    #status {
      margin-top: 18px;
      padding: 14px 0;
      min-height: 24px;
      white-space: pre-wrap;
    }
    ol { padding-left: 24px; }
    li { margin: 8px 0; }
    @media (prefers-color-scheme: dark) {
      body { background: #171717; color: #f2f2f2; }
      button { background: #8ab4f8; color: #0b1b32; }
    }
  </style>
</head>
<body>
  <main>
    <h1>📍 現在地テスト</h1>
    <p>位置情報を許可してください。<br>取得した座標から近くのランドマーク候補を表示します。</p>
    <button id="gpsButton" type="button">現在地を取得</button>
    <div id="status"></div>
    <ol id="candidates"></ol>
  </main>
  <script>
    const button = document.getElementById("gpsButton");
    const statusBox = document.getElementById("status");
    const list = document.getElementById("candidates");

    function setStatus(text) {
      statusBox.textContent = text;
    }

    function renderCandidates(items) {
      list.innerHTML = "";
      for (const item of items.slice(0, 5)) {
        const li = document.createElement("li");
        li.textContent = item.name || String(item);
        list.appendChild(li);
      }
    }

    async function sendPosition(position) {
      const lat = position.coords.latitude;
      const lon = position.coords.longitude;
      setStatus(`座標: ${lat.toFixed(6)}, ${lon.toFixed(6)}\\nYahoo PlaceInfoを確認しています...`);
      const response = await fetch(`/api/placeinfo?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "placeinfo_failed");
      }
      const candidates = data.result.candidates || [];
      setStatus(`座標: ${lat.toFixed(6)}, ${lon.toFixed(6)}\\n候補: ${candidates.length}件`);
      renderCandidates(candidates);
    }

    function getCurrentPosition() {
      if (!navigator.geolocation) {
        setStatus("このブラウザでは位置情報を取得できません。");
        return;
      }
      button.disabled = true;
      setStatus("位置情報を取得しています...");
      navigator.geolocation.getCurrentPosition(
        (position) => {
          sendPosition(position).catch((error) => {
            setStatus(`位置情報テストを開始できませんでした: ${error.message}`);
          }).finally(() => {
            button.disabled = false;
          });
        },
        (error) => {
          setStatus(`位置情報を取得できませんでした: ${error.message}`);
          button.disabled = false;
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
      );
    }

    button.addEventListener("click", getCurrentPosition);
    window.addEventListener("load", getCurrentPosition);
  </script>
</body>
</html>
"""


def parse_coordinate(value: str, *, lower: float, upper: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if lower <= number <= upper:
        return number
    return None


def placeinfo_summary(result: dict[str, Any]) -> str:
    lat = float(result.get("lat") or 0)
    lon = float(result.get("lon") or 0)
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    lines = [
        "📍 Yahoo PlaceInfo 結果",
        "",
        "座標:",
        f"{lat:.6f}, {lon:.6f}",
        "",
        "候補:",
    ]
    if not candidates:
        lines.append("取得候補なし")
    for index, item in enumerate(candidates[:5], start=1):
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item).strip()
        if name:
            lines.append(f"{index}. {name}")
    return "\n".join(lines)


def post_discord_webhook(content: str) -> bool:
    webhook_url = (GEMMA_DISCORD_WEBHOOK or GEMMA_WEBHOOK_URL or "").strip()
    if not webhook_url:
        return False
    payload = {"content": content}
    if GPS_REPORT_CHANNEL_ID:
        payload["allowed_mentions"] = {"parse": []}
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "nagoya-event-gps-web/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError):
        return False


def post_discord_bot_message(content: str) -> bool:
    token = str(DISCORD_BOT_TOKEN or "").strip()
    channel_id = str(GPS_REPORT_CHANNEL_ID or "").strip()
    if not token or not channel_id:
        return False
    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "nagoya-event-gps-web/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError):
        return False


def post_discord_report(content: str) -> bool:
    return post_discord_webhook(content) or post_discord_bot_message(content)


class GPSRequestHandler(BaseHTTPRequestHandler):
    server_version = "NagoyaGPSWeb/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/gps":
            self.send_html(GPS_HTML)
            return
        if parsed.path == "/api/placeinfo":
            self.handle_placeinfo(parse_qs(parsed.query))
            return
        self.send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"gps_web_access={self.address_string()} {fmt % args}", flush=True)

    def send_html(self, html: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_placeinfo(self, query: dict[str, list[str]]) -> None:
        lat = parse_coordinate((query.get("lat") or [""])[0], lower=-90, upper=90)
        lon = parse_coordinate((query.get("lon") or [""])[0], lower=-180, upper=180)
        if lat is None or lon is None:
            self.send_json({"ok": False, "error": "invalid_lat_lon"}, status=HTTPStatus.BAD_REQUEST)
            return

        result = get_yahoo_placeinfo(lat, lon, area="gps")
        posted = post_discord_report(placeinfo_summary(result))
        self.send_json({"ok": True, "result": result, "discord_posted": posted})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GPS PlaceInfoテスト用の軽量Webサーバー。")
    parser.add_argument("--host", default="127.0.0.1", help="待ち受けホスト。")
    parser.add_argument("--port", type=int, default=8787, help="待ち受けポート。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), GPSRequestHandler)
    print(f"GPS Web app listening on http://{args.host}:{args.port}/gps", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("GPS Web app stopped", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
