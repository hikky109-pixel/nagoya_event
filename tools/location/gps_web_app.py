#!/usr/bin/env python3
"""ブラウザGeolocationでYahoo PlaceInfoを試す軽量Webアプリ。"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config import DISCORD_BOT_TOKEN, GEMMA_DISCORD_WEBHOOK, GEMMA_WEBHOOK_URL, GPS_REPORT_CHANNEL_ID  # noqa: E402
from tools.location.get_hybrid_placeinfo import get_hybrid_placeinfo  # noqa: E402


REQUEST_TIMEOUT_SECONDS = 10
JST = ZoneInfo("Asia/Tokyo")
PLACEINFO_DIR = ROOT / "data" / "location" / "placeinfo"
METADATA_KEYS = ("source", "user_id", "report_type", "channel_id")


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
    .actions {
      display: grid;
      gap: 10px;
    }
    .actions[data-state="ready"] .after-success,
    .actions[data-state="done"] #gpsButton {
      display: none;
    }
    .after-success {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    button {
      width: 100%;
      border: 0;
      border-radius: 8px;
      padding: 14px 18px;
      background: #0b57d0;
      color: #fff;
      font-size: 17px;
      font-weight: 700;
      min-height: 52px;
    }
    #closeButton { background: #5f6368; }
    #refreshButton { background: #0b57d0; }
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
      #closeButton { background: #9aa0a6; color: #111; }
      #refreshButton { background: #8ab4f8; color: #0b1b32; }
    }
    @media (max-width: 420px) {
      main {
        width: min(100% - 24px, 720px);
        padding: 28px 0;
      }
      .after-success {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main>
    <h1>📍 現在地テスト</h1>
    <p>位置情報を許可してください。<br>取得した座標から近くのランドマーク候補を表示します。</p>
    <div id="actions" class="actions" data-state="ready">
      <button id="gpsButton" type="button">📍 現在地を取得</button>
      <div class="after-success">
        <button id="closeButton" type="button">❌ 閉じる</button>
        <button id="refreshButton" type="button">🔄 現在地を更新</button>
      </div>
    </div>
    <div id="status"></div>
    <ol id="candidates"></ol>
  </main>
  <script>
    const actions = document.getElementById("actions");
    const button = document.getElementById("gpsButton");
    const closeButton = document.getElementById("closeButton");
    const refreshButton = document.getElementById("refreshButton");
    const statusBox = document.getElementById("status");
    const list = document.getElementById("candidates");
    let hasSuccessfulPosition = false;

    function setStatus(text) {
      statusBox.textContent = text;
    }

    function setBusy(isBusy) {
      button.disabled = isBusy;
      closeButton.disabled = isBusy;
      refreshButton.disabled = isBusy;
      if (isBusy) {
        button.textContent = "📡 現在地を更新しています...";
        refreshButton.textContent = "📡 現在地を更新しています...";
      } else {
        button.textContent = "📍 現在地を取得";
        refreshButton.textContent = "🔄 現在地を更新";
      }
    }

    function showInitialActions() {
      actions.dataset.state = "ready";
    }

    function showPostSuccessActions() {
      actions.dataset.state = "done";
    }

    function enableRetry() {
      setBusy(false);
      if (hasSuccessfulPosition) {
        showPostSuccessActions();
      } else {
        showInitialActions();
      }
    }

    function geolocationErrorMessage(error) {
      if (error.code === 1) {
        return "位置情報が拒否されました";
      }
      if (error.code === 2) {
        return "位置情報を取得できませんでした";
      }
      if (error.code === 3) {
        return "位置情報取得がタイムアウトしました";
      }
      return error.message || "位置情報を取得できませんでした";
    }

    function renderCandidates(items) {
      list.innerHTML = "";
      for (const item of items.slice(0, 5)) {
        const li = document.createElement("li");
        if (item && typeof item === "object") {
          li.textContent = item.name || "";
        } else {
          li.textContent = String(item);
        }
        list.appendChild(li);
      }
    }

    async function sendPosition(position) {
      const lat = position.coords.latitude;
      const lon = position.coords.longitude;
      setStatus(`座標: ${lat.toFixed(6)}, ${lon.toFixed(6)}\\nYahoo PlaceInfoを確認しています...`);
      const params = new URLSearchParams(window.location.search);
      params.set("lat", lat);
      params.set("lon", lon);
      const response = await fetch(`/api/placeinfo?${params.toString()}`);
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "placeinfo_failed");
      }
      const candidates = data.result.candidates || [];
      const displayText = data.result.display_lines && data.result.display_lines.text ? data.result.display_lines.text : "";
      const discordStatus = data.discord_posted ? "\\nDiscordへ送信しました😇" : "\\nDiscord送信は確認できませんでした";
      const displayStatus = displayText ? `${displayText}\\n` : "";
      setStatus(`${displayStatus}候補: ${candidates.length}件${discordStatus}`);
      renderCandidates(candidates);
      hasSuccessfulPosition = true;
      showPostSuccessActions();
    }

    function getCurrentPosition() {
      if (!navigator.geolocation) {
        setStatus("このブラウザでは位置情報を取得できません。\\nうまく動かない場合はSafariで開いてください😇");
        enableRetry();
        return;
      }
      setBusy(true);
      setStatus("GPS許可を確認しています...");
      navigator.geolocation.getCurrentPosition(
        (position) => {
          sendPosition(position).catch((error) => {
            setStatus(`位置情報テストを開始できませんでした: ${error.message}`);
            enableRetry();
          }).then(() => {
            setBusy(false);
          });
        },
        (error) => {
          setStatus(`${geolocationErrorMessage(error)}\\nうまく動かない場合はSafariで開いてください😇`);
          enableRetry();
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      );
    }

    function closePage() {
      setStatus("");
      if (window.history.length > 1) {
        window.history.back();
        window.setTimeout(() => {
          window.close();
          window.setTimeout(() => {
            setStatus("ブラウザの×で閉じてください");
          }, 300);
        }, 300);
        return;
      }
      window.close();
      window.setTimeout(() => {
        setStatus("ブラウザの×で閉じてください");
      }, 300);
    }

    button.addEventListener("click", getCurrentPosition);
    refreshButton.addEventListener("click", getCurrentPosition);
    closeButton.addEventListener("click", closePage);
  </script>
</body>
</html>
"""


ADMIN_PLACEINFO_HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PlaceInfo Test</title>
  <style>
    :root { color-scheme: light dark; }
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      background: #f6f7f8;
      color: #202124;
    }
    main {
      width: min(680px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0;
    }
    h1 { font-size: 24px; margin: 0 0 18px; }
    label {
      display: grid;
      gap: 6px;
      margin: 0 0 12px;
      font-weight: 700;
    }
    input {
      box-sizing: border-box;
      width: 100%;
      border: 1px solid #dadce0;
      border-radius: 8px;
      padding: 12px;
      font-size: 17px;
      background: #fff;
      color: #202124;
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 16px;
    }
    button {
      border: 0;
      border-radius: 8px;
      padding: 14px 16px;
      background: #0b57d0;
      color: #fff;
      font-size: 16px;
      font-weight: 700;
      min-height: 52px;
    }
    #copyButton { background: #5f6368; }
    button:disabled { opacity: .6; }
    #output {
      margin-top: 22px;
      padding: 16px;
      min-height: 84px;
      border: 1px solid #dadce0;
      border-radius: 8px;
      background: #fff;
      white-space: pre-wrap;
      font-size: 18px;
      line-height: 1.7;
    }
    #status {
      margin-top: 10px;
      min-height: 24px;
      color: #5f6368;
    }
    @media (prefers-color-scheme: dark) {
      body { background: #171717; color: #f2f2f2; }
      input, #output { background: #202124; color: #f2f2f2; border-color: #3c4043; }
      button { background: #8ab4f8; color: #0b1b32; }
      #copyButton { background: #9aa0a6; color: #111; }
      #status { color: #bdc1c6; }
    }
    @media (max-width: 460px) {
      main { width: min(100% - 24px, 680px); }
      .actions { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <h1>PlaceInfo Test</h1>
    <label>Latitude<input id="latInput" inputmode="decimal" autocomplete="off"></label>
    <label>Longitude<input id="lonInput" inputmode="decimal" autocomplete="off"></label>
    <div class="actions">
      <button id="searchButton" type="button">検索</button>
      <button id="copyButton" type="button">📋 出力をコピー</button>
    </div>
    <div id="output"></div>
    <div id="status"></div>
  </main>
  <script>
    const latInput = document.getElementById("latInput");
    const lonInput = document.getElementById("lonInput");
    const searchButton = document.getElementById("searchButton");
    const copyButton = document.getElementById("copyButton");
    const output = document.getElementById("output");
    const statusBox = document.getElementById("status");

    function setBusy(isBusy) {
      searchButton.disabled = isBusy;
      copyButton.disabled = isBusy;
      searchButton.textContent = isBusy ? "検索中..." : "検索";
    }

    async function search() {
      const lat = latInput.value.trim();
      const lon = lonInput.value.trim();
      if (!lat || !lon) {
        statusBox.textContent = "Latitude / Longitude を入力してください";
        return;
      }
      setBusy(true);
      statusBox.textContent = "";
      try {
        const params = new URLSearchParams({ lat, lon });
        const response = await fetch(`/api/admin/placeinfo-test?${params.toString()}`);
        const data = await response.json();
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "placeinfo_failed");
        }
        output.textContent = data.text || "";
        statusBox.textContent = output.textContent ? "" : "表示できる候補がありません";
      } catch (error) {
        statusBox.textContent = `検索できませんでした: ${error.message}`;
      } finally {
        setBusy(false);
      }
    }

    async function copyOutput() {
      const text = output.textContent.trim();
      if (!text) {
        statusBox.textContent = "コピーする出力がありません";
        return;
      }
      try {
        await navigator.clipboard.writeText(text);
        statusBox.textContent = "コピーしました";
      } catch (error) {
        statusBox.textContent = "コピーできませんでした。出力を長押しでコピーしてください";
      }
    }

    searchButton.addEventListener("click", search);
    copyButton.addEventListener("click", copyOutput);
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


def placeinfo_display_text(result: dict[str, Any]) -> str:
    display = result.get("display_lines") if isinstance(result.get("display_lines"), dict) else {}
    text = str(display.get("text") or "").strip()
    if text:
        return text
    lines = display.get("lines")
    if isinstance(lines, list):
        return "\n".join(str(line).strip() for line in lines if str(line).strip())
    short_address = str(result.get("short_address") or "").strip()
    return f"📍 {short_address}" if short_address else ""


def placeinfo_summary(result: dict[str, Any]) -> str:
    lat = float(result.get("lat") or 0)
    lon = float(result.get("lon") or 0)
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    display_text = placeinfo_display_text(result)
    lines = [
        "🚕 現在地テスト結果",
        "",
    ]
    if display_text:
        lines.extend([display_text, ""])
    lines.extend(
        [
            "候補:",
        ]
    )
    if not candidates:
        lines.append("取得候補なし")
    for index, item in enumerate(candidates[:5], start=1):
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                lines.append(f"{index}. {name}")
        else:
            name = str(item).strip()
            if name:
                lines.append(f"{index}. {name}")
    lines.extend(
        [
            "",
            "結果が違う場合は、この投稿にリプライで正解を教えてください😇",
        ]
    )
    return "\n".join(lines)


def first_query_value(query: dict[str, list[str]], key: str) -> str:
    value = (query.get(key) or [""])[0]
    return str(value or "").strip()


def request_metadata(query: dict[str, list[str]]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key in METADATA_KEYS:
        value = first_query_value(query, key)
        if value:
            metadata[key] = value[:120]
    return metadata


def save_discord_post_result(result: dict[str, Any], *, metadata: dict[str, str], posted: bool) -> str:
    PLACEINFO_DIR.mkdir(parents=True, exist_ok=True)
    saved_at = datetime.now(JST)
    payload = {
        "saved_at": saved_at.isoformat(timespec="seconds"),
        "source": "GPSWebApp",
        "discord_posted": posted,
        "metadata": metadata,
        "placeinfo_raw_path": result.get("raw_path", ""),
        "lat": result.get("lat"),
        "lon": result.get("lon"),
        "taxi_label": result.get("taxi_label", {}),
        "comparison": result.get("comparison", {}),
        "address": result.get("address", []),
        "short_address": result.get("short_address", ""),
        "roadname": result.get("roadname", ""),
        "candidates": result.get("candidates", []),
    }
    path = PLACEINFO_DIR / f"{saved_at:%Y%m%d_%H%M%S}_gps_discord.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path.relative_to(ROOT))


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
    except (OSError, urllib.error.URLError) as exc:
        print(f"gps_discord_webhook_post_failed={type(exc).__name__}", flush=True)
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
    except (OSError, urllib.error.URLError) as exc:
        print(f"gps_discord_bot_post_failed={type(exc).__name__}", flush=True)
        return False


def post_discord_report(content: str) -> bool:
    return post_discord_bot_message(content) or post_discord_webhook(content)


class GPSRequestHandler(BaseHTTPRequestHandler):
    server_version = "NagoyaGPSWeb/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/gps":
            self.send_html(GPS_HTML)
            return
        if parsed.path == "/admin/placeinfo-test":
            self.send_html(ADMIN_PLACEINFO_HTML)
            return
        if parsed.path == "/api/placeinfo":
            self.handle_placeinfo(parse_qs(parsed.query))
            return
        if parsed.path == "/api/admin/placeinfo-test":
            self.handle_admin_placeinfo_test(parse_qs(parsed.query))
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

        metadata = request_metadata(query)
        result = get_hybrid_placeinfo(lat, lon, area="gps_hybrid")
        if metadata:
            result["request"] = metadata
        posted = post_discord_report(placeinfo_summary(result))
        if not posted:
            print("gps_discord_post_failed=true", flush=True)
        post_result_path = save_discord_post_result(result, metadata=metadata, posted=posted)
        self.send_json(
            {
                "ok": True,
                "result": result,
                "discord_posted": posted,
                "discord_post_result_path": post_result_path,
            }
        )

    def handle_admin_placeinfo_test(self, query: dict[str, list[str]]) -> None:
        lat = parse_coordinate((query.get("lat") or [""])[0], lower=-90, upper=90)
        lon = parse_coordinate((query.get("lon") or [""])[0], lower=-180, upper=180)
        if lat is None or lon is None:
            self.send_json({"ok": False, "error": "invalid_lat_lon"}, status=HTTPStatus.BAD_REQUEST)
            return

        result = get_hybrid_placeinfo(lat, lon, area="admin_placeinfo_test")
        self.send_json(
            {
                "ok": True,
                "text": placeinfo_display_text(result),
                "result": {
                    "display_lines": result.get("display_lines", {}),
                    "short_address": result.get("short_address", ""),
                    "lat": result.get("lat"),
                    "lon": result.get("lon"),
                },
            }
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GPS OSM + Yahoo PlaceInfoテスト用の軽量Webサーバー。")
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
