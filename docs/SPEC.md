# nagoya_event 現状仕様

最終更新: 2026-09-15

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

### 2.1 道路情報

道路情報は主に `scrapers/road_pdf.py` が愛知県警PDFを処理し、`csv_events/road.csv` を生成する。

流れ:

1. 愛知県警PDFから通常の取締・オービス予定を抽出する
2. 画像化された重点取締枠はOCRで読み取る
3. `csv_events/road.csv` へ保存する
4. `main.py` の `load_road_events()` が当日分を読み込む
5. `build_road_message()` がDiscord投稿文を作る
6. `sync_road_csv_to_sheet()` がGoogle Sheetsの `道路情報` へ同期する

通常運用のDiscord投稿では、`道路情報` Google Sheetsを正本として読む。Sheets取得に失敗した場合のみ `csv_events/road.csv` へfallbackする。テストや手元確認で明示的にCSVパスを渡した場合は、そのCSVだけを読む。

重点取締OCRでは、交通安全運動など季節・期間名を含む定型イベントについて、`data/road/traffic_safety_campaigns.yml` の実施期間と取得対象日を照合する。期間外の `春の全国交通安全運動期間中の交通指導取締り` は本番採用しない。OCR誤認を `春` から `夏` などへ機械置換することは禁止する。不整合時は `road_ocr: rejected seasonal mismatch ...` を出力し、CSV生成、Google Sheets同期、Discord投稿の各入口で防御的に除外する。

`道路情報` Google Sheets同期はsafe upsert方式である。同期前に既存Sheetを読み、CSV由来の新規行は追加し、既存行は `sync_key` 優先で突合する。`sync_key` がない旧行は、重複しない場合のみ `date + venue + note + source + url` をfallback keyとして照合する。CSV由来行の `sync_key` は `date + venue + title + note + source + url` から生成する。

道路情報の手動管理列:

- `sync_key`: CSV由来行の安定キー。タイトル手修正後も同一行として扱うために保持する。
- `manual_override`: true相当の場合、Sheets側の値をCSVで上書きしない。
- `reviewed`: 人間レビュー状態。同期では保持する。
- `updated_by`: 手動更新者メモ。同期では保持する。
- `source_detail` / `memo`: `秘密`、`secret`、`手動` を含む場合は保護行として扱う。

保護対象:

- `manual_override` がtrue相当の行
- `status` が `manual` または `secret` の行
- `source`、`source_detail`、`note`、`memo` に `手動`、`秘密`、`secret` を含む行

保護対象行はCSVに存在しなくても削除しない。CSVに存在しないSheets専用行も基本的に保持する。期間不整合の自動生成行だけは、保護対象でない場合に同期結果から除外できる。道路情報同期ではシート全体clearは禁止し、必要な場合も書き戻し後の余剰範囲だけを消す。

愛知県警の月次取締予定は `tools/road/check_monthly_road_pdf.py` が対象ページと当月PDFを監視する。実行時刻は `nagoya-road-monthly.timer` で毎日10:05、10:15、12:00、18:05 JSTとし、当月分を取得済みならstateにより即時skipする。月初に未公開・取得失敗でも後続日に再試行し、10:00ちょうどの公開更新と競合しないよう、タイマーには `Asia/Tokyo` を明記する。

月次取得の流れ:

1. 対象HTMLを一般的なChrome User-Agent、キャッシュ抑止query、`Cache-Control: no-cache`付きで取得する。HTTP 200、HTML Content-Type、空でない本文を必須とする。
2. HTML上の `torishimariyoteiR*.pdf` リンクから公開済み月を確認する。
3. 当月PDFを同じUser-Agentとキャッシュ抑止付きで取得する。redirectは通常追従し、HTTP 200、`application/pdf`、空でない本文を必須とする。403、redirect loop、HTML応答、0 byteは取得失敗とし、既存PDFを上書きしない。
4. 当月PDF単体を先に解析し、raw、重複排除後、当日以降の件数を確認する。
5. 当月レコードを1件以上確認できた場合だけ、全月CSVを再生成してGoogle Sheetsへsafe upsertする。
6. Sheets同期後、当日より前の行を `【過去】道路情報` へ移す。

PDF解析とCSV生成の成功は、Google Sheets同期の成否とは別にstateへ確定する。Sheets認証で `RefreshError` / `invalid_grant` が発生した場合も、取得済みPDF、生成済みCSV、月次stateを保持し、`sheet_sync_pending=true` と `sheet_sync_reason=oauth_refresh_failed` を記録する。次回の月次実行は対象HTMLやPDFを再取得せず、保存済みCSVからSheets同期だけを再試行する。同期成功後に `sheet_sync_pending=false` とし、過去行の移動まで実施する。

0件や異常時は次の状態を区別する。

- `official_no_schedule`: 当月PDFに公式の予定なし表記がある。
- `publication_not_updated_yet`: HTMLが前月リンクのみ、更新時刻が当日10時より前、または月初の再取得結果が同一ETagである。
- `fetch_or_parse_error`: HTTP失敗、PDF取得失敗、HTML/PDF構造変更、予定なし表記のない解析0件。

18:00より前の0件・取得失敗は試行回数にかかわらず再試行可能状態とし、JST 18:00以降の失敗だけを当日の最終失敗として管理者通知対象にする。最終失敗後も当月分を取得済みにはせず、後続日のtimerで再試行する。異常時はdebug JSONと診断ログだけを保存し、既存 `road.csv` とGoogle Sheetsを更新・削除しない。空CSVを `sync_road_csv_to_sheet()` に渡した場合も `empty_csv` として書き込みを行わない。

主な診断ログ:

```text
road_scraper_started_at
road_scraper_http_status
road_scraper_final_url
road_scraper_html_length
road_scraper_page_month
road_scraper_raw_records
road_scraper_parsed_records
road_scraper_future_records
road_scraper_csv_records
road_sheet_sync_status
road_sheet_sync_reason
road_sheet_sync_records
road_record_skip_reason
```

### 2.2 キョードー東海スクレーパー

キョードー東海は月別公演カレンダーを一次取得元とする。対象月URLは
`https://www.kyodotokai.co.jp/events/calendor/YYYYMM` で組み立てる。前月、当月、
翌月、過去月のいずれも同じ形式で直接指定できる。

カレンダーの各日から、会場フィルタ適用前の公演名、日付、詳細URLをすべて取得する。
同日複数公演や同一公演の昼夜公演は別の詳細URLとして保持し、URL単位で重複を
除外する。カレンダー下部の「今日・明日の公演」欄は取得対象を
`div.calendarbox` 内へ限定することで混入させない。

対象日と一致した候補だけ詳細ページを取得し、開催日、会場、開演時刻、公演名を
詳細ページで確定してから会場フィルタを適用する。カレンダー取得失敗、主要
セレクタ0件、または表示年月不一致の場合だけ、五十音別の
`/events/index/1/` から `/events/index/9/` をフォールバックとして巡回する。
`/events` と五十音一覧は終了済み公演が消えるため、一次取得元にはしない。

2026-08-06の比較確認では、カレンダーから2026年7月24件、8月28件、9月23件の
一意な詳細URLを取得できた。8月カレンダーには3587、3588、3589がすべて存在したが、
同日時点の五十音一覧からは終了済みのこれら3件を含む8月公演6件が消えていた。

カレンダーの正常性は `div.calendarbox table tr` の件数で判定する。HTTP 200でも
このセレクタが0件の場合は、一時的な空レスポンス、メンテナンスページ、遮断ページ
などの可能性があるため1回だけ再取得する。HTTPステータスが200以外の場合や
取得例外の場合も同様に再取得する。詳細ページは `div.detailbox` を主要セレクタ
として同じ再取得・診断規則を適用する。

再取得後も正常な一覧を確認できない場合は、次の診断情報を管理ログへ出す。

- HTTPステータス
- 最終URL
- HTMLのバイト長
- 主要セレクタと件数
- 保存HTMLと診断JSONのパス

異常時の保存先:

```text
data/debug/scrapers/kyodo_tokai/
```

HTMLとJSONは異常時だけ保存し、通常取得では保存しない。一度目が異常でも
再取得で対象構造が確認できた場合は、再試行した事実と前後のステータス、HTML長、
セレクタ件数をhealthログへ記録し、管理者向け異常通知は作らない。

当日該当公演が0件であることと、カレンダーセレクタ自体が0件であることは区別する。
カレンダーが正常に取得できていれば、対象日の公演が0件でもスクレーパー異常とは
扱わない。

公演候補はカレンダーでの発見、詳細解析、追加を段階別に記録し、除外時は日付不一致、
日付解析失敗、詳細取得失敗、公演名・会場欠落、対象外会場、URL重複のいずれかを
必ず記録する。月内の会場フィルタ適用前件数は `kyodo_calendar_candidates` に記録する。

```text
kyodo_event_found
kyodo_event_skipped_reason
kyodo_event_parsed
kyodo_event_added
kyodo_calendar_candidates
kyodo_calendar_fallback
```

`kyodo_event_added` の公演は `main.py` のイベント集合へ入り、共通の正規化、
当日抽出、重複除外を経てDiscord通知本文の生成対象となる。

### 2.3 劇団四季スクレーパー

劇団四季の対象作品・劇場ページは次のURLである。

```text
https://www.shiki.jp/stage_schedule/?aj=0&rid=0019&ggc=0977
```

対象は「オペラ座の怪人」、会場は `ＭＴＧ名古屋四季劇場` とする。作品ページの
静的HTMLでは `#targetArea` が空であり、公演カレンダーはJavaScriptが公式JSON APIを
呼び出して描画する。ブラウザ描画完了待ちは競合があるため一次取得には使用しない。

一次取得経路:

1. 作品ページの `h1.stageTitle` と `p.stageInfo strong` から作品名・名古屋会場を確認する。
2. `/api_stage_schedule/stageYmList` から公開月を取得する。
3. 各月について `/api_stage_schedule/calendar` を `target_ym=YYYYMM` 付きで取得する。
4. `results.calendar[]` の `koen_day` と `mor` / `aft` の `time` を公演枠へ変換する。
5. APIが含む前月・翌月のカレンダー余白を `koen_day` の年月で除外する。
6. 名古屋会場確認後、`source + venue + title + date + time` で重複を除外する。

APIリクエストには作品ページのRefererと `X-Requested-With: XMLHttpRequest` を付ける。
これらがない場合、一部の将来月が一時的に404となることがある。HTTP失敗は1回だけ
再試行し、再試行後も1か月でも取得できなければ全体を不確定とする。APIには
公演ごとの詳細URLはなく、作品・劇場ページと月別JSONが取得元である。このため
`shiki_detail_urls` と `shiki_detail_success` は現行構造では0となる。

昼夜公演は `mor` と `aft` を別イベントとして保持する。`daily_disp_flg=1` かつ
`daily_disp_str` に貸切表記がある場合、または時間なしの枠の `dispstr` に貸切表記が
ある場合も、貸切公演として日付とnoteを保持する。通常公演の終了時刻は従来どおり
開演から160分後とする。空席状態は `sufficient / seat / unsoldSeat / justRest /
soldOut` を `◎ / ○ / △ / ▽ / ×` へ変換する。

2026-08-08の実サイト確認では、対象ページはHTTP 200、リダイレクト0、静的HTML
23,716 bytes、旧主要セレクタ0件だった。公式APIから2026年8月～2027年3月の
将来公演220件を取得し、すべて日付解析成功、名古屋公演、会場フィルタ通過、
重複除外後220件だった。

異常判定と既存データ保護:

- 0件または1件は正常結果として確定しない。
- 前回の既存将来公演に対して50%以上減少した結果はCSVへ書かない。
- API月一覧、いずれかの月別API、作品ページ、名古屋会場確認の失敗時はCSVへ書かない。
- Health Dashboardの前回比50%以上減少判定は維持し、閾値を緩和しない。
- 異常時も既存 `csv_events/shiki.csv` をinactive化・空更新せず、そのまま保持する。

異常時は取得した作品ページHTMLと診断JSONを次へ保存する。

```text
data/debug/scrapers/shiki/
```

主な診断ログ:

```text
shiki_http_status
shiki_final_url
shiki_html_length
shiki_raw_candidates
shiki_detail_urls
shiki_detail_success
shiki_parsed_events
shiki_nagoya_events
shiki_filtered_events
shiki_skip_reason
```

### 2.4 愛知・名古屋2026大会前baseline

2026-08-10時点で公開されている愛知・名古屋2026アジア競技大会の
競技セッション日程を、後日の変更比較用原本として保存する。このbaselineは
本番イベントDBの入力ではなく、定期監視、Discord通知、自動反映も行わない。

snapshot:

```text
snapshot_date: 2026-08-10
raw_sessions: 527
competition_sessions: 503
ceremony_sessions: 2
excluded_non_event_products: 22
allowed_event_categories: 55
adopted_event_categories: 57
```

公式取得元:

- 競技マスター: `https://lp-ag.tickets-aichi-nagoya2026.org/wp-content/themes/asia/assets/js/kyougi.json`
- 会場マスター: `https://lp-ag.tickets-aichi-nagoya2026.org/wp-content/themes/asia/assets/js/venue.json`
- セッションAPI: `https://generalsale.tickets-aichi-nagoya2026.org/getFilteredProductsJSON.th`
- アジア競技大会の親カテゴリ: `eventCategoryFather=3`

`tools/event/build_aichi_nagoya_2026_baseline.py`はセッションAPIを25件ずつページングし、
`hasMoreRecords`がfalseになるまで取得する。取得中の`totalRecords`変動、空ページ、
JSON構造異常、総件数不一致、0～1件の結果、競技許可後0～1件は異常とし、
新しいrawやbaselineを書かない。

競技baselineは`kyougi.json`のURLから取れるeventCategoryを競技許可リストとする。
それに加え、開会式と閉会式は非競技カテゴリだがタクシー需要上重要なため、
baselineと採用会場候補の正式対象とする。`event_type`は競技を`competition`、
開会式を`opening_ceremony`、閉会式を`closing_ceremony`とする。1日券、応援プラス、
プレミアムプラス、ホスピタリティラウンジなど、競技・開会式・閉会式そのものではない
商品はbaselineから除外するが、rawレスポンスからは削除しない。

保存先:

```text
data/aichi_nagoya_2026/raw/kyougi.json
data/aichi_nagoya_2026/raw/venue.json
data/aichi_nagoya_2026/raw/sessions_20260810.json
data/aichi_nagoya_2026/baseline/baseline_sessions_20260810.csv
data/aichi_nagoya_2026/baseline/venue_selection_master_20260810.csv
data/aichi_nagoya_2026/baseline/venue_candidates_20260810.csv
```

Google Sheetsの`アジア大会_大会前マスター`は、`baseline_sessions_20260810.csv`の
505件を全列保持するimmutableな原本タブである。競技503件と開会式・閉会式各1件を
保存し、採用会場による244件への絞り込みは行わない。将来の日程変更比較はこのタブを
基準とし、実運用用の`アジア大会`タブを更新しても大会前の状態を消さない。

`tools/event/sync_aichi_nagoya_2026_pre_event_master.py`は既存のGoogle Sheets認証、タブ作成、
CSV読込、タブ読戻しの共通処理を使う。空タブだけに初回書込みを行い、同一snapshotと
全セルが一致する再実行は`unchanged`とする。同一snapshotで差異がある場合、ヘッダーが
異なる場合、別snapshotがすでに存在する場合は、clear、上書き、追記をせず505件の原本を保護する。

`sessions_20260810.json`は`retrieved_at`、`source_url`、リクエスト条件、`total_records`と、
各ページの公式JSONレスポンス全体を`pages`に無加工で保持する。生データの
フィールドは削除しない。

baseline CSVの保持項目:

```text
snapshot_date, event_type, idProduct, idPerformance, eventCategory, sessionCode, idVenue,
date, time, end_time, venue, event_name, event_category_name, session_name,
session_info, availability_status, selling_status, is_sellable, source
```

日付、開始、終了時刻は`dhStart` / `dhEnd`を正式ソースとし、`idMonth`などは
主日時判定に使わない。将来は`idPerformance`、`idProduct`、`sessionCode`を安定キー候補とし、
UNCHANGED / TIME_CHANGED / VENUE_CHANGED / INFO_CHANGED / ADDED / REMOVED /
CANCELLEDなどの差分判定を検討するが、現時点では未実装である。

会場はAPIの`idVenue`と`nmVenue`を保持し、Unicode NFKC、括弧、空白のみを
安全に正規化して`venue.json`と突合する。同一と断定できない表記は推測せず
`unresolved`とする。Google Sheetsの`https://docs.google.com/spreadsheets/d/12MNpRn0Krk3WVRFoj37bST2fXBGnomeQ-DQ4N9VA-7c`
にある`アジア大会_会場候補`の◎・○26会場を2026-08-10時点の採用会場マスターとし、
完全一致または上記正規化で一致した242セッションだけを`venue_candidates_20260810.csv`へ出力する。
選定マスターの表記がAPI会場と一致しない場合は自動採用しない。

同じsnapshot_dateのファイルが同一内容なら更新せず、内容が異なる場合は
`--force`がない限り上書きを拒否する。販売サイトのQueue-it、Bot対策、reCAPTCHA、
Cookie / Sessionチェックを回避する実装は行わない。通常取得できない場合は
取得不能とし、既存baselineを保護する。

回帰テストは競技許可判定、非競技除外、同日複数セッション、`dhStart` /
`dhEnd`変換、会場正規化突合、採用会場限定、欠損日時の中断、同日不正上書き防止、
0件時非更新を対象とする。

### 2.5 愛知・名古屋2026営業用データ

アジア大会データは次の3層に分ける。

1. Google Sheetsの`アジア大会_大会前マスター`: 2026-08-10時点の505件を保持するimmutable原本
2. `アジア大会_会場候補`: 名古屋市内・近郊を営業対象として採用する会場とDB表示名のマスター
3. `アジア大会`: 採用会場に該当する244件を営業判断向けに整形した7列の実運用タブ

`tools/event/build_aichi_nagoya_2026_operational.py`は、immutable原本
`baseline_sessions_20260810.csv`と`venue_candidates_20260810.csv`を読み、
次へ出力する。

```text
data/aichi_nagoya_2026/operational/asia_games_operational_20260810.csv
```

営業用CSVと`アジア大会`タブの列は次の順序に固定する。

```text
date,time,end_time,venue,event_name,session_info,availability_status
```

営業用の`venue`は、会場候補マスター由来の`db_display_name`を使用する。コード内へ
別の会場名マッピングを重複定義しない。`db_display_name`がない候補は推測せず異常終了し、
営業用CSVやSheetsを空更新しない。`event_name`は競技ではbaseline値を使用し、式典だけ
`開会式` / `閉会式`へ簡潔化する。`session_info`は長文を切り捨てず、
`availability_status`は販売状態のAPI原文を変換せず保持する。

行は`date`、`time`、`venue`の昇順とする。同日・同時刻の複数セッションは
別行として保持する。開会式と閉会式は必ず営業対象に含める。2026-08-10 snapshotでは
競技242件、開会式1件、閉会式1件の計244件で、会場表示名未解決は0件である。

生成時はbaselineのSHA-256を処理前後で比較し、営業用加工が原本を変更していないことを
確認する。baseline、会場候補、抽出結果の0件、必須列不足、候補IDの原本不在、
会場表示名未解決では出力・Sheets更新を行わない。

`tools/event/sync_aichi_nagoya_2026_operational.py`は既存Google Sheets共通認証・読戻し処理を
利用する。`アジア大会`タブに異なるデータ行や未知のヘッダーがある場合は自動置換しない。
正常なCSVを先に書き込んでから旧列・余剰行だけを限定クリアし、同期失敗時もローカルCSVと
`アジア大会_大会前マスター`を変更しない。Sheets表示はヘッダー固定、フィルター、
`session_info`折り返しとし、7列だけを表示する。

主な確認ログ:

```text
asia_operational_source_records
asia_operational_candidate_records
asia_operational_output_records
asia_operational_competition_records
asia_operational_opening_records
asia_operational_closing_records
asia_operational_venue_unresolved
asia_operational_sheet_sync_status
```

### 2.6 愛知・名古屋2026イベントBOT

大会固有のBOT処理は`tools/event/aichi_nagoya_2026_bot.py`へ集約する。通常の`main.py`は
大会機能が有効な場合に専用の日次送信関数を呼ぶだけとし、他イベントの旧9列ローダー、
本文生成、Discord通知には大会用の列変換やチケット表示を混在させない。

大会機能は環境設定`ENABLE_AICHI_NAGOYA_2026`で一括制御し、既定値はtrueとする。
falseの場合は次をすべて停止する。

- 7列`アジア大会`Sheetおよびfallback CSVの読込
- 既存`ajipara.csv`とGoogle Sheets`アジパラ`の読込
- 大会専用のチケット日本語表示、プレーンテキスト通知、長文表示制御
- 開会式強制テスト経路

営業用入力スキーマ:

```text
date,time,end_time,venue,event_name,session_info,availability_status
```

BOTはGoogle Sheets`アジア大会`を一次入力とし、取得・7列検証に失敗した場合だけ
`data/aichi_nagoya_2026/operational/asia_games_operational_20260810.csv`へfallbackする。
大会前マスターと会場候補タブは読込・更新しない。旧9列の`csv_events/asia.csv`をSheetへ
自動同期する処理と、営業用全日程を日次で削除するcleanup処理は通常BOTから外す。

2026-09-03以降、一次取得URLは`gviz/tq?tqx=out:csv&sheet=アジア大会`を使用せず、
対象タブの固定gidを指定した次のCSV export URLを使用する。

```text
https://docs.google.com/spreadsheets/d/12MNpRn0Krk3WVRFoj37bST2fXBGnomeQ-DQ4N9VA-7c/export?format=csv&gid=272979110
```

同日時点でgviz方式はGoogle側のCSVが列方向に崩れ、固定7列ヘッダー検証に失敗したためである。
取得方式変更後も、列順を含む完全一致の7列schema検証、未知列・0件の異常扱い、取得失敗・
schema不一致時の営業用CSV fallbackを維持する。この変更は`アジア大会`営業用タブの一次取得
だけに限定し、通常イベント、道路情報、他のGoogle Sheets取得URL・処理には適用しない。

2026-08-10の営業用244件に存在する`availability_status`は次の3種類である。

```text
BUY: 104
LIMITED: 64
SOLD_OUT: 76
```

CSVとSheetでは原値を保持し、表示層だけで次のように日本語化する。

- `BUY` → `販売中`
- `LIMITED` → `残席わずか`
- `SOLD_OUT` → `予定枚数終了`

`availability_status`はイベント採否に使わず、`SOLD_OUT`も通知対象に残す。未知値も
通知を落とさず原値を`🎟️ チケット：<原値>`として表示し、
`asia_ticket_status_unknown`を記録する。`session_info`の原データは変更せず、Discord表示時
だけ1イベント700文字を上限に省略記号付きで安全に短縮する。日次件数が多い場合は、
Discordのcontent上限内でイベント単位に複数のプレーンテキスト投稿へ分割する。

大会通知はEmbedを使用せず、Webhook payloadの`content`へプレーンテキストとして設定する。
見出し、日付、件数、イベントの順に空行を入れ、日付は`09月03日（木）`、件数は
`🏟️ 本日 N件`形式とし、各イベントを`────────────`で区切る。チケット状況を
表示する大会通知には、開会式・閉会式を含め、最終メッセージ末尾へ必ず次を付ける。

```text
チケット状況は公式チケット状況です。販路によって異なる場合があります😇
```

通常イベント通知には付けない。

開会式強制テスト:

```bash
# 送信なしpreview
.venv/bin/python tools/event/test_asia_opening_discord.py

# WEBHOOK_ASIAへ開会式1件だけ送信
.venv/bin/python tools/event/test_asia_opening_discord.py --send
```

テストはローカル営業用CSVから2026-09-19の`開会式`を厳密に1件だけ選び、
`🧪【テスト投稿】`付きプレーンテキストを生成する。0件・2件以上・開会式以外なら送信しない。
本番日付、CSV、Sheets、通常イベントの重複抑制stateは変更しない。送信時はWebhookへ
`wait=true`を付け、Discordが返した投稿済みcontentが送信内容と一致し、末尾に上記文言が
あることを`asia_event_content_verified=true`で確認する。

主なBOTログ:

```text
asia_event_records
asia_event_schema
asia_ticket_status_counts
asia_ticket_status_unknown
asia_event_opening_found
asia_event_opening_notification_target
asia_event_test_mode
asia_event_test_records
asia_event_content_verified
asia_event_discord_status
```

大会終了後の撤去手順:

1. 実行環境で`ENABLE_AICHI_NAGOYA_2026=false`にする。
2. BOTをdry-runし、アジア大会・アジパラのSheet/CSV読込、特殊表示、footer、テスト投稿が出ないことを確認する。
3. 必要なら`WEBHOOK_ASIA`、大会専用起動手順・監視設定を無効化する。
4. 歴史データとしてbaseline、営業用CSV、テスト、Sheets 3タブを保持または別途アーカイブする。
5. 完全削除する場合だけ、`tools/event/aichi_nagoya_2026_*.py`、本専用BOTモジュール、
   `config.py`のフラグ、`main.py`の専用呼出し、Google Sheetsの大会専用タブを対象として確認後に削除する。

通常運用からの撤去は手順1だけで成立し、通常イベントBOTの取得・通知は継続する。

### 2.7 愛知・名古屋2026公式Results API

`tools/event/aichi_nagoya_2026_results.py`は、大会公式Results APIから日程を取得し、
API固有の圧縮レスポンスを展開して、競技別dailyを後続処理用の辞書へ正規化する。
現時点では取得・展開・正規化だけを行い、Google Sheets、営業用CSV、既存7列スキーマ、
Discord通知へは書込み・自動反映しない。

取得エンドポイント:

```text
https://back.results.asiangames2026.org/s/AG2026/ja/ALL/schedule/matrix
https://back.results.asiangames2026.org/s/AG2026/ja/ALL/schedule/day/YYYY-MM-DD
https://back.results.asiangames2026.org/s/AG2026/ja/{Disc}/schedule/daily/YYYY-MM-DD
```

既定言語は`ja`とする。比較・診断時だけ各公開取得関数の`language="en"`またはCLIの
`--language en`で英語版を明示選択できる。2026-09-16の同一`ResCode`比較では、BKBは
`DiscDesc`、`VenueDesc`、`EventDesc`、`PhaseDesc`、`UnitDesc`、Home/Awayの`Name`が
日本語になった。VVOも説明系5項目は日本語になった一方、Home/Awayの`Name`は英語のままで、
一部`UnitDesc`には`プ?ル`という公式データ上の欠損があった。このため競技名、会場名、
event、phase、sessionは`ja`レスポンスの公式値を優先し、自前の英語から日本語への変換は
行わない。

リクエストヘッダーは次の最小構成に固定する。ETag由来の`If-None-Match`やブラウザ固有の
`sec-*`ヘッダーは付けない。

```text
Accept: application/json, text/plain, */*
Origin: https://results.asiangames2026.org
Referer: https://results.asiangames2026.org/
User-Agent: Mozilla/5.0
```

レスポンス本文は通常のJSONではない。HTTP本文をUTF-8文字列として復号し、その文字列を
Latin-1 bytesへ戻した後、`zlib.decompress`で展開し、展開結果をUTF-8 JSONとして読む。
文字コード、zlib、JSONのいずれかが不正な場合は空データとして扱わず
`ResultsPayloadError`とする。

公開関数の役割:

- `fetch_schedule_matrix()`: 全競技の開催日matrixを取得・展開する。
- `fetch_day_schedule(date)`: 指定日の全競技概要を取得・展開する。
- `extract_discipline_codes(payload)`: 日別概要内の`Disc`を出現順・重複なしで抽出する。
- `fetch_discipline_daily(Disc, date)`: 競技別dailyの展開済み公式JSONを無加工で返す。
- `fetch_normalized_discipline_daily(Disc, date)`: 競技別dailyを取得・展開・正規化する。

正規化データは取得言語、公式の識別子、競技名、`DateTimeRaw`、日付、時刻、status、会場、
event、phase、round、sessionを保持する。`isH2H=true`では`Home.Name/Org`と
`Away.Name/Org`を`competitors.home/away`へ構造化し、`matchup`も生成する。団体競技の
対戦国・地域名は`Org`の3文字コードを正として大会呼称の日本語表示名に正規化する。
`JPN`は必ず`日本`、`HKG`は`ホンコン・チャイナ`とする。既知コードではAPIの`Name`は
診断用の原値として保持し、未知コードだけ`Name`へfallbackして勝手に翻訳しない。
個人競技の選手名は`Org`へ置換せずAPIの`Name`をそのまま使う。`isH2H=false`では対戦者を
生成せず、`PhaseDesc` / `PhaseDescA`と`UnitDesc` / `UnitDescA`をround・session情報として
保持する。

コマンドライン確認:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_results.py matrix
.venv/bin/python tools/event/aichi_nagoya_2026_results.py day 2026-09-16
.venv/bin/python tools/event/aichi_nagoya_2026_results.py daily BKB 2026-09-16
.venv/bin/python tools/event/aichi_nagoya_2026_results.py daily BKB 2026-09-16 --raw
.venv/bin/python tools/event/aichi_nagoya_2026_results.py daily BKB 2026-09-16 --language en
```

### 2.8 公式Resultsと営業用Sheetのdry-run照合

`tools/event/aichi_nagoya_2026_results_dry_run.py`は、公式Resultsの日別正規化データと
Google Sheetsの`アジア大会`タブを読み取り専用で照合する。Google Sheets更新、営業用CSV更新、
Discord通知は行わず、既存の`session_info`と`availability_status`も変更しない。

Sheet読込は既存タブの固定gidを使うHTTP GETに限定し、`range=A:G`を明示する。読込対象と
列順は次の7列だけで、ヘッダー不一致または0件は異常終了する。

```text
date,time,end_time,venue,event_name,session_info,availability_status
```

外部通信はGoogle Sheets GET、Results日別overview GET、競技別daily GETのすべてで
接続timeout 5秒、読取timeout 15秒、1リクエストのhard wall-clock timeout 20秒を設定する。
さらにdry-run全体を既定90秒で中断し、競技別dailyの逐次取得が累積して無制限に待つことを
禁止する。全体上限は`--overall-timeout`で短縮できる。

進捗は標準エラーへ即時flushし、Sheet、overview、各dailyの開始・完了・失敗、競技コード、
`index=N/total`、timeout値、経過秒、取得件数を出す。JSONまたはtextの照合結果は標準出力へ
分離するため、停止時は最後の`external_http_start`または`results_daily_start`から待機先を
特定できる。timeout時は部分照合結果を出さず終了コード1とする。

処理の流れ:

1. 指定日の`ALL/schedule/day`から競技コードを抽出する。
2. 各競技の`schedule/daily`を取得し、対戦者を含む正規化データを作る。
3. Sheetの指定日行ごとに`date`、`time`、会場alias、競技aliasの順で完全一致照合する。
4. 完全一致が1件なら`MATCH`、2件以上なら`AMBIGUOUS`、0件なら`NOT_FOUND`とする。

会場aliasは表記揺れを明示的な同値グループとして定義する。未知の会場名はNFKC、空白、
括弧、区切り記号を正規化した完全一致だけを許可し、部分一致や類似度による推測は行わない。
`名古屋市総合体育館［レインボーホール］`と`NGKホール`、
`名古屋市総合体育館［レインボープール］`と`NGKアリーナ`は別々のaliasグループとする。
競技もResultsの競技コードまたは明示的な日英aliasで照合し、たとえばバスケットボールと
3x3バスケットボールを混同しない。

dry-run出力はSheet側の日時・会場・競技、Results側の日時・会場・競技・phase・round・session、
H2Hの対戦名、候補`session_info`、照合理由、候補数を含む。完全一致が複数ある場合は候補を
すべて表示し、1件へ自動確定しない。公式dailyが競技単位で空の場合も部分結果を
`NOT_FOUND`として確定せず異常終了する。`NOT_FOUND`では、残り3キーが一致するResultsを
`Nearby Results (not selected)`として診断表示できるが、候補数には含めず自動確定もしない。

候補`session_info`は表示だけに使用する。`PhaseDesc`の公式日本語値を元に表示用の空白・
区切りを整え、H2Hは`男子準々決勝｜ヨルダン vs 大韓民国`、
`男子グループA｜タイ vs キルギス`、`女子予選プールA｜日本 vs ネパール`のように生成する。
非H2Hは公式`PhaseDesc`を優先する。`PhaseDesc`が正常で`UnitDesc`に`?`がある場合は
`PhaseDesc`を採用する。いずれもSheetへは書き込まない。

実行例:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_results_dry_run.py 2026-09-16
.venv/bin/python tools/event/aichi_nagoya_2026_results_dry_run.py 2026-09-16 --format json
.venv/bin/python tools/event/aichi_nagoya_2026_results_dry_run.py 2026-09-16 --overall-timeout 60
```

### 2.9 公式Resultsとの全期間日程監査

`tools/event/aichi_nagoya_2026_results_audit.py`は、`アジア大会`タブの固定7列`A:G`を
全行読み取り、`ja/ALL/schedule/matrix`にある全公式日付について、Sheetに存在する競技だけの
日別overviewと競技別dailyを取得して監査する。公式競技コードはmatrixの値に合わせ、
クリケット`CKT`、7人制ラグビー`RU7`、セパタクロー`SPK`、ソフトテニス`TST`を使用する。

分類は次の優先順とする。

1. date/time/venue alias/sportが1件一致: `EXACT_MATCH`
2. 同じ完全キーが複数: `MULTIPLE_CANDIDATES`
3. date/venue alias/sport一致、time不一致: `TIME_MISMATCH`
4. date/time/sport一致、venue alias不一致: `VENUE_MISMATCH`
5. time/venue alias/sportが別日で一致: `DATE_MISMATCH`
6. 上記に該当しない: `RESULTS_NOT_FOUND`

`TIME_MISMATCH`は同日・同会場・同競技のResultsを全件表示する。
`VENUE_MISMATCH`は同日・同時刻・同競技の候補を全件表示し、公式`VenueDesc`が空の場合は
Sheet会場を検証不能であることを理由へ明記する。`DATE_MISMATCH`は日付差が最小の候補だけを
表示する。`RESULTS_NOT_FOUND`でも同競技が存在する場合は、会場alias一致、日付差、時刻差で
並べた上位5件を診断表示する。いずれの候補も`auto_selected=false`であり、自動修正や
`session_info`生成結果の書込みには使用しない。

Sheet、matrix、overview、dailyには既存の接続5秒・読取15秒・1通信20秒hard timeoutを適用し、
監査全体にも既定90秒のwall-clock timeoutを適用する。進捗ログには全25日の日付index、
各dailyのrequest index、競技コード、件数、経過時間、失敗中のstageを出す。取得途中で
dailyが空または対象日レコードが0件になった場合は、部分監査結果を出さず異常終了する。

実行例:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_results_audit.py
.venv/bin/python tools/event/aichi_nagoya_2026_results_audit.py --format json
.venv/bin/python tools/event/aichi_nagoya_2026_results_audit.py --format markdown
.venv/bin/python tools/event/aichi_nagoya_2026_results_audit.py --overall-timeout 90
```

### 2.10 公式チケット販売状況のdry-run監査

`tools/event/aichi_nagoya_2026_ticket_status_audit.py`は、2026-08-10 baseline作成で使用した
`getFilteredProductsJSON.th`のページング取得関数を再利用し、現在の公式
`availabilityStatus`と`アジア大会`タブの`availability_status`を読み取り専用で比較する。
新規のHTMLスクレーパーは持たず、Queue-it、reCAPTCHA、Bot対策、Cookie/Session制限の
回避は行わない。通常のJSON取得が失敗した場合、ページ数・`totalRecords`・取得件数が
不整合の場合、または取得結果が空の場合は部分結果を出さず異常終了する。

Sheetは固定7列`A:G`だけをGETし、`【発火テスト】`行を営業用監査から除外する。各営業用行を
immutableな`venue_candidates_20260810.csv`へ次の順で照合する。

1. `availability_status`以外の6列完全一致
2. `session_info`を除くdate/time/end_time/venue/event_name一致
3. date/time/venue/event_name一致
4. date/venue/event_name一致

各段階で1件に絞れた場合だけbaselineの`idPerformance / idProduct / sessionCode`を採用する。
複数残る場合は`MULTIPLE_CANDIDATES`とし、時刻の近さなどで自動選択しない。現在の公式商品も
3つの安定IDが完全一致する場合だけ対応セッションとする。

分類:

- `UNCHANGED`: 安定IDが一意に一致し、Sheetと公式の販売状態が同じ
- `STATUS_CHANGED`: 安定IDが一意に一致し、販売状態が異なる
- `MULTIPLE_CANDIDATES`: baselineまたは現在公式側で複数候補が残る
- `NOT_FOUND`: baseline対応、現在の安定ID、または既知の公式販売状態を安全に得られない

公式販売状態として自動比較する値は`BUY / LIMITED / SOLD_OUT`だけとし、未知値は変更扱いに
せず`NOT_FOUND`で保護する。Markdown/CSV/任意JSONはローカル診断成果物であり、Google Sheet、
`session_info`、`availability_status`、その他6列、列順、BOT状態を書き換える経路はない。
集計では安定ID一致行の公式内訳とは別に、`NOT_FOUND / MULTIPLE_CANDIDATES`のSheet値を保持した
保護後の実効内訳も表示する。

公式チケット各ページには既定15秒の明示timeout、Sheetには2.8と同じtimeoutを適用し、監査全体を
既定120秒のhard timeoutで囲む。進捗ログにはSheet取得、baseline読込、公式ページ番号、累積件数、
総件数、完了分類件数、失敗stageを出す。

実行例:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_ticket_status_audit.py \
  --markdown-output logs/aichi_nagoya_2026_ticket_status_audit.md \
  --csv-output logs/aichi_nagoya_2026_ticket_status_audit.csv \
  --json-output logs/aichi_nagoya_2026_ticket_status_audit.json \
  --overall-timeout 120 --request-timeout 15
```

### 2.11 availability_status更新可否の突合dry-run

`tools/event/aichi_nagoya_2026_availability_update_audit.py`は、2.10の販売状況監査JSON、
2.9のResults全期間監査JSON、内容監査の行別分類を突合する。入力成果物だけを読み、
Google Sheetsおよび外部APIへの接続経路や書込み経路を持たない。対象は
`STATUS_CHANGED`と保護対象のTicket `NOT_FOUND / MULTIPLE_CANDIDATES`で、`UNCHANGED`は
更新対象外として件数だけ記録する。

`STATUS_CHANGED`は、2026-08-10 baselineと現在の公式チケット商品の
date/time/venue/event_nameが一致し、次のいずれかを満たす場合だけ`SAFE_TO_UPDATE`とする。

- Resultsが`EXACT_MATCH`で、内容監査が`CONTENT_MATCH`または`AGGREGATED_OK`
- 開会式・閉会式であり、Resultsに存在しない一方、チケットの3安定IDが一意で商品コアが不変

競技行の内容監査は許可状態を列挙するfail-closed方式とする。Resultsが`EXACT_MATCH`でも、
`CONTENT_OUTDATED`は`HOLD_CONTENT_OUTDATED`、`INSUFFICIENT_SHEET_INFO / NEEDS_REVIEW`または
未知の内容分類は`NEEDS_REVIEW`として旧値を保持する。開会式・閉会式は内容監査の対象外であり、
上記の明示的なResults対象外例外を維持する。

Resultsの`TIME_MISMATCH / VENUE_MISMATCH / DATE_MISMATCH / RESULTS_NOT_FOUND`は
`HOLD_RESULTS_MISMATCH`、ResultsまたはTicketの`MULTIPLE_CANDIDATES`は`NEEDS_REVIEW`とし、
候補を自動選択しない。Ticket `NOT_FOUND`は`HOLD_TICKET_NOT_FOUND`として旧Sheet値を保持する。
販売状態は短時間にも変化し得るため、実書込みを将来実装する場合も、dry-run成果物の値を
そのまま使用せず、直前に同じ公式取得・安定ID・商品コア・Results条件を再検証する。

出力はMarkdown/CSV/JSONとし、`SAFE_TO_UPDATE`の対象行、旧値・新値、Ticket根拠、Results状態、
6種類の状態遷移、保留理由、実書込み時の変更セル数を含む。現段階では
`availability_status`を含む固定7列、列順、`session_info`、BOT状態を一切変更しない。

実行例:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_availability_update_audit.py \
  --ticket-audit logs/aichi_nagoya_2026_ticket_status_audit.json \
  --results-audit logs/aichi_nagoya_2026_results_audit.json \
  --content-audit logs/aichi_nagoya_2026_content_audit.md \
  --markdown-output logs/aichi_nagoya_2026_availability_update_audit.md \
  --csv-output logs/aichi_nagoya_2026_availability_update_audit.csv \
  --json-output logs/aichi_nagoya_2026_availability_update_audit.json
```

### 2.12 availability_statusの限定セル更新

`tools/event/aichi_nagoya_2026_availability_updater.py`は、固定された更新候補一覧を入力にせず、
起動のたびに次の順で更新予定セルを作り直す。

1. 2.4と同じ公式Ticket JSON APIを全ページ再取得する。
2. `アジア大会`の固定7列`A:G`を再取得する。
3. Results `/ja/`のmatrix、全日overview、対象競技dailyを再取得して全期間監査を作り直す。
4. Ticket安定ID、現在の商品date/time/venue/event_name、Results監査、内容監査を2.11の条件で再評価する。
5. その時点の`SAFE_TO_UPDATE`のうち、Sheetと公式値が異なる`availability_status`セルだけを計画する。

引数なしと`--dry-run`は同じread-onlyモードであり、Google Sheets認証サービスを生成せず、
書込みAPIを呼ばない。`--apply`が明示された場合だけ、認証付きGoogle Sheets APIを準備する。
`--dry-run`と`--apply`は同時指定できない。Ticket、Sheet、Resultsのいずれかが取得不能、空、
不完全、timeoutになった場合は更新計画を確定せず、Sheet値を保持する。Queue-it、reCAPTCHA、
Bot対策、Cookie/Session制限の回避は行わない。

内容監査は人手確認済みMarkdownの行別分類を使用するが、対応するResults監査snapshotと
現在Sheetの`availability_status`以外の6列を全行・同じ順序で比較する。1セルでも異なる場合は、
古い内容分類を行番号へ適用せず実行全体を中断する。発火テストはTicket監査と同様に除外する。

検証済みのsession_info F列更新後は、`--accepted-session-info-apply-report`に完全成功した
session_info updaterのapply JSONを明示できる。共通の証跡検証関数で`mode=apply`、
`sheet_write=true`、F列・session_info対象、`applied=planned`、`not_applied=unexpected=0`、
物理行番号・Fセル・date/time/venue/event_name・旧F値の一致を確認し、その成果物に記録された
F変更だけを内容監査参照へインメモリでrebaseする。その後、従来の6列identity比較を全行に
実施する。証跡不正、部分適用、重複行、旧値・identity不一致はfail-closedで中断し、
内容監査・Results snapshotファイル自体は変更しない。dry-runは引き続きwrite serviceを
生成せず、availability updaterの書込み対象はG列だけである。

`--apply`では計画生成後、書込み直前に次を行う。

- spreadsheet IDとタブ名`アジア大会`をmetadataで確定する。
- 対象範囲`A1:G<最終行>`を認証付きで再読込し、計画時の7列全セルと完全一致することを確認する。
- G列のdata validationを読取り、`ONE_OF_LIST`の場合は新値が許可値に含まれることを確認する。
- `spreadsheets.values.batchUpdate`の離散した`G<行番号>`だけを、`RAW`で単一batch更新する。
- 直後に同じ`A:G`を再読込し、他6列、行数、非対象Gセルが不変で、対象Gセルだけが新値になったことを確認する。

Sheet全体更新、A:F更新、行・列の追加、削除、並び替え、列順変更、`session_info`更新、BOT state更新、
曖昧候補の選択を行うコード経路は持たない。Ticket `NOT_FOUND`、Ticket/Results
`MULTIPLE_CANDIDATES`、Results mismatch、内容監査が`CONTENT_MATCH / AGGREGATED_OK`以外の競技行は
旧値を保持する。開会式・閉会式の明示的なResults対象外例外だけは2.11の条件を適用する。

進捗はstderrと`<output-prefix>.progress.log`の両方へ即時出力する。Ticket各HTTP、Sheet取得、
Results各HTTP、Google API metadata/read/writeのstageとtimeoutを記録する。batch更新の応答が失敗・
timeoutの場合もA:Gを再読込し、`applied / not_applied / unexpected`件数を可能な限り記録する。
各外部通信には既存の明示timeoutを使い、処理全体は既定240秒のhard timeoutで中断する。

dry-run例:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_availability_updater.py --dry-run \
  --content-audit logs/aichi_nagoya_2026_content_audit_2026-09-15.md \
  --content-reference-results logs/aichi_nagoya_2026_results_audit_2026-09-15.json \
  --output-prefix logs/aichi_nagoya_2026_availability_update_plan_2026-09-15
```

`--apply`は人間が直前のdry-run Markdown/CSV/JSONにある更新予定セルを確認した後だけ明示する。
applyでもTicket、Sheet、Resultsの再取得と安全性再評価を省略しない。

### 2.13 session_infoの公式Results補完read-only監査

`tools/event/aichi_nagoya_2026_session_info_audit.py`は、`アジア大会`の固定7列`A:G`と
Results `/ja/`をread-onlyで再取得し、2.7〜2.9の正規化、Orgコード日本語名、会場alias、
競技alias、全期間監査を再利用して`session_info`候補を分類する。Google Sheets認証サービス、
書込みAPI、BOT state、営業用CSVを変更する経路は持たない。

date/time/venue/sportが一意に`EXACT_MATCH`し、Results候補が1件、内容監査が
`CONTENT_MATCH / AGGREGATED_OK`、候補文字列と`ResCode`が非空の場合だけ候補を自動更新可能とする。
チーム競技はOrgコード由来の両対戦国がそろう場合だけ`ラウンド｜国 vs 国`を生成する。
個人競技は`isH2H`でも選手名・matchupを使わず、公式`PhaseDesc`優先のラウンド・セッション名だけを
候補とする。現在値と候補がNFKC、空白、表示用括弧・区切りの差だけなら`UNCHANGED`、異なる場合は
`SAFE_TO_UPDATE`とするが、本監査ではいずれもSheetへ書き込まない。

分類:

- `SAFE_TO_UPDATE`
- `UNCHANGED`
- `HOLD_TIME_MISMATCH`
- `HOLD_DATE_MISMATCH`
- `HOLD_VENUE_MISMATCH`
- `HOLD_MULTIPLE_CANDIDATES`
- `HOLD_RESULTS_NOT_FOUND`
- `HOLD_CONTENT_OUTDATED`
- `NEEDS_REVIEW`

同一完全キーにResultsが複数ある場合は`HOLD_MULTIPLE_CANDIDATES`かつ
`aggregation_state=MULTIPLE_RESULTS_NOT_COMBINED`とし、1試合を選ばず、初回監査では複数候補を
自動結合しない。開会式、閉会式、発火テストはResults対象外として候補を生成しない。
内容監査が`CONTENT_OUTDATED`なら候補を診断用に保持して`HOLD_CONTENT_OUTDATED`、
`INSUFFICIENT_SHEET_INFO / NEEDS_REVIEW`や未知分類は`NEEDS_REVIEW`とする。

Markdown / CSV / JSONには物理Sheet行番号、date/time/venue/event_name、現在値、候補値、
Results `ResCode`、Results・内容・集約状態、判定理由を保存する。集計には全分類、日本戦、
準々決勝、準決勝、3位決定戦、決勝の一意候補数を含む。内容監査の行番号を安全に再利用するため、
対応するResults監査snapshotと現在Sheetの`availability_status`以外の6列が全245行一致することを
取得前に検証する。内容監査Markdownの索引はヘッダーを除くデータ行番号として読み、成果物では
ヘッダーを含む物理Sheet行番号へ1を加えて表示する。

実行例:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_session_info_audit.py \
  --content-audit logs/aichi_nagoya_2026_content_audit_2026-09-15.md \
  --content-reference-results logs/aichi_nagoya_2026_results_audit_2026-09-15.json \
  --output-prefix logs/aichi_nagoya_2026_session_info_audit_2026-09-16 \
  --overall-timeout 240
```

### 2.14 session_info候補の表示品質read-onlyレビュー

`tools/event/aichi_nagoya_2026_session_info_display_review.py`は、2.13のJSONにある
`SAFE_TO_UPDATE`だけを対象に、Sheet・Resultsへの再接続や書込みを行わず表示品質を検査する。
各行を`DISPLAY_OK / DISPLAY_NEEDS_FIX / NEEDS_REVIEW`へ分類し、物理Sheet行、日時、会場、競技、
現在値、元候補、推奨候補、ResCode、日本戦、重要ラウンド、理由をMarkdown / CSV / JSONへ保存する。

検査対象は男女ラベルやPhase/Unitの重複、`? / �`等の欠損、`vs`以外の連続英字、区切り数、
国名表示、個人競技への選手名混入である。チーム候補は2.13でOrgコードを正としたもの、個人候補は
対戦者名を含まないものだけを前提とする。一般化できる表示修正はレビュー成果物の推奨値として
示し、この段階では2.13の生成器やGoogle Sheetへ反映しない。

表示品質レビューで確認した一般化ルールはsession_info生成器へ適用する。NFKCと空白除去後、
`予選ラウンド`と`グループ / プール`の間にあるハイフン類、長音、区切り点、または区切りなしを
吸収し、`予選グループ / 予選プール`へ簡潔化する。特定行番号、競技、ResCode、過去の57件の
固定リストには依存しない。準々決勝、準決勝、3位決定戦、決勝、順位決定戦、メダル関連など
対象外のラウンド名、Orgコード由来の国名、Home/Away、個人競技の選手名除外仕様は変更しない。

実行例:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_session_info_display_review.py \
  --session-audit logs/aichi_nagoya_2026_session_info_audit_2026-09-16.json \
  --output-prefix logs/aichi_nagoya_2026_session_info_display_review_2026-09-16
```

### 2.15 session_infoの限定セル更新

`tools/event/aichi_nagoya_2026_session_info_updater.py`は、固定候補を使用せず、起動ごとに
`アジア大会`の固定7列`A:G`と公式Results `/ja/`を再取得し、2.13の監査と2.14の表示品質判定を
作り直す。`SAFE_TO_UPDATE`かつ`DISPLAY_OK`で、候補が非空、欠損・文字化け記号を含まず、現在値と
異なり、かつ既存の有用な情報を失わない行だけをF列`session_info`の更新予定セルとする。
既存値に2件以上の試合数、男女両区分、複数の独立したラウンド・セッション、メダル情報があり、
単一Results候補でそれらを保持できない場合は`HOLD_AGGREGATED_SESSION_INFO`とする。区切りを含むが
複数内容か安全に判定できない場合は`NEEDS_REVIEW`へ倒す。単一ラウンドから同じラウンドの対戦カードを
加える詳細化は更新可能とし、単なる中黒等の表記区切りだけで集約扱いしない。

それ以外のResults不一致、複数候補、
内容不整合、表示修正必要、未知分類、開会式、閉会式、発火テストはfail-closedで保持する。

引数なしと`--dry-run`は完全なread-onlyで、認証付きGoogle Sheetsサービス、metadata、prewrite、
batchUpdate、postwriteのいずれも生成・実行しない。`--apply`が明示された場合だけ、2.12で使用する
共通の単一列更新処理へF列と`new_session_info`を指定する。

applyでは書込み直前に`A:G`を再取得して計画時snapshotとの完全一致を要求し、離散したFセルだけを
単一batchで更新する。書込み後に`A:G`を再取得し、A:E、G、非対象F、行数、行順、7列schemaが
不変で、対象Fだけが計画値になったことを検証する。`planned / applied / not_applied / unexpected`を
記録し、部分失敗を含め`unexpected != 0`または完全適用でない場合は成功扱いにしない。

apply直後のread-only再監査では、`applied=planned`、`not_applied=0`、`unexpected=0`を満たす
完全成功済みapply JSONを`--accepted-apply-report`で指定できる。この場合だけ、その成果物に記録された
旧F値から新F値への変更を内容監査参照へインメモリで反映する。日時・会場・競技・旧F値のいずれかが
参照と異なる場合、部分適用、unexpected、重複行、不正行がある場合はfail-closedで拒否する。
ファイル上の内容監査参照は変更せず、dry-runのGoogle Sheets書込み経路も生成しない。

成果物はMarkdown / CSV / JSON / progress.logとし、物理Sheet行、日時、会場、競技、旧値、新値、
ResCode、監査分類、表示分類、更新適格性を保存する。Google Sheet全体の再生成、A:EやGの更新、
非対象Fの更新、行・列の追加・削除・並び替え、7列schema変更は行わない。

dry-run例:

```bash
.venv/bin/python tools/event/aichi_nagoya_2026_session_info_updater.py --dry-run \
  --content-audit logs/aichi_nagoya_2026_content_audit_2026-09-15.md \
  --content-reference-results logs/aichi_nagoya_2026_results_audit_2026-09-15.json \
  --output-prefix logs/aichi_nagoya_2026_session_info_update_plan_2026-09-16
```

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

- イベント系のCSV同期は既存仕様を維持。ただし `道路情報` は手動修正・秘密ルート行を守るsafe upsert方式
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
- `nagoya-road-monthly.timer`: 毎日10:05、10:15、12:00、18:05 JSTに道路PDFを確認する。取得済み月はstateでskipし、未取得月は後続日も再試行する。18:05の失敗だけを当日の最終失敗通知対象とする。
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

### 13.1 近鉄名古屋線の正規化

近鉄の通知対象は名古屋線である。対象判定の正本はトップページに掲載された路線名とし、詳細本文から抽出した `main_line` や `affected_lines` は対象判定に使用しない。

処理仕様:

1. スクレーパーはトップページの各行を解析し、路線名、状況、原因、詳細URLの対応関係を取得する。
2. トップページ由来の値を `top_page_line`、`top_page_lines`、`top_page_status`、`top_page_cause` としてdebug snapshotへ保存する。
3. `top_page_lines` に `名古屋線` が含まれる情報だけ詳細ページを取得・解析する。名古屋線がなければ詳細取得前に除外し、`detail_skipped_reason=top_page_target_line_not_found` を保存する。
4. normalizerは通知生成前に `is_kintetsu_nagoya_target()` を必ず通し、`top_page_lines` に名古屋線があるレコードだけを採用する。
5. 採用した詳細の `body_text` から名古屋線を含む文章を抽出し、`近鉄 名古屋線: ...` 形式へ正規化する。
6. 詳細レコードが存在しない場合は、トップページ由来メッセージに `名古屋線` が明記されているものだけをfallback採用する。
7. 正規化結果は `get_all_railway_alerts_snapshot()`、`monitoring_public_railway_alerts()` を経由して `railway_beta_alerts` へ入る。

詳細本文に名古屋線が含まれる場合や、詳細解析済みの旧snapshotで `affected_lines` に名古屋線が含まれる場合でも、トップページの掲載路線が大阪線など別路線であれば通知対象外とする。たとえば「大阪線は、名古屋線で発生した停電の影響により一部運休」という情報は、原因発生場所に名古屋線が登場するだけなので名古屋向け通知を生成しない。名古屋線として詳細解析したレコードでは `affected_lines` を従来どおり生成するが、通知対象判定には使用しない。

ステータスは本文から `運休`、`運転見合わせ`、`遅れ`、`遅延`、`運転変更`、`振替輸送` の順で判定する。たとえば、名古屋線の一部列車運休は次のように記録される。

```text
railway_normalized: operator=近鉄 line=名古屋線 status=運休 accepted=true
railway_beta_alerts:1
```

除外時も理由をログへ記録する。

```text
railway_normalized: operator=近鉄 line=大阪線 status=運休 accepted=false reason=top_page_target_line_not_found
```

主な除外理由:

- `top_page_target_line_not_found`: トップページ掲載路線に名古屋線がない
- `target_line_not_found`: fallbackメッセージに名古屋線の記載がない
- `empty_detail_message`: 詳細レコードから通知本文を作れない
- `invalid_detail_record`: 詳細レコードの形式が不正
- `detail_snapshot_unavailable`: 最新debug snapshotを読み込めない

近鉄の失敗や対象外判定はJR東海、名鉄、名古屋市営地下鉄など他事業者のalert生成を停止させない。

### 13.2 近鉄の発生路線・影響路線

名古屋線がトップページの通知対象である場合、詳細ページから次の構造化項目をdebug recordへ保存する。

- `origin_line`: 障害が発生した路線。詳細タイトルまたは本文の主語から取得する。
- `origin_location`: 発生駅・区間。取得できない場合は空文字列。
- `affected_lines`: 詳細本文に記載された影響路線。従来フィールドを維持する。
- `cause`: 人身事故、設備点検、車両故障などの原因。
- `status`: `遅れ`、`運休`、`遅れ・運休`、`運転見合わせ`、`運転再開` など。
- `direct`: `origin_line` が名古屋線なら `true`、他路線から名古屋線への波及なら `false`。

名古屋線で直接発生した障害は、発生場所と原因を含める。

```text
近鉄 名古屋線: 近鉄名古屋線の江戸橋駅構内で車両故障が発生し、列車に運休が発生しています。
```

他路線からの波及は、発生路線と原因を先に示し、名古屋線側の影響だけを通知する。

```text
近鉄 名古屋線: 奈良線の人身事故の影響で、近鉄名古屋線の一部列車に遅れが発生しています。
```

2026年7月29日の実例では、奈良線の富雄駅構内で発生した人身事故により、奈良線では遅れ・一部運休、名古屋線では近鉄名古屋～伊勢中川間に遅れが発生した。この場合、名古屋線通知へ奈良線側の運休を混ぜず、`origin_line=奈良線`、`affected_lines` に名古屋線を含む、`status=遅れ`、`direct=false` とする。

### 13.3 路線名付き復旧通知

全alertが解消して `change_type=recovered` となった場合、直前の `removed_alerts` のprefixから復旧路線名を生成する。固定文言の「前回の障害」ではなく、次のように対象路線を表示する。

```text
近鉄名古屋線は平常運転に戻りました。
JR中央線は平常運転に戻りました。
```

複数路線が同時に復旧した場合は、重複を除いた路線名を読点で連結する。復旧対象は直前stateのalertから取得し、新たに推測しない。

### 13.4 JR東海在来線の原因・区間変更通知

JR東海在来線では、動物衝突、折り返し列車の遅れ、踏切内障害物など低影響の初回情報を `low_impact` として抑制する既存方針を維持する。ただし、同一路線の前回alertが存在し、公式本文が変わった場合は、低影響マーカーだけで早期終了せず構造化差分判定へ進める。

構造化差分では `incident_key` に路線、原因、影響区間、方向、発生時刻を含める。次の変更は新しい異常incidentとして通知対象にする。

- 原因の変更
- 影響開始駅・終了駅の変更
- status悪化
- 初回の運転再開見込み
- 運転再開時刻の設定
- 振替輸送開始

同じ `incident_key` のままdelivery本文だけが変わった場合は、従来どおり `delivery_message_only` として抑制する。

2026年7月30日の中央線では、前回の「折り返し列車の遅れ」から「勝川駅～春日井駅間で踏切内障害物を検知」へ原因・区間・本文が変わった。このケースは `official_incident_changed` としてpre-LLM filterを通過し、構造化判定で `new_abnormal_incident` として新規通知する。

調査用ログ:

```text
railway_zairai_fetched_body
railway_zairai_previous_body
railway_zairai_diff_result
railway_zairai_notification_target
railway_zairai_not_notified_reason
```

## 14. Lv17.8 雨の開始・終了予測通知

目的:

- 名古屋中心部で雨が始まる直前と止む直前だけを通知し、仕事量の切り替え判断に使う。
- 「雨が降り始めました」「雨が止みました」という事後通知は生成しない。
- Lv14.4で無効化した旧Open-Meteo 1時間雨通知は復活させず、Lv17.8の遷移通知だけを既存の天気state・Discord投稿経路へ追加する。

データ取得:

- `tools/weather/get_open_meteo_alerts.py` がOpen-Meteoの `minutely_15=precipitation` を取得する。
- タイムゾーンは `Asia/Tokyo` 固定。
- 雨判定は既存の `RAIN_THRESHOLD_MM = 0.1` を現在値と予測値で共用する。
- API失敗や15分データ欠損時は通知せず、`rain_transition: no transition reason=data_unavailable` を記録する。

降り始め予測:

- 現在値が0.1mm未満で、15分以内の予測点が0.1mm以上になる場合に通知する。

```text
🌧️ 15分以内に雨が降り始める見込みです
```

降り終わり予測:

- 現在値が0.1mm以上で、30分以内に0.1mm未満となり、その後30分先までの予測点が連続して0.1mm未満の場合に通知する。
- 30分先の予測点が取得できない場合は終了予測を生成しない。

```text
🌤️ 30分以内に雨が止む見込みです
```

状態管理:

- 既存の `data/ai/weather_state.json` に `rain_transition` componentを追加する。
- 主な項目は `start_notice_sent`、`end_notice_sent`、`rain_event_active`。
- 補助項目として `initialized`、`rain_observed`、`dry_confirmations`、`updated_at` を保持する。
- 同一イベントでは開始予測・終了予測をそれぞれ最大1回に抑える。
- 雨なし・開始予測なしを2回連続で確認してからイベント状態をリセットする。1回だけ予報が消えた場合はリセットせず、予報の揺れによる再通知を防止する。
- 初回起動時に現在雨ありかつ終了予測ありでも、終了予測通知は出さない。stateを初期化した次回以降に判定する。

主なログ:

```text
rain_transition: start predicted within 15m
rain_transition: end predicted within 30m
rain_transition: skipped duplicate start
rain_transition: skipped duplicate end
rain_transition: no transition
```

既存機能との関係:

- 気象庁・Yahoo Weatherの取得、既存の雨量severity、風通知、JMA警報・注意報stateは維持する。
- Open-Meteo snapshotは `get_all_weather_snapshot()` の `raw_openmeteo` と `sources.Open-Meteo` に保存するが、旧1時間予報文は `normalized_alerts` へ追加しない。
- 遷移通知は `evaluate_weather_state()` で既存メッセージと統合され、既存のDiscord投稿先・投稿処理を通る。

## 14.1 Lv17.9 雨通知・名鉄通知改善

名鉄運転見合わせ通知:

- 名鉄公式の異常情報は `運転見合わせ`、`区間`、`理由`、`備考` の順で正規化・表示する。
- 備考本文が `dt/dd/li` の外側にあっても、`踏切通行不可`、`点検中`、`点検作業`、`再開準備`、`運転再開の準備`、`振替輸送` を含む文は重要情報として必ず保持する。
- 運転見合わせ区間内の踏切通行不可情報はDiscord本文へ表示する。
- 2026-08-02の名鉄瀬戸線（栄町～尾張瀬戸、大雨による運転規制、点検作業準備、踏切通行不可、振替輸送）を回帰テストとする。

Open-Meteo雨遷移診断:

- Open-Meteoの `minutely_15=precipitation` と共通閾値 `0.1mm` は維持し、Yahoo雨雲レーダーは比較対象に限る。
- 予測snapshotには現在値、15分以内・30分以内の全予測点、閾値、判定理由、判定結果を保持する。
- 通知・重複抑制・継続雨・予測なし・データ欠損のいずれでも、次の診断ログを必ず出力する。

```text
rain_forecast_current
rain_forecast_15m
rain_forecast_30m
rain_transition_reason
rain_transition_threshold
rain_transition_decision
start_notice_sent
end_notice_sent
```

- 2026-08-02の実運用相当データ（現在0mm、15分予測8.4mm、以後強雨）で開始予測通知が生成されることを回帰テストとする。

## 15. テスト

主な確認コマンド:

```bash
python3 -m py_compile main.py config.py tools/ai/*.py tools/location/*.py tools/railway/*.py
.venv/bin/python -m pytest tests/test_osm_road_geometry.py tests/test_road_aliases.py tests/test_place_labeler.py tests/test_hybrid_placeinfo.py tests/test_placeinfo_review_export.py tests/test_sync_placeinfo_review_sheet.py tests/test_sync_place_dict_sheets.py tests/test_shinkansen_position.py tests/test_railway_incident_manager.py -q
git diff --check
```

キョードー東海の重要テスト:

- `tests/test_kyodo_tokai.py`
- 初回の主要セレクタ0件から再取得で回復した場合、異常通知を作らないこと
- 2回続けて正常一覧を確認できない場合、HTMLと診断JSONを保存すること
- 診断ログにHTTPステータス、最終URL、HTML長、セレクタ件数、保存先を含むこと

劇団四季の重要テスト:

- `tests/test_shiki.py`
- 現行JSON API fixtureから複数公演と名古屋会場を取得できること
- 同日の昼夜公演を別イベントとして保持すること
- 貸切表記を失わないこと
- 月境界や重複レコードから同一公演を重複生成しないこと
- 0件・1件および前回比50%以上減少時に既存CSVを更新しないこと
- 異常時にHTMLと診断JSONを保存すること
- Health Dashboardの前回比50%以上減少警告を維持すること

公式Results照合の重要テスト:

- `tests/test_aichi_nagoya_2026_results.py`
- `tests/test_aichi_nagoya_2026_results_dry_run.py`
- `tests/test_aichi_nagoya_2026_results_audit.py`
- `tests/test_aichi_nagoya_2026_ticket_status_audit.py`
- `tests/test_aichi_nagoya_2026_availability_update_audit.py`
- `tests/test_aichi_nagoya_2026_availability_updater.py`
- 圧縮レスポンスを展開し、H2Hと個人競技を正規化できること
- Results APIの既定言語が`ja`で、明示時だけ`en`を選択できること
- 団体戦の既知`Org`を日本語大会呼称へ変換し、未知`Org`と個人選手名はAPI名へfallbackすること
- Sheet読込がHTTP GETかつ固定7列`A:G`に限定されること
- SheetとResultsのGETに接続・読取timeoutとhard wall-clock timeoutがあること
- Sheet、overview、各競技dailyの進捗と失敗箇所を即時ログで特定できること
- dry-run全体timeoutを超えた場合、後続の外部通信へ進まないこと
- 既知の会場aliasと競技aliasで一致できること
- `MATCH`、`AMBIGUOUS`、`NOT_FOUND`を分類できること
- 全期間監査の6分類、近接候補、TIME_MISMATCH全候補、公式VenueDesc空を区別できること
- 曖昧候補を1件へ自動確定しないこと
- `session_info`候補を表示しても入力行と`availability_status`を変更しないこと
- Ticket/Results/内容監査の突合で、完全一致だけを更新可能とし、複数候補と不一致を保留すること
- 開会式・閉会式のResults不在を例外処理し、Ticket `NOT_FOUND`は旧値保持にすること
- updaterの既定モードがread-onlyで、物理Sheet行を含むG列セルだけを計画すること
- apply直前snapshot不一致、他6列の変化、data validation違反、部分失敗を検出すること

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

## 16. 今後の予定

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

## 17. 変更時の追記ルール

仕様変更時は次の順で更新する。

1. 実装コードとテストを更新
2. このSPECの該当章を更新
3. 運用コマンド、環境変数、Google Sheets列が変わる場合は必ず追記
4. 未実装の構想は「今後の予定」へ移す
5. 手動レビュー列を破壊する可能性がある同期変更は、必ずテストを追加してから反映する
