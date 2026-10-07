# アジパラ短期切替・2026年10月道路データ取込

作業日: 2026-10-08 JST。既存の朝6時通知をそのまま使用する。
本番Google Sheetの置換と旧更新cronの停止は、この作業では実施していない。

## 変更・追加ファイル一覧（15ファイル）

- 既存コード変更: `config.py`、`main.py`、`scrapers/utils/google_sheet_events.py`、`tools/event/aichi_nagoya_2026_bot.py`
- テスト: `tests/test_asia_bot.py`（変更）、`tests/test_asian_para_short_operation.py`（追加）
- 文書: `docs/SPEC.md`（変更）、`docs/asian_para_2026_short_operation.md`（追加）
- ローカル生成ツール: `tools/event/build_asian_para_2026_sessions.py`、`tools/road/import_road_october_2026.py`（追加）
- アジパラデータ: `data/asian_para_2026/raw/session_schedule_20261002.pdf`、`data/asian_para_2026/operational/asian_para_sessions_20261002.csv`、`data/asian_para_2026/operational/asian_para_sessions_20261002.audit.json`（追加）
- 道路データ: `data/road_pdfs/torishimariyoteiR8.10.pdf`、`csv_events/road.csv`（追加）

## 調査結果と変更箇所

- `docs/SPEC.md`を先に確認。実プロジェクトは配布フォルダ内の`nagoya_event-main/`。
- `main.py → send_asia_info() → tools/event/aichi_nagoya_2026_bot.py:send_daily_notice()`が通知経路。
- `scrapers/utils/google_sheet_events.py:load_asia_operational_google_sheet_events()`は既存`アジア大会`タブの固定gidからCSVをGETし、7列を検証する。取得先・タブ名・列は変更していない。
- `main.py`と常駐schedulerにはF/G updaterの呼出しがない。schedulerは天気予報用。6時cron、F/G updaterの実際のcron・wrapperは配布フォルダにないため、サーバー側の確認が必要。
- 旧`sync_asia_csv_to_sheet()`、`cleanup_old_asia_rows()`は通常`main.py`から既に外れている。外部cronからの実行は別途停止確認が必要。
- `config.py`の`ASIAN_PARA_SHORT_OPERATION = True`を通知表示・fallback・旧アジパラ別経路読込停止に使用する。既存の大会全体フラグは維持。
- `tests/test_asia_bot.py`は従来モードの回帰テストを維持し、`tests/test_asian_para_short_operation.py`で短期モードを検証する。

## Sheet投入用データ

原本: [公式Session Schedule・2026-10-02版](https://www.asianparagames-2026.org/wp-content/uploads/2026/10/Session-schedule-for-Aichi-Nagoya-2026-Asian-Para-Games-Ver7-as-of-2-Oct-2026.pdf)。

- `data/asian_para_2026/raw/session_schedule_20261002.pdf`: 原本PDF。
- `data/asian_para_2026/operational/asian_para_sessions_20261002.csv`: 競技151件、19競技、会場19か所。availability_statusは全件空欄。
- 同名`.audit.json`: 原本URL・版・SHA256、PDF行、色、日付、原記号、全時刻枠、確認事項。
- `tools/event/build_asian_para_2026_sessions.py`: 当該PDF専用のローカル抽出。別版を誤使用しないようSHA256を検証する。Web・Sheets・Discordへの接続はない。

```text
date,time,end_time,venue,event_name,session_info,availability_status
```

| 競技日 | セッション数 |
| --- | ---: |
| 2026-10-16 | 6 |
| 2026-10-17 | 10 |
| 2026-10-19 | 27 |
| 2026-10-20 | 29 |
| 2026-10-21 | 28 |
| 2026-10-22 | 23 |
| 2026-10-23 | 24 |
| 2026-10-24 | 4 |
| 合計 | 151 |

黄色55セル89枠、青色42セル62枠。ユーザー確認により両方を採用した。
青色の凡例はCompetition Dayであり、公式練習日とは記載されていない。
1つのセルに複数時刻がある場合は全時刻を別行に保持する。

## 人間確認事項

- OC: 2026-10-18、CC: 2026-10-24。原本は日付・略号のみで、会場・開始・終了時刻は未記載。競技151件には含めていない。既存BOTは開閉会式も扱えるため、公式の別資料で確認できた場合は同じ7列に`開会式`・`閉会式`として追加することを提案する。
- 会場・競技名はPDFのアウトライン文字のため文字抽出できない。画像を目視で転記し、公式英語名を保持した。日本語会場名への置換や営業エリアによる絞込みは行っていない。伊豆などの会場も含む。
- W/M/X/QF/SF/F等は日単位のセル表記。午前・午後それぞれにどの種目や決勝が含まれるかはこのPDFだけでは確定できない。各枠に同じ日単位の情報と原記号を表示し、個別の割当を推測していない。
- 10月18日は競技枠がなく、式典未登録の現状態では当日データなしとして通知をスキップする。

## 本番切替手順（運用担当者が実施）

1. サーバーの`crontab -l`、systemd timer、wrapperを読み取り確認し、下表の旧書込ジョブを停止する。実行中のジョブがないことも確認する。今回cronは変更していない。
2. 現行`アジア大会`タブを退避する。元のタブを削除・再作成せず、同じgidのタブ内のA:Gデータを今回CSVへ全置換する。151データ行+ヘッダー1行とし、旧大会の余剰行が残らないようにする。別の大会前マスターや会場候補タブは対象外。
3. 固定7列・列順を確認する。dateは`YYYY-MM-DD`、time/end_timeは`HH:MM`を維持し、G列は空欄にする。会場の英語表示とOC/CC未登録を確認する。
4. 変更したコードとアジパラfallback CSVを本番ディレクトリへ配置する。`ASIAN_PARA_SHORT_OPERATION = True`、既存`ENABLE_AICHI_NAGOYA_2026`が有効であることを確認する。既存Webhookは再利用し、認証ファイルを変更しない。
5. 下記の大会専用dry-runだけで、Sheetの当日抽出・件数・時刻・チケット非表示を確認する。`main.py`全体は他Sheetへの同期を持つため、確認目的では起動しない。
6. 既存の`main.py`朝6時ジョブを継続する。新しいcronは不要。大会終了後は既存の大会全体フラグをfalseにして停止できる。

```bash
cd /home/ubuntu/nagoya_event
# 保存済みPDFからの再生成。通信・Sheet書込なし。
.venv/bin/python tools/event/build_asian_para_2026_sessions.py
# ローカルCSVのみから本文生成。Discord送信なし。
.venv/bin/python -c "from datetime import date; from tools.event.aichi_nagoya_2026_bot import load_notice_events, build_messages; d=date(2026,10,19); print('\n\n'.join(build_messages(load_notice_events(d, prefer_sheet=False), d)))"
# 本番切替後のSheet読取と本文previewだけ。Discord送信なし。
.venv/bin/python -c "from datetime import date; from tools.event.aichi_nagoya_2026_bot import send_daily_notice; send_daily_notice(date(2026,10,19), dry_run=True)"
```

## 停止すべき旧アジア大会ジョブ

実cronの時刻・登録名は確認できていない。以下のコマンドを直接またはwrapperから呼ぶ登録が停止対象。

| 呼出し対象 | 理由 |
| --- | --- |
| `tools/event/aichi_nagoya_2026_session_info_updater.py --apply` | 旧大会ResultsでF列を更新する |
| `tools/event/aichi_nagoya_2026_availability_updater.py --apply` | 旧大会Ticket/ResultsでG列を更新する |
| `tools/event/sync_aichi_nagoya_2026_operational.py` | 旧大会営業用CSVを7列タブへ書き戻す |
| `sync_asia_csv_to_sheet()`を呼ぶ外部ジョブ | 旧9列CSV同期との衝突を防ぐ |
| `cleanup_old_asia_rows()`を呼ぶ外部ジョブ | 短期用全日程の削除を防ぐ |

`--dry-run`監査は書込なしだが、旧大会用なので短期運用には不要。停止を提案する。
旧開会式Discordテストは短期モードで拒否する。6時の`main.py`と天気schedulerは停止対象ではない。
停止は運用担当者の作業であり、今回のコード変更だけでは外部cronは停止しない。

## 追加依頼: 今月の道路PDF

ユーザー添付`torishimariyoteiR8.10-1.pdf`を`data/road_pdfs/torishimariyoteiR8.10.pdf`に保存。
`tools/road/import_road_october_2026.py`は既存地点抽出を再利用し、当該PDFの目視確認結果を補完して
`csv_events/road.csv`へ79件（オービス地点73、重点取締6）をローカル保存した。
元の`road.csv`は配布フォルダには存在しなかった。

このPDFの地点欄はすべて破線より下の可搬式オービス欄。既存抽出器は縦座標の固定閾値で
先頭17件を一般取締と分類するため、このPDF専用の取込処理だけでオービスへ補正した。
元の抽出器を変更していない。OCRが必要な画像欄は目視で次の6件を転記した。

- 10/10: 交通事故死ゼロの日・携帯電話違反取締り
- 10/20、10/30: 交通事故死ゼロの日・横断歩行者妨害取締り
- 10/30～10/31: 県内一斉飲酒運転取締り（2日分）
- 10/31: 歓楽街の飲酒運転取締り

生活道路30km/hの案内とスポーツの日の祝日表示は取締イベントとして登録しない。
PDFに時刻がないためtimeは従来どおり`未定`。本番道路Sheetへの反映は行っていない。
通常BOTは道路Sheet優先のため、ローカルCSVの作成だけでは本番Sheetの通知内容は変わらない。

## 検証結果

- `pytest -q`実行: 提供ZIPに共通`libs/rokuyou.py`・`libs/discord_sender.py`がなく、また`tests/test_etix.py`が収集時に実ブラウザを起動するため、4件の収集エラー。
- 作業フォルダ外へ導入せず、外側`.tools/`に検証用Pythonを配置。テスト専用pluginで欠落2モジュールのimportだけ代替し、関数が呼ばれた場合は失敗させた。socket接続を遮断。
- UTF-8指定・上記plugin・`--ignore=tests/test_etix.py`の全体検証: **470成功、3失敗**。失敗は既存Results系のPOSIX SIGALRM/setitimer前提のタイムアウトテストで、Windowsには該当APIがない。今回の実装対象外。
- 通知・7列・空欄G列・チケット非表示・既存6時入口・CSV fallback・投稿2000文字内・道路回帰: **64成功**。
- F/G updaterの本番処理や更新CLIは起動していない。全体pytestの既存updater単体テストはmockのread-only処理と仮データを使う。
- この配布フォルダにはGit実行ファイル・`.git`がないため`git diff --check`は実行不可。変更前コピーとのローカルdiffを確認し、変更行・新規ファイルの末尾空白チェックは成功。元からあるconfig.pyの未変更行の空白は触れていない。
- 変更コードの`py_compile`成功。10/19サンプル27件の通知本文をローカル生成し、すべて2000文字以内、販売情報なしを確認。検証用の外側`.tools/`は本番配置対象ではない。
- 本番Sheet書込、cron変更、本番Discord送信、commit、push、credentials/tokenの表示・変更は行っていない。
