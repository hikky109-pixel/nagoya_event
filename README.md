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

## Google Sheets

Google Sheets sync uses the existing OAuth files under `credentials/`:

- `credentials/credentials.json`
- `credentials/token.json`

If `GOOGLE_SHEET_ID` is set, it overrides the spreadsheet ID inferred from the existing sheet URL.

## OCR dependency

The Misonoza scraper calls the external `tesseract` command for schedule images. Install it at the OS level if OCR fallback is needed, for example:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

No Python OCR package is required by the current production scraper code.
