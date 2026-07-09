# nagoya_event 現状仕様

最終更新: 2026-07-10

この文書は、現時点のコード実装を正として整理する。未実装の構想は末尾の「今後の予定」に分ける。仕様変更時は該当章へ追記し、運用上の注意が変わる場合は「運用メモ」も更新する。

## 1. 全体構成

`nagoya_event` は、名古屋周辺のイベント情報、道路情報、GPS/PlaceInfoレビュー情報を扱う運用リポジトリである。

主なデータ面は次の2系統に分ける。

- イベントDB: 公演、展示、道路、クルーズ船、アジア大会などイベント通知・日次投稿向け。
- 名古屋場所辞書DB: GPS/PlaceInfoレビュー、タクシー運用上の場所辞書、通り名、補正候補の管理向け。

現時点では、場所辞書の本体はローカルYAMLとGoogle Sheetsの併用である。Google Sheets側は `PlaceInfo_Review` のレビュー管理を開始しており、TB/TP、ランドマーク、道路上書き等は将来用シート名のみ定義済み。

## 2. イベントDB

イベントDBは `main.py` と `scrapers/` 配下を中心に動く。

主な入力:

- 各スクレイパーの取得結果
- `csv_events/*.csv`
- Google Sheetsのイベント系シート

主なGoogle Sheets同期:

- `sync_csv_to_sheet("csv_events/misonoza.csv", "御園座")`
- `sync_road_csv_to_sheet()`
- `sync_cruise_csv_to_sheet()`
- `sync_asia_csv_to_sheet()`
- `cleanup_old_cruise_rows(today)`
- `cleanup_old_asia_rows(today)`

Google SheetsのイベントDB IDは既存の `GOOGLE_SHEET_ID`、または `scrapers/utils/google_sheet_events.py` の既定URLから導出される。`config.py` では `EVENT_SHEET_ID` も定義し、未設定時は `GOOGLE_SHEET_ID` をfallbackとして使う。

## 3. 名古屋場所辞書DB

場所辞書DB用の設定は `config.py` にある。

優先ID:

1. `PLACE_DICT_SHEET_ID`
2. `LOCATION_SHEET_ID`
3. `EVENT_SHEET_ID`
4. 従来のGoogle Sheets設定

将来用を含むシート名:

- `PlaceInfo_Review`
- `TB_TP`
- `Landmarks`
- `Place_Label_Overrides`
- `Road_Aliases`
- `Road_Overrides`
- `Seeded_Taxi_Ops`

現時点でGoogle Sheets同期実装があるのは、`PlaceInfo_Review`、`Seeded_Taxi_Ops`、`Landmarks`、`Place_Label_Overrides`、`Road_Aliases` である。TB/TP、Road_Overrides、Seeded_Taxi_Ops等をGoogle Sheetsから読み込んで本番判定へ反映する実装はまだない。

## 4. PlaceInfo_Review

### 4.1 目的

Discordの「🚕 現在地テスト結果」投稿を抽出し、レビュー用データとしてTSVとGoogle Sheetsに同期する。Google Sheetsは人間がレビュー・補正する管理場所として扱う。

### 4.2 TSV

出力先:

```text
data/location/placeinfo_review.tsv
```

生成スクリプト:

```text
tools/location/export_placeinfo_review.py
```

抽出対象:

- Discord投稿本文に `🚕 現在地テスト結果` を含むもの

取得元:

- 保存済みJSONL: `data/ai/discord_history`
- Discord REST API: `--fetch-discord`

Discord API設定:

- チャンネルID: `GPS_REPORT_CHANNEL_ID` または `YAHOO_PLACEINFO_TEST_CHANNEL_ID`
- Bot Token: `DISCORD_BOT_TOKEN`
- `--limit 0` または `--all` で取得できる限り遡る
- Discord APIの1回最大100件制限に合わせ、内部で `before` ページングを行う

TSVの基本列:

```text
timestamp
message_id
lat
lon
address
current_guess
candidate1
candidate2
candidate3
candidate4
candidate5
google_maps_url
my_comment
expected
judge
fix_policy
fixed_at
retest_result
```

重複排除:

1. `message_id`
2. `lat + lon + timestamp`

`export_review_tsv_from_discord()` は既存TSVを読み込み、取得分とマージする。既存TSVにある `my_comment`、`expected`、`judge` 等は、同じキーの行では保持される。

### 4.3 Google Sheets同期

同期スクリプト:

```text
tools/location/sync_placeinfo_review_sheet.py
```

同期先:

- シート名: `PlaceInfo_Review`
- スプレッドシートID: 場所辞書DB優先。未設定時はイベントDBへfallback。

現在の同期方式:

- 既存Google Sheetsの `PlaceInfo_Review` を読み込む
- TSV由来の行と既存Sheet行をupsertマージする
- `message_id` 優先、空なら `lat + lon + timestamp` をfallback keyにする
- 既存行がある場合、自動更新列はTSV側で更新し、手動レビュー列はSheets側を保持する
- 新規行は追加する
- 重複行は作らない
- 書き戻しは `values.update(A1)` を使う
- 既存Sheetの方が長かった場合のみ、古い余剰行を部分clearする
- 全シートclearによる全置換はしない

自動更新列:

```text
timestamp
message_id
lat
lon
address
current_guess
candidate1
candidate2
candidate3
candidate4
candidate5
google_maps_url
```

手動保持列:

```text
my_comment
expected
judge
fix_policy
fixed_at
retest_result
reviewed
correct_address
correct_road
correct_intersection
correct_landmark
correct_label
note
```

重要方針:

- Google Sheets側で人間が編集した `reviewed`、`correct_*`、`note` 等は同期で潰さない。
- 手動レビュー列がTSVに空で存在していても、既存Sheet行がある場合はSheet側の値を保持する。
- Sheets側に追加列がある場合も、ヘッダー統合で消さない。

## 5. GPS/PlaceInfo表示

### 5.1 Web画面

Webアプリ:

```text
tools/location/gps_web_app.py
```

エンドポイント:

- `/gps`
- `/api/placeinfo`
- `/admin/placeinfo-test`
- `/api/admin/placeinfo-test`

`/gps` の仕様:

- 初回は `📍 現在地を取得` ボタンのみ表示
- 自動取得はしない
- 取得中はボタンを無効化し、`📡 現在地を更新しています...` を表示
- Geolocation設定は `enableHighAccuracy: true`, `timeout: 10000`, `maximumAge: 0`
- 取得成功後は `❌ 閉じる` と `🔄 現在地を更新` を表示
- 更新時はGPS、PlaceInfo、Discord投稿、画面表示を再実行する
- 閉じる処理は `history.back()` 優先、補助で `window.close()`

通常GPS画面の表示:

- `display_lines.text` を表示
- 候補件数と候補一覧も画面には残す
- Discord送信成功時は `Discordへ送信しました😇`

### 5.2 管理ページ

`/admin/placeinfo-test` はレビュー・開発専用ページである。

入力:

- Latitude
- Longitude

ボタン:

- `検索`
- `📋 4行コピー`
- `📋 全件コピー`

表示:

- Labeler処理結果
- Yahoo API取得結果
- 通り名判定
- 候補一覧
- 採用理由
- Raw JSON

候補一覧には、名称、Category、Score、距離、座標、Where、Combined、UIDを表示する。Scoreは小数2桁へ整形する。

4行コピーはLabeler処理結果のみをコピーする。全件コピーは画面に表示しているデバッグ情報一式をコピーする。

管理ページだけ、📍・🛣️・🚥・🚖・🏢の取得元と採用理由を表示する。GPS画面とDiscord投稿は簡潔表示を維持する。

## 6. PlaceInfoラベル生成

現在のPlaceInfo取得は `get_hybrid_placeinfo.py` にあるが、ユーザー向け表示の主役はYahoo PlaceInfoである。OSM候補は本文表示候補としては使わず、現時点では `OSMDisabled` として互換形だけ残している。

処理の入口:

```text
get_hybrid_placeinfo(lat, lon)
```

現在の結果形:

- `source`: `YahooPrimaryPlaceInfo`
- `short_address`: Yahoo優先
- `candidates`: Yahoo候補
- `road_alias`: road_alias判定結果
- `taxi_label`: 秘伝のタレ、Yahoo交差点、Yahooランドマーク等の比較用ラベル
- `display_lines`: 実表示用の短い行

`display_lines` の表示順:

```text
📍 住所
🛣️ 通り名
🚥 交差点
🚖 TP/TBまたはタクシー運用系辞書
🏢 ランドマーク辞書
座標: lat, lon
```

注意:

- `🏢` はYahoo候補由来では自動表示しない。
- `🏢` を表示するのは、現時点では秘伝のタレなど辞書ヒット時のみ。
- `🚖` は `place_label_overrides.yml` の `source: seeded_taxi_ops` に当たった場合に表示する。
- Yahoo候補一覧はadminデバッグには残す。

### 6.1 TP/TB表示

TP/TBやタクシー乗り場などタクシー運用系の場所は、`data/location/place_label_overrides.yml` の `source: seeded_taxi_ops` で管理する。

判定仕様:

- 現在座標と辞書中心座標の距離が `radius_m` 以内ならヒット
- 複数ヒット時は `priority` が小さいものを優先し、同priorityなら距離が近いものを優先
- `source: seeded_taxi_ops` がヒットした場合、`display_lines` に `🚖 label` を表示する
- 範囲外では🚖行を表示しない
- Google Sheets同期では `Seeded_Taxi_Ops` シートへsafe upsertする

新幹線口TP:

```text
id: nagoya_station_taikodori_taxi_stand
label: 新幹線口TP
center: 35.169980, 136.880800
radius_m: 60
source: seeded_taxi_ops
priority: 200
```

実測確認:

- 実測ズレ座標 `35.170216, 136.880259`
- 中心点からの距離は約55.74m
- 最小整数半径は56mだが、既存TP/TB辞書の10m刻み運用とGPS誤差の微小な揺れを考慮し、既存値と同じ `radius_m: 60` を採用する

現時点ではTP/TBのpolygon判定は未実装。円形radiusで一般道路や隣接施設へ誤爆する地点が増える場合は、将来的にpolygon/geometry判定へ移行する。

## 7. road_alias / 通り名判定

道路辞書:

```text
data/location/road_aliases.yml
```

判定コード:

```text
tools/location/road_aliases.py
```

辞書項目:

- `id`
- `name`
- `direction`
- `aliases`
- `source_url`
- `start`
- `end`
- `road_numbers`
- `intersections`
- `geometry`
- `note`

判定仕様:

本番の🛣️通り名表示は次の優先順位で決める。

1. 表示用Yahoo交差点限定road_aliasで、東西道路と南北道路が両方確定した `東西道路 × 南北道路`
2. OSM geometry道路データの `display_name`
3. Yahoo `roadname` fallback

Yahoo交差点辞書で片方向だけ確定した場合、または未登録の場合は、その片方向road_aliasを本番🛣️行へは採用せず、OSM geometry判定へ進む。OSM geometryも採用できない場合だけYahoo `roadname` fallbackを使う。

OSM geometry採用条件:

- ローカル保存済みOSM way geometryのみを使う
- GPSリクエストごとにOSM APIやOverpass APIへアクセスしない
- 現在座標から最寄りOSM道路geometryまでの距離が `DEFAULT_MAX_DISTANCE_M = 30.0` m以内の場合だけ採用する
- 閾値外、データなし、座標不正の場合はOSM geometryを採用しない

OSM道路名の役割:

- `osm_name`: OSM上の道路名
- `display_name`: タクシー向け表示名

例:

```text
osm_name: 大須本通
display_name: 本町通
```

OSM geometryで採用できない場合は、Yahoo `roadname` fallbackへ進む。Yahoo採用交差点限定road_aliasの照合自体は維持し、東西道路と南北道路が両方確定した場合だけOSMより優先する。

Yahoo採用交差点限定road_alias:

1. Yahoo候補のうち `Category=地点名` の候補から、表示用の🚥交差点を先に確定する
2. road_aliasの表示判定には、表示用に採用したYahoo交差点だけを使う
3. 採用交差点名を正規化する
4. 採用交差点名を `road_aliases.yml` の `intersections` と完全一致照合する
5. 採用交差点内で `direction` が `east_west` と `north_south` に分かれる
6. 採用交差点内で東西道路と南北道路が1本ずつ確定できた場合だけ、本番🛣️行に `東西道路 × 南北道路` として採用する
7. 採用交差点内で片方のみ確定した道路名は、adminデバッグやfallback候補として保持するが、本番🛣️行には単独採用しない
8. 同方向で複数候補がある場合は、Yahoo `roadname` が辞書の `name` または `aliases` と一致するものを優先
9. 採用交差点でroad_alias未確定かつYahoo `roadname` が人間向け通り名として使える場合はfallbackとして採用する
10. Yahoo `roadname` も空またはfallback不適格なら🛣️行は表示しない

表示用に採用した交差点以外のYahoo地点名候補から、表示用road_aliasを採用しない。たとえば🚥が `丸の内オフランプ交差点` の場合、2位以下の `新御園橋交差点` から `外堀通` を採用しない。

adminデバッグでは、OSM geometry判定、表示判定に使ったroad_alias候補、参考用の全road_alias候補を分けて表示する。これにより、2位以下のYahoo交差点候補の辞書ヒットはレビュー材料として残しつつ、本番表示には混ぜない。

最終採用元は `road_alias.adoption_source` で確認できる。

- `osm_geometry`
- `adopted_yahoo_intersection`（東西道路と南北道路が両方確定した場合）
- `yahoo_roadname_fallback`

Yahoo `roadname` fallback:

- `伊勢町通り` のような末尾 `通り` は `伊勢町通` に正規化する
- `県道`、`国道`、`市道`、`名古屋高速`、`高速`、`IC`、`JCT`、`インター` を含む道路名は採用しない
- `通`、`線`、`筋` のいずれも含まない名称は採用しない

正規化:

- 全角数字を半角化
- 空白、全角空白、中黒、ハイフン類を除去
- 末尾の `交差点` を除去
- `三ッ蔵` / `三ツ蔵` は `三蔵` として照合する

現時点の辞書データは、Wikipedia由来の主要道路と、OSM由来で補強した三蔵通を含む。三蔵通はOSM way idとgeometry文字列を `geometry` に保存している。`geometry` は保存のみで、現時点の判定には使っていない。

2026-07時点で、実測レビューに基づき以下の交差点を辞書へ追加している。

- `錦通伊勢町交差点` -> `錦通`
- `三ッ蔵通大津交差点` / `三蔵通大津交差点` -> `三蔵通 × 大津通`
- `天王崎橋東交差点` -> `三蔵通`
- `天王崎橋交差点` -> `三蔵通`
- `伏見魚ノ棚交差点` -> `伏見通`

### 7.1 OSM geometry道路データ

OSM way geometryを使った座標沿い道路判定を、本番の🛣️通り名表示の第1優先として使う。

データ:

```text
data/location/osm_road_geometries.yml
```

コード:

```text
tools/location/osm_road_geometry.py
```

目的:

- Wikipedia由来の交差点辞書やYahoo `roadname` だけでは、細街路や商店街付近で1本隣の道路名を拾うことがある
- OSM way geometryから現在座標に最も近い名前付き道路を判定し、通り名改善に使えるか評価する

現在の扱い:

- 本番の `display_lines`、GPS画面、Discord投稿の🛣️行に反映する
- `get_hybrid_placeinfo()` の結果に `osm_road_geometry` を保持する
- `comparison.osm_geometry_road` にOSM geometry候補の道路名を保存する
- `comparison.final_road` と `comparison.final_road_source` に本番採用結果を保存する
- `/admin/placeinfo-test` では「OSM geometry道路判定」欄で距離、閾値、way id、採用可否を表示する

OSMデータ取得方法:

- Overpass APIでは `way["highway"]["name"=...]` または `name` / `alt_name` / `old_name` 検索に `out geom tags` を使う
- 小範囲の確認では OSM API map endpoint からbbox内のwayを取得し、`highway` と `name` を持つwayを抽出する
- 実行時に毎回OSM APIへアクセスせず、取得したway id、道路名、geometryをローカルYAMLへ保存する

現在の実験データ:

- `三蔵通`: OSM `name=三蔵通`
- `本町通`: OSM上の近傍way名は `大須本通`。タクシー向け期待表示に合わせ、実験データでは `display_name=本町通` として保存する
- `門前町通`: OSM `name=門前町通り`。大須本通/本町通との誤判定比較用

実測確認:

- `35.166229, 136.897967` はOSM geometry道路判定で `三蔵通`
- `35.160399, 136.901881` はOSM geometry道路判定で `本町通`
- 後者では `門前町通` は100m以上離れており、OSM geometry距離判定なら1本東側の誤採用を避けられる

注意:

- OSM nameとタクシー向け表示名が一致しない場合があるため、`osm_name` と `display_name` を分けて管理する
- OSM geometryで採用できない場合のfallbackとして、現在のYahoo road_alias / roadname処理を維持する
- OSM geometryデータを増やすまでは、未登録エリアでは従来fallbackが主に使われる

## 8. Discord投稿

GPS取得後のDiscord投稿は `gps_web_app.py` の `placeinfo_summary()` で生成する。

現在の投稿形:

```text
🚕 現在地テスト結果

📍 住所
🛣️ 通り名
🚥 交差点
🚖 TP/TB ※あれば
🏢 ランドマーク ※辞書ヒット時のみ
座標: lat, lon

結果が違う場合は、この投稿にリプライで正解を教えてください😇
```

Discord投稿には候補一覧を出さない。候補一覧、Raw JSON、採用理由はadminデバッグ専用である。

投稿先:

- Bot投稿: `DISCORD_BOT_TOKEN` + `GPS_REPORT_CHANNEL_ID`
- Webhook fallback: `GEMMA_DISCORD_WEBHOOK` または `GEMMA_WEBHOOK_URL`

`allowed_mentions` は空にし、不要なメンションを抑制する。

投稿後は `data/location/placeinfo/*.json` に保存する。保存内容には、座標、短縮住所、roadname、候補、taxi_label、comparison、Discord投稿成否などを含む。個人情報、乗務員情報、売上情報は保存しない。

## 9. Google Sheets同期

認証ファイル:

```text
credentials/credentials.json
credentials/token.json
```

これらはGit管理に載せない。

イベント系同期は `scrapers/utils/google_sheet_events.py` の共通処理を使う。場所辞書DBの `PlaceInfo_Review` 同期も同じGoogle Sheets APIクライアントを使うが、スプレッドシートIDは場所辞書DB優先で解決する。

同期時の基本方針:

- イベント系のCSV同期は既存仕様を維持
- `PlaceInfo_Review` は人間レビュー列を保持するupsert同期
- 場所辞書YAMLの同期も、人間レビュー列を保持するupsert同期
- 同期失敗はログに出す
- 朝のイベント同期全体を壊さないよう、PlaceInfo同期は個別 `try/except` で隔離する

手動同期:

```bash
python3 tools/location/export_placeinfo_review.py --fetch-discord --limit 500
python3 tools/location/sync_placeinfo_review_sheet.py
python3 tools/location/sync_place_dict_sheets.py
```

全件寄り取得:

```bash
python3 tools/location/export_placeinfo_review.py --fetch-discord --all
```

### 9.1 場所辞書YAML同期

同期スクリプト:

```text
tools/location/sync_place_dict_sheets.py
```

同期先は `PLACE_DICT_SHEET_ID` を最優先する。未設定時は `LOCATION_SHEET_ID`、`EVENT_SHEET_ID`、従来設定へfallbackする。

同期対象:

```text
data/location/place_label_overrides.yml
data/location/road_aliases.yml
```

`place_label_overrides.yml` は `source` ごとに分割して同期する。

| source | 同期先シート |
|---|---|
| `seeded_taxi_ops` | `Seeded_Taxi_Ops` |
| `seeded_landmark` | `Landmarks` |
| `user_corrected` | `Place_Label_Overrides` |

`road_aliases.yml` は全件を `Road_Aliases` へ同期する。

一意キー:

- 場所補正系: `id` 優先。`id` が空なら `source + lat + lon + label`
- road_alias系: `id` 優先。`id` が空なら `name + direction + start + end`

自動管理列:

- 場所補正系: `id`, `lat`, `lon`, `radius_m`, `label`, `source`, `confidence`, `priority`
- road_alias系: `id`, `name`, `direction`, `aliases`, `source_url`, `start`, `end`, `road_numbers`, `intersections`, `geometry`, `source_note`

手動保持列:

```text
reviewed
note
enabled
updated_by
```

重要方針:

- シート全体clearは禁止。
- 既存Sheetを読み込み、ローカルYAMLとupsertする。
- 既存行がある場合、ローカル自動列は更新し、手動保持列はSheets側を保持する。
- 重複キー行がある場合は1行に統合し、手動列の値は空でないものを保持する。
- 書き戻し後に古い余剰行が残る場合のみ、余剰範囲を部分clearする。
- `road_aliases.yml` のYAML側 `note` は、Sheets手動列 `note` と衝突させず `source_note` として同期する。

## 10. systemd timer / 定期実行

READMEでは、日次イベント処理はcronまたは同等の定期実行から以下を起動する運用になっている。

```bash
/home/ubuntu/nagoya_event/.venv/bin/python /home/ubuntu/nagoya_event/main.py
```

`main.py` の末尾では、Discord投稿後に各Google Sheets同期を実行する。PlaceInfo_Review同期もこの流れに追加済みで、失敗してもイベント同期全体は止めない。

リポジトリ内のsystemdファイル:

- `nagoya-scheduler.service`: `tools/scheduler/run_scheduler.py` を常駐実行する。現時点ではOpen-Meteo予報投稿の定時ジョブ用。
- `nagoya-road-monthly.timer`: 毎月1日の道路PDF監視ジョブを複数時刻で実行する。
- GPS Web Appのsystemd user service化は `scripts/install_gps_systemd.sh` と `docs/gps_tailscale_funnel.md` を参照。

リポジトリ内には、`main.py` を朝6:00に起動するtimerファイルは見当たらない。Oracle側のcronまたは外部systemd timerで `main.py` が朝6:00系に実行される前提の運用である。

## 11. Oracle運用メモ

本番想定パス:

```text
/home/ubuntu/nagoya_event
```

基本操作:

```bash
cd /home/ubuntu/nagoya_event
.venv/bin/python -m pip install -r requirements.txt
```

GPS Web App:

```bash
systemctl --user restart gps-web
journalctl --user -u gps-web -n 50 --no-pager
```

イベント日次処理:

```bash
/home/ubuntu/nagoya_event/.venv/bin/python /home/ubuntu/nagoya_event/main.py
```

PlaceInfoレビュー同期:

```bash
python3 tools/location/export_placeinfo_review.py --fetch-discord --limit 500
python3 tools/location/sync_placeinfo_review_sheet.py
python3 tools/location/sync_place_dict_sheets.py
```

新幹線走行位置の手動取得:

```bash
python3 tools/railway/fetch_shinkansen_position.py
python3 tools/railway/analyze_shinkansen_position.py --summary-yaml
```

注意:

- `.env`、`credentials/token.json`、`credentials/credentials.json` はcommitしない。
- `PLACE_DICT_SHEET_ID` または `LOCATION_SHEET_ID` を設定すると、PlaceInfo_Reviewは名古屋場所辞書DBへ同期される。
- 未設定時は従来のイベントDBへfallbackする。
- Google Sheets側の手動レビュー列は同期で潰さない方針。

## 12. 東海道新幹線走行位置

目的:

- JR東海公式の列車走行位置JSONを手動取得し、列車ごとの遅延分数を保存・解析する。
- 公式運行情報の文章だけでは判断しづらい遅延規模を、列車単位の `delay` から補助的に確認する。
- 現時点では通知実装は行わず、Gemma投入用summary候補を作るところまで。

公式ページ:

```text
https://traininfo.jr-central.co.jp/shinkansen/pc/ja/ti08.html
```

取得URL:

```text
https://traininfo.jr-central.co.jp/shinkansen/var/train_info/train_location_info.json
https://traininfo.jr-central.co.jp/shinkansen/common/data/common_ja.json
```

保存先:

```text
data/railway/shinkansen_position/
```

実装:

```text
tools/railway/fetch_shinkansen_position.py
tools/railway/analyze_shinkansen_position.py
```

保存仕様:

- `fetch_shinkansen_position.py` は `train_location_info.json` と駅名・列車名辞書の `common_ja.json` を取得する。
- 取得結果は `YYYYMMDD_HHMMSS_shinkansen_position.json` として保存する。
- snapshotには `source_url`、`common_url`、`fetched_at`、`payload`、`common` を含める。
- 公式サイトへ過剰アクセスしないため、現時点では手動実行のみ。自動ポーリングや通知は未実装。
- 失敗時はtracebackを出さず、標準エラーへ短いログを出して終了する。

解析仕様:

- `analyze_shinkansen_position.py` は保存済みsnapshotを読み込む。引数省略時は保存先ディレクトリの最新snapshotを使う。
- `atStation.bounds` と `betweenStation.bounds` の各列車を正規化する。
- 取得できる主な項目:
  - `train_no`: `のぞみ288` など、列車種別名 + 列車番号
  - `direction`: `up` / `down`
  - `position`: 駅番線、または駅間の概略
  - `delay_min`: JSON上の `delay`
- JSON構造が変わった場合でも、存在しないキーは空扱いにし、解析処理で例外停止しない。

判定対象:

- 東海道新幹線区間のみを対象にする。
- 山陽区間は `ignored_reason: 山陽区間のため対象外` としてsummary上は参考情報に回し、通常severity・終電接続riskの判定から除外する。
- 山陽直通列車でも、現在位置が東海道区間に入っている場合は対象にする。

通常遅延severity:

- `delay_min >= 30` の東海道区間列車を `severity_alerts` に出す。
- 通常遅延severityと終電接続riskは別軸として扱う。

終電帯接続risk:

ルールファイル:

```text
data/railway/shinkansen_terminal_connection_rules.yml
```

現時点の暫定ルール:

- `のぞみ549号`: `delay_min >= 20` で名東方面リスク
- `ひかり669号`: `delay_min >= 10` で名東方面リスク
- `のぞみ108号`: `delay_min >= 40` で名東方面リスク

ひかり669号:

- 名古屋23:49着想定。
- 東山線名東方面への乗換余裕が極めて小さいため、10分遅れから終電接続リスクとして扱う。
- 過去実走・営業感覚で、10分程度の遅れでも名東方面需要が増えた記憶あり。

現時点では名古屋到着見込み時刻の再計算は行わず、列車番号別の遅延閾値で判定する。

Gemma投入用summary候補:

```yaml
source: shinkansen_position
line: tokaido_shinkansen
max_delay_min: 20
severity_alerts: []
terminal_connection_risks:
- train_name: "ひかり"
  train_number: "669"
  direction: "down"
  delay_min: 10
  position: "名古屋付近"
  risk_area: "名東方面"
  threshold_min: 10
  reason: "ひかり669号は名古屋23:49着想定で、10分遅れから東山線接続が危険"
delayed_trains:
- train_no: "のぞみxxx"
  direction: "up"
  delay_min: 10
  position: "名古屋付近"
ignored_trains: []
```

現時点の注意:

- `train_location_info.json` は東海道・山陽新幹線全体の走行位置を含む。
- 遅延分数は列車単位で取れるが、公式運行情報の原因・区間文章とは別データとして扱う。
- 通知投稿、名古屋到着見込み時刻の推定、他社線終電時刻との照合は未実装。

## 13. Railway Incident管理

目的:

- 同一交通障害を1つのincidentとして管理し、Gemmaの類似投稿連投を抑制する。
- 公式文面の軽微な変更、遅延分数の小幅変化、復旧見込み時刻の更新だけでは新規incidentを作らない。
- severity上昇、30分以上の通常遅延閾値突破、終電接続risk新規発生、運転見合わせ、復旧など、需要影響が変わる場合のみ再通知候補にする。

実装:

```text
tools/railway/railway_incident_manager.py
```

state保存先:

```text
data/railway/incidents/railway_incidents.json
```

保存仕様:

- JSONで `version` と `incidents` を保存する。
- 保存は一時ファイルへ書き込み後 `os.replace` するatomic write。
- 同一プロセス/同一ホスト上の競合を避けるため、可能な環境では `fcntl.flock` による `.lock` ファイル排他を使う。
- state JSONが壊れている場合はログを出し、安全側で空stateとして扱う。

incident_id:

- 取得時刻そのものだけでは作らない。
- `operator`、`line`、正規化した `reason`、正規化した `affected_section` からfingerprintを作る。
- 初回検知時に `operator_line_YYYYMMDD_reason_001` 形式のIDを発行する。
- 復旧済みincidentと同じfingerprintで新しい障害が発生した場合は、同日の連番を進めて新しいincident_idを発行する。

保持する主な項目:

- `incident_id`
- `operator`
- `line`
- `status`
- `reason`
- `affected_section`
- `first_detected_at`
- `last_seen_at`
- `last_notified_at`
- `last_message_fingerprint`
- `severity`
- `max_delay_min`
- `terminal_connection_risks`
- `notification_count`

同一incident判定:

- 同じ `operator`、`line`、正規化reason、正規化affected_section のopen incidentがあれば同一incidentとして扱う。
- 時刻表記、遅延分数、対象列車数などの軽微な文面変化はfingerprintに入れない。
- 別原因、別路線、明確に別区間の場合は別incidentとする。

通知抑制:

- 初回検知は `should_notify = true`
- 同一incidentで意味のある変化がなければ `should_notify = false`
- 公式文面だけの軽微変更では再通知しない
- 遅延分数が変わっただけでは毎回通知しない

再通知候補:

- `severity` が上昇
- `max_delay_min` が30分閾値を新たに超えた
- `terminal_connection_risks` が新規発生
- `status` が運転見合わせ相当へ悪化
- 影響区間が明確に変化
- 復旧

新幹線走行位置JSONとの関係:

- `analyze_shinkansen_position.py` のsummaryに含まれる `max_delay_min`、`severity_alerts`、`terminal_connection_risks` をincident eventへ反映できる構造にしている。
- 通常severityと終電接続riskは別軸を維持する。
- 山陽区間は走行位置summary側で `ignored_reason` 付きの参考情報へ回し、incident判定の主要対象は東海道区間とする。

現時点のGemma連携:

- 本番の `run_gemma_ollama.py` への通知抑制差し込みはまだ行っていない。
- 既存の鉄道取得、pre-LLM filter、state diff、cooldown、復旧通知の分岐が複雑なため、今回はincident manager単体とintegration helperに留める。
- 次段階では、鉄道alertまたは新幹線走行位置summaryをincident eventへ変換し、`should_notify` がtrueの場合のみGemma入力・投稿候補へ進める。

既存の鉄道→Gemma→Discord経路:

- 取得: `tools/ai/railway_status_normalizer.py` の `get_all_railway_alerts_snapshot()`
- 監視時間判定: `tools/ai/run_gemma_ollama.py` の `is_railway_monitoring_active()`
- 0:00〜5:00の新幹線通常監視休止、重大交通incident時の監視延長は既存仕様を維持する。
- 既存抑制: `railway_filters.py`、`railway_state.py`、`railway_beta_state.json`、`railway_beta_last_notify.json`
- コメント生成/投稿候補: `run_gemma_ollama.py` の `railway_beta_comment` 系分岐
- 履歴: `railway_history.py`

## 14. テスト

主な確認コマンド:

```bash
python3 -m py_compile main.py config.py tools/ai/*.py tools/location/*.py tools/railway/*.py
.venv/bin/python -m pytest tests/test_osm_road_geometry.py tests/test_road_aliases.py tests/test_place_labeler.py tests/test_hybrid_placeinfo.py tests/test_placeinfo_review_export.py tests/test_sync_placeinfo_review_sheet.py tests/test_sync_place_dict_sheets.py tests/test_shinkansen_position.py tests/test_railway_incident_manager.py -q
git diff --check
```

PlaceInfo同期の重要テスト:

- `tests/test_sync_placeinfo_review_sheet.py`
- Sheets側だけの `reviewed`、`correct_*`、`note` が保持されること
- `message_id` またはfallback keyで重複行を作らないこと

road_aliasの重要テスト:

- `tests/test_osm_road_geometry.py`
- `tests/test_road_aliases.py`
- 主要交差点から通り名が判定できること
- 東西道路と南北道路が `東西 × 南北` の順で表示されること
- 複数候補時にYahoo roadname一致を優先すること
- 別々のYahoo交差点候補をまたいで通り名を混ぜないこと
- Yahoo採用交差点で東西道路と南北道路が両方確定した場合は、OSM geometryより `東西 × 南北` を優先すること
- Yahoo採用交差点で片方向だけ確定した場合は単独採用せず、OSM geometryまたはYahoo roadname fallbackへ進むこと
- road_alias未登録時にYahoo roadname fallbackが効くこと
- OSM geometryで三蔵通と本町通の実測座標を本番通り名へ採用できること
- OSM `osm_name` とタクシー向け `display_name` を分離できること
- OSM geometry距離閾値外では従来fallbackへ戻ること

場所辞書同期の重要テスト:

- `tests/test_sync_place_dict_sheets.py`
- `seeded_taxi_ops` が `Seeded_Taxi_Ops` へ同期されること
- `seeded_landmark` が `Landmarks` へ同期されること
- `user_corrected` が `Place_Label_Overrides` へ同期されること
- `road_aliases.yml` が `Road_Aliases` へ同期されること
- `reviewed`、`note`、`enabled`、`updated_by` が保持されること
- 全シートclearを行わないこと

新幹線走行位置の重要テスト:

- `tests/test_shinkansen_position.py`
- 列車番号、方向、位置、遅延分数を正規化できること
- 最大遅延分数と遅延列車一覧をsummary化できること
- 東海道区間のみ通常severity・終電接続riskの判定対象にすること
- `のぞみ549号`、`ひかり669号`、`のぞみ108号` の暫定終電接続riskを判定できること
- 山陽区間の列車は `ignored_reason` 付きで判定対象外にできること
- JSON構造欠落時も例外停止しないこと
- timestamp付きファイル名で保存できること

Railway Incident管理の重要テスト:

- `tests/test_railway_incident_manager.py`
- 初回障害は新規incident_idを発行し通知対象にすること
- 同一障害、同一内容、軽微な文面変更は抑制すること
- 20分から35分など30分閾値を新たに超えた場合は再通知候補にすること
- `ひかり669号` など終電接続risk新規発生は再通知候補にすること
- 別原因は別incidentにすること
- 復旧は同一incident_idで通知候補にし、復旧後の同一fingerprint新規障害は新incident_idにすること
- 壊れたstateでも全体停止しないこと

## 15. 今後の予定

未実装、または構想段階のもの:

- `TB_TP` シートからタクシー乗り場・タクシープール辞書を読み込む
- `Landmarks` シートから強ランドマーク辞書を読み込む
- `Road_Overrides` シートから道路・通り名補正を読み込む
- `Seeded_Taxi_Ops` シートから初期タクシー運用ランドマークを読み込む
- `Place_Label_Overrides` / `Road_Aliases` のSheets側編集をローカルYAMLへpullする
- PlaceInfo_Reviewの `correct_*` から辞書候補を半自動生成する
- Discord正解リプライからpending補正候補を作る
- OSM geometry道路データを名古屋中心部の主要通りへ拡張する
- Yahoo交差点に出ない細街路向けの交差点辞書を追加する
- 管理ページからGoogle Sheets行または辞書候補へ直接反映する
- Google Maps座標貼り付けから `/admin/placeinfo-test` を直接検索する
- TP/TBの円形radiusで誤爆が出る地点はpolygon/geometry判定へ移行する
- 新幹線走行位置summaryを既存の鉄道通知/Gemma判断へ接続する
- 終電帯は小幅遅延でも他社線接続影響を強めに評価する
- Railway Incident管理を `run_gemma_ollama.py` の鉄道通知分岐へ接続する
- 公式alertと新幹線走行位置summaryを統合したincident event変換器を本番経路へ入れる

## 16. 変更時の追記ルール

仕様変更時は次の順で更新する。

1. 実装コードとテストを更新
2. このSPECの該当章を更新
3. 運用コマンド、環境変数、Google Sheets列が変わる場合は必ず追記
4. 未実装の構想は「今後の予定」へ移す
5. 手動レビュー列を破壊する可能性がある同期変更は、必ずテストを追加してから反映する
