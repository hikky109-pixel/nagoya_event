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
from tools.location.place_labeler import distance_m  # noqa: E402
from tools.location.road_aliases import infer_road_alias_from_result  # noqa: E402


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
  <title>PlaceInfo Review</title>
  <style>
    :root { color-scheme: light dark; }
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      background: #f6f7f8;
      color: #202124;
    }
    main {
      width: min(900px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0;
    }
    h1 { font-size: 24px; margin: 0 0 18px; }
    h2 { font-size: 17px; margin: 0 0 12px; }
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
      grid-template-columns: repeat(3, 1fr);
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
      width: 100%;
    }
    button:disabled { opacity: .6; }
    section, details {
      margin-top: 18px;
      padding: 16px;
      border: 1px solid #dadce0;
      border-radius: 8px;
      background: #fff;
    }
    #summary, #yahoo, #roadAlias, #reasons, pre {
      white-space: pre-wrap;
      line-height: 1.7;
    }
    #summary { font-size: 15px; }
    #candidates {
      display: grid;
      gap: 10px;
    }
    .candidate {
      border-top: 1px solid #dadce0;
      padding-top: 10px;
      white-space: pre-wrap;
      line-height: 1.6;
      font-size: 14px;
    }
    .candidate:first-child {
      border-top: 0;
      padding-top: 0;
    }
    summary {
      cursor: pointer;
      font-weight: 700;
    }
    pre {
      overflow-x: auto;
      font-size: 12px;
      margin: 12px 0 0;
    }
    #status {
      margin-top: 10px;
      min-height: 24px;
      color: #5f6368;
    }
    @media (prefers-color-scheme: dark) {
      body { background: #171717; color: #f2f2f2; }
      input, section, details { background: #202124; color: #f2f2f2; border-color: #3c4043; }
      .candidate { border-color: #3c4043; }
      button { background: #8ab4f8; color: #0b1b32; }
      #status { color: #bdc1c6; }
    }
    @media (max-width: 460px) {
      main { width: min(100% - 24px, 900px); }
      .actions { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <h1>PlaceInfo Review</h1>
    <label>Latitude<input id="latInput" inputmode="decimal" autocomplete="off"></label>
    <label>Longitude<input id="lonInput" inputmode="decimal" autocomplete="off"></label>
    <div class="actions">
      <button id="searchButton" type="button">検索</button>
      <button id="copySummaryButton" type="button">📋 4行コピー</button>
      <button id="copyAllButton" type="button">📋 全件コピー</button>
    </div>
    <section>
      <h2>Labeler処理結果</h2>
      <div id="summary"></div>
    </section>
    <section>
      <h2>Yahoo API取得結果</h2>
      <div id="yahoo"></div>
    </section>
    <section>
      <h2>通り名判定</h2>
      <div id="roadAlias"></div>
    </section>
    <section>
      <h2>候補一覧</h2>
      <div id="candidates"></div>
    </section>
    <section>
      <h2>採用理由</h2>
      <div id="reasons"></div>
    </section>
    <details>
      <summary>Raw JSON</summary>
      <pre id="rawJson"></pre>
    </details>
    <div id="status"></div>
  </main>
  <script>
    const latInput = document.getElementById("latInput");
    const lonInput = document.getElementById("lonInput");
    const searchButton = document.getElementById("searchButton");
    const copySummaryButton = document.getElementById("copySummaryButton");
    const copyAllButton = document.getElementById("copyAllButton");
    const summaryBox = document.getElementById("summary");
    const yahooBox = document.getElementById("yahoo");
    const roadAliasBox = document.getElementById("roadAlias");
    const candidatesBox = document.getElementById("candidates");
    const reasonsBox = document.getElementById("reasons");
    const rawJson = document.getElementById("rawJson");
    const statusBox = document.getElementById("status");

    function setBusy(isBusy) {
      searchButton.disabled = isBusy;
      copySummaryButton.disabled = isBusy;
      copyAllButton.disabled = isBusy;
      searchButton.textContent = isBusy ? "検索中..." : "検索";
    }

    async function copyText(text, emptyMessage) {
      const value = (text || "").trim();
      if (!value) {
        statusBox.textContent = emptyMessage;
        return;
      }
      try {
        await navigator.clipboard.writeText(value);
        statusBox.textContent = "コピーしました";
      } catch (error) {
        statusBox.textContent = "コピーできませんでした。表示内容を長押しでコピーしてください";
      }
    }

    function buildAllText() {
      return [
        "Labeler処理結果",
        summaryBox.textContent.trim(),
        "",
        "Yahoo API取得結果",
        yahooBox.textContent.trim(),
        "",
        "通り名判定",
        roadAliasBox.textContent.trim(),
        "",
        "候補一覧",
        candidatesBox.textContent.trim(),
        "",
        "採用理由",
        reasonsBox.textContent.trim(),
        "",
        "Raw JSON",
        rawJson.textContent.trim(),
      ].join("\\n").trim();
    }

    function renderCandidates(items) {
      candidatesBox.innerHTML = "";
      if (!items || items.length === 0) {
        candidatesBox.textContent = "候補なし";
        return;
      }
      for (const item of items) {
        const div = document.createElement("div");
        div.className = "candidate";
        div.textContent = [
          "--------------------------------",
          "",
          `${item.index}.`,
          `名称: ${item.name || ""}`,
          `Category: ${item.category || ""}`,
          `Score: ${item.score || ""}`,
          `距離: ${item.distance_m || "取得不可"}`,
          `座標: ${item.coordinate || "取得不可"}`,
          `Where: ${item.where || ""}`,
          `Combined: ${item.combined || ""}`,
          `UID: ${item.uid || ""}`,
          "",
        ].join("\\n");
        candidatesBox.appendChild(div);
      }
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
        summaryBox.textContent = data.text || "";
        yahooBox.textContent = data.debug && data.debug.yahoo ? data.debug.yahoo : "";
        roadAliasBox.textContent = data.debug && data.debug.road_alias ? data.debug.road_alias : "";
        renderCandidates(data.debug && data.debug.candidates ? data.debug.candidates : []);
        reasonsBox.textContent = data.debug && data.debug.reasons ? data.debug.reasons.join("\\n") : "";
        rawJson.textContent = JSON.stringify(data.result || {}, null, 2);
        statusBox.textContent = data.text ? "" : "表示できる候補がありません";
      } catch (error) {
        statusBox.textContent = `検索できませんでした: ${error.message}`;
      } finally {
        setBusy(false);
      }
    }

    searchButton.addEventListener("click", search);
    copySummaryButton.addEventListener("click", () => copyText(summaryBox.textContent, "4行コピーする内容がありません"));
    copyAllButton.addEventListener("click", () => copyText(buildAllText(), "全件コピーする内容がありません"));
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


def _text(value: Any) -> str:
    return str(value or "").strip()


def _candidate_name(candidate: dict[str, Any]) -> str:
    return _text(candidate.get("name") or candidate.get("label"))


def _candidate_coordinate(candidate: dict[str, Any]) -> tuple[float | None, float | None]:
    try:
        lat = float(candidate.get("lat"))
        lon = float(candidate.get("lon"))
    except (TypeError, ValueError):
        return None, None
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None, None


def _find_candidate_by_name(candidates: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    if not name:
        return None
    for candidate in candidates:
        if _candidate_name(candidate) == name:
            return candidate
    return None


def _candidate_distance_from_result(result: dict[str, Any], candidate: dict[str, Any]) -> str:
    candidate_lat, candidate_lon = _candidate_coordinate(candidate)
    if candidate_lat is None or candidate_lon is None:
        return ""
    try:
        lat = float(result.get("lat"))
        lon = float(result.get("lon"))
    except (TypeError, ValueError):
        return ""
    return f"{round(distance_m(lat, lon, candidate_lat, candidate_lon))}m"


def _candidate_coordinate_text(candidate: dict[str, Any]) -> str:
    lat, lon = _candidate_coordinate(candidate)
    if lat is None or lon is None:
        return ""
    return f"{lat:.6f}, {lon:.6f}"


def _candidate_score_text(candidate: dict[str, Any]) -> str:
    value = candidate.get("score")
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _text(value)


def _road_alias_debug_text(result: dict[str, Any]) -> str:
    road_alias = result.get("road_alias") if isinstance(result.get("road_alias"), dict) else infer_road_alias_from_result(result)
    yahoo_intersections = road_alias.get("yahoo_intersections") if isinstance(road_alias.get("yahoo_intersections"), list) else []
    candidates = road_alias.get("road_alias_candidates") if isinstance(road_alias.get("road_alias_candidates"), list) else []
    candidate_lines = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        source_url = _text(candidate.get("source_url"))
        source_suffix = f" ({source_url})" if source_url else ""
        candidate_lines.append(
            f"- {_text(candidate.get('name'))}: {_text(candidate.get('matched_intersection'))}"
            f" / Yahoo={_text(candidate.get('yahoo_intersection'))}{source_suffix}"
        )
    return "\n".join(
        [
            f"Yahoo roadname: {_text(road_alias.get('yahoo_roadname')) or 'なし'}",
            f"Yahoo交差点名: {', '.join(_text(item) for item in yahoo_intersections if _text(item)) or 'なし'}",
            "road_alias候補:",
            *(candidate_lines or ["- なし"]),
            f"採用通り名: {_text(road_alias.get('adopted_roadname')) or 'なし'}",
            f"判定理由: {_text(road_alias.get('reason')) or 'なし'}",
        ]
    )


def placeinfo_admin_debug(result: dict[str, Any]) -> dict[str, Any]:
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    display = result.get("display_lines") if isinstance(result.get("display_lines"), dict) else {}
    debug = display.get("debug") if isinstance(display.get("debug"), dict) else {}
    intersection_name = _text(debug.get("intersection"))
    landmark_name = _text(debug.get("landmark"))
    intersection_candidate = _find_candidate_by_name(candidates, intersection_name)
    landmark_candidate = _find_candidate_by_name(candidates, landmark_name)

    candidate_rows = []
    for index, candidate in enumerate(candidates[:12], start=1):
        candidate_rows.append(
            {
                "index": index,
                "name": _candidate_name(candidate),
                "category": _text(candidate.get("category")),
                "score": _candidate_score_text(candidate),
                "distance_m": _candidate_distance_from_result(result, candidate),
                "coordinate": _candidate_coordinate_text(candidate),
                "where": _text(candidate.get("where")),
                "combined": _text(candidate.get("combined")),
                "uid": _text(candidate.get("uid")),
            }
        )

    yahoo_lines = [
        f"source: {_text(result.get('source'))}",
        f"raw_path: {_text(result.get('raw_path'))}",
        f"address: {' > '.join(str(part) for part in result.get('address', []) if str(part).strip())}",
        f"short_address: {_text(result.get('short_address'))}",
        f"roadname: {_text(result.get('roadname')) or 'なし'}",
        f"candidate_count: {len(candidates)}",
    ]

    taxi_label = result.get("taxi_label") if isinstance(result.get("taxi_label"), dict) else {}
    taxi_source = _text(taxi_label.get("source"))
    taxi_debug = taxi_label.get("debug") if isinstance(taxi_label.get("debug"), dict) else {}

    reasons = []
    if taxi_source == "override":
        override_id = _text(taxi_debug.get("override_id"))
        reasons.append(f"辞書適用: 秘伝のタレ{f' ({override_id})' if override_id else ''}")
    else:
        reasons.append("辞書適用: なし")
    reasons.extend(
        [
            "📍 取得元: Yahoo住所",
            "🚥 取得元: 未判定",
            "🏢 取得元: 未判定",
        ]
    )
    if intersection_candidate is not None:
        category = _text(intersection_candidate.get("category"))
        if category == "地点名":
            reasons[2] = "🚥 取得元: Yahoo地点名(Category=地点名)"
            reasons.append("🚥 採用理由: Yahoo地点名(Category=地点名)")
        else:
            reasons[2] = f"🚥 取得元: Yahoo候補(Category={category or '不明'})"
            reasons.append(f"🚥 採用理由: Yahoo候補(Category={category or '不明'})")
    elif display.get("intersection"):
        reasons[2] = "🚥 取得元: Yahoo Roadname"
        reasons.append("🚥 採用理由: Yahoo道路名採用")
    else:
        reasons[2] = "🚥 取得元: 候補なし"
        reasons.append("🚥 採用理由: 候補なし")

    if landmark_candidate is not None:
        reason = "🏢 強ランドマーク"
        category = _text(landmark_candidate.get("category"))
        landmark_source = f"Yahoo候補(Category={category or '不明'})"
        if taxi_source == "override":
            landmark_source = f"秘伝のタレ + {landmark_source}"
        reasons[3] = f"🏢 取得元: {landmark_source}"
        if intersection_candidate is not None:
            intersection_lat, intersection_lon = _candidate_coordinate(intersection_candidate)
            landmark_lat, landmark_lon = _candidate_coordinate(landmark_candidate)
            if None not in (intersection_lat, intersection_lon, landmark_lat, landmark_lon):
                distance = distance_m(intersection_lat, intersection_lon, landmark_lat, landmark_lon)
                reason = f"{reason}\n交差点から{round(distance)}m"
            else:
                reason = f"{reason}\n交差点距離は取得不可、Yahoo候補順で採用"
        reasons.append(reason)
    else:
        if taxi_source == "override":
            reasons[3] = "🏢 取得元: 秘伝のタレ"
        else:
            reasons[3] = "🏢 取得元: 候補なし"
        reasons.append("🏢 強ランドマークなし")

    return {
        "yahoo": "\n".join(yahoo_lines),
        "road_alias": _road_alias_debug_text(result),
        "candidates": candidate_rows,
        "reasons": reasons,
    }


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
                "copy_text": placeinfo_display_text(result),
                "debug": placeinfo_admin_debug(result),
                "result": {
                    "display_lines": result.get("display_lines", {}),
                    "short_address": result.get("short_address", ""),
                    "road_alias": result.get("road_alias", {}),
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
