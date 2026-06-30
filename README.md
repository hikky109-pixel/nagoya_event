# nagoya_event setup

This project is intended to run from a project-local virtual environment.

```bash
cd /home/ubuntu/nagoya_event
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Cron should use the virtualenv Python directly:

```bash
/home/ubuntu/nagoya_event/.venv/bin/python /home/ubuntu/nagoya_event/main.py
```

## Weather Alert Beta

天気速報βのDiscord投稿先は環境変数で管理する。チャンネルIDはコードに直書きしない。

ローカル `.env` と Ubuntu 本番環境 `/home/ubuntu/nagoya_event/.env` の両方に、同じ設定を追加すること:

```bash
WEATHER_ALERT_CHANNEL_ID=1521500210239635477
```

手動テスト:

```bash
python3 tools/weather/send_weather_alert_beta.py --force --dry-run
```

## Yahoo PlaceInfo Alpha

Yahoo PlaceInfo テストボタンの投稿先は環境変数で管理する。チャンネルIDとYahoo Client IDはコードに直書きしない。

ローカル `.env` と Ubuntu 本番環境 `/home/ubuntu/nagoya_event/.env` の両方に、同じ設定を追加すること:

```bash
YAHOO_CLIENT_ID=...
YAHOO_PLACEINFO_TEST_CHANNEL_ID=1521532870601080852
```

手動テスト:

```bash
python3 tools/location/get_yahoo_placeinfo.py --lat 35.170915 --lon 136.881537 --pretty
python3 tools/location/post_placeinfo_test_button.py --force
```

## Google Sheets

Google Sheets sync uses the existing OAuth files under `credentials/`:

- `credentials/credentials.json`
- `credentials/token.json`

If `GOOGLE_SHEET_ID` is set, it overrides the spreadsheet ID inferred from the existing sheet URL.

### オービス秘伝のタレ

Google Sheets「オービス_可搬式」を正本にする。

通常運用:

```bash
python3 tools/orbis/pull_orbis_sheet.py
git add data/orbis/orbis_mobile.csv
git commit
git push
```

例外運用:

CSVからGoogle Sheetsを復旧したい時だけ、明示的に `--push` を付けて上書きする。

```bash
python3 tools/orbis/sync_orbis_sheet.py --push
```

## OCR dependency

The Misonoza scraper calls the external `tesseract` command for schedule images. Install it at the OS level if OCR fallback is needed, for example:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

No Python OCR package is required by the current production scraper code.
