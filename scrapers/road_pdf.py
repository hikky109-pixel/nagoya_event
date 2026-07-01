import argparse
import calendar
import csv
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlretrieve

import pdfplumber

from tools.common.scraper_health import (
    build_admin_warning_message,
    check_count,
    check_sequence,
    check_structure_hash,
    has_major_warning,
)


BASE_URL = "https://www.pref.aichi.jp/police/koutsu/ko-shidou/images"
PDF_DIR = Path("data/road_pdfs")
IMAGE_CROP_DIR = Path("data/road_image_crops")
DEFAULT_CSV_PATH = Path("csv_events/road.csv")
DEFAULT_YEAR = 2026
DEFAULT_MONTH = 5

X_TOL = 35
SKIP_TEXTS = {"県内取締", "り予定", "県内取締り予定", "可搬式", "オービス", "予定", "可搬式オービス予定"}
CSV_FIELDS = [
    "date",
    "time",
    "end_time",
    "venue",
    "title",
    "source",
    "status",
    "note",
    "url",
]


def reiwa_year_for_date(value: date) -> int:
    return value.year - 2018


def pdf_months(today: date | None = None) -> list[str]:
    current = today or date.today()
    reiwa_year = reiwa_year_for_date(current)
    return [f"R{reiwa_year}.{month}" for month in range(1, current.month + 1)]


PDF_MONTHS = pdf_months()


def pdf_url(month_key: str) -> str:
    return f"{BASE_URL}/torishimariyotei{month_key}.pdf"


def pdf_path(month_key: str) -> Path:
    return PDF_DIR / f"torishimariyotei{month_key}.pdf"


def download_pdf(month_key: str, force: bool = False) -> tuple[Path, str]:
    url = pdf_url(month_key)
    path = pdf_path(month_key)
    path.parent.mkdir(parents=True, exist_ok=True)

    if force or not path.exists():
        urlretrieve(url, path)

    return path, url


def infer_year_month(path: Path) -> tuple[int, int]:
    match = re.search(r"R(\d+)\.(\d+)", path.name)
    if not match:
        return DEFAULT_YEAR, DEFAULT_MONTH

    reiwa_year = int(match.group(1))
    month = int(match.group(2))
    return 2018 + reiwa_year, month


def clean_text(s):
    if not s:
        return ""

    return (
        s.replace(" ", "")
         .replace("　", "")
         .strip()
    )


def normalize_ocr_text(text: str) -> str:
    return (
        clean_text(text)
        .replace("飲適", "飲酒")
        .replace("飲洒", "飲酒")
        .replace("信楽街", "歓楽街")
        .replace("失楽街", "歓楽街")
        .replace("上行者", "歩行者")
        .replace("妨寺", "妨害")
        .replace("取縮", "取締")
    )


def is_noise_text(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9０-９]+", text))


def extract_words(path: Path) -> list[dict]:
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        return page.extract_words()


def find_day_cells(words: list[dict], year: int | None = None, month: int | None = None) -> list[dict]:
    candidates = []

    for word in words:
        text = clean_text(word.get("text", ""))
        if not text.isdigit():
            continue

        day = int(text)
        if not 1 <= day <= 31:
            continue

        candidates.append({"day": day, "x": float(word["x0"]), "y": float(word["top"])})

    if year is None or month is None:
        return sorted(candidates, key=lambda cell: cell["day"])

    days_in_month = calendar.monthrange(year, month)[1]
    columns = sorted({round(cell["x"], 2) for cell in candidates})
    rows = sorted({round(cell["y"], 2) for cell in candidates})
    first_weekday = date(year, month, 1).weekday()
    first_col = (first_weekday + 1) % 7
    cells = []

    for day in range(1, days_in_month + 1):
        offset = first_col + day - 1
        expected_col = offset % 7
        expected_row = offset // 7
        if expected_col >= len(columns) or expected_row >= len(rows):
            continue

        expected_x = columns[expected_col]
        expected_y = rows[expected_row]
        day_candidates = [cell for cell in candidates if cell["day"] == day]
        if not day_candidates:
            continue

        cell = min(
            day_candidates,
            key=lambda item: abs(item["x"] - expected_x) + abs(item["y"] - expected_y),
        )
        cells.append(cell)

    return sorted(cells, key=lambda cell: cell["day"])


def cell_bottom(cell: dict, cells: list[dict]) -> float:
    y = cell["y"]
    next_rows = [other["y"] for other in cells if other["y"] > y]
    return min(next_rows) if next_rows else y + 70


def event_kind(word_y: float, cell_y: float) -> tuple[str, str]:
    dy = word_y - cell_y
    if 20 <= dy < 33:
        return "交通取締予定", "取締"

    return "可搬式オービス予定", "オービス"


def extract_events(path: Path, url: str) -> list[dict]:
    year, month = infer_year_month(path)
    words = extract_words(path)
    cells = find_day_cells(words, year, month)
    events = []

    for cell in cells:
        day = cell["day"]
        x = cell["x"]
        y = cell["y"]
        bottom = cell_bottom(cell, cells)

        for word in words:
            word_x = float(word["x0"])
            word_y = float(word["top"])

            if abs(word_x - x) > X_TOL or not y + 15 < word_y < bottom:
                continue

            venue = clean_text(word.get("text", ""))
            if not venue or venue in SKIP_TEXTS or venue.startswith("※") or is_noise_text(venue):
                continue

            title, category = event_kind(word_y, y)
            events.append({
                "date": f"{year}-{month:02d}-{day:02d}",
                "time": "未定",
                "end_time": "",
                "venue": clean_text(venue),
                "title": clean_text(title),
                "source": "愛知県警",
                "status": "confirmed",
                "note": clean_text(category),
                "url": url,
            })

    return events


def classify_focus_text(text: str) -> str | None:
    text = normalize_ocr_text(text)

    if "交通事故死ゼロ" in text and "携帯電話" in text:
        return "交通事故死ゼロの日（携帯電話違反取締り）"
    if "交通事故死ゼロ" in text and ("歩行者" in text or "妨害" in text):
        return "交通事故死ゼロの日（歩行者妨害取締り）"
    if "交通事故死ゼロ" in text:
        return "交通事故死ゼロの日"
    if "歩行者" in text and "妨害" in text:
        return "歩行者妨害取締り"
    if "携帯電話" in text:
        return "携帯電話違反取締り"
    if "歓楽街" in text and "飲酒" in text:
        return "歓楽街の飲酒運転取締り"
    if "一斉" in text and "飲酒" in text:
        return "県内一斉飲酒運転取締り"
    if "飲酒" in text:
        return "飲酒運転取締り"
    if "交通安全運動" in text:
        return "春の全国交通安全運動期間中の交通指導取締り"
    if "行楽期" in text:
        return "春の行楽期中における交通指導取締り"
    if "重点取締" in text:
        return "重点取締"

    return None


def parse_focus_period(text: str, year: int) -> list[str]:
    text = normalize_ocr_text(text)
    match = re.search(r"(\d{1,2})月(\d{1,2})日[〜～~ー一\-]*(\d{1,2})月(\d{1,2})日", text)
    if not match:
        return []

    start_month, start_day, end_month, end_day = (int(value) for value in match.groups())
    start = date(year, start_month, start_day)
    end = date(year, end_month, end_day)
    if end < start:
        end = date(year + 1, end_month, end_day)

    dates = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)

    return dates


def date_for_bbox(bbox: tuple[float, float, float, float], cells: list[dict], year: int, month: int) -> str | None:
    x0, top, x1, bottom = bbox
    center_x = (x0 + x1) / 2
    center_y = (top + bottom) / 2

    row_cells = [cell for cell in cells if cell["y"] <= center_y < cell_bottom(cell, cells)]
    if not row_cells:
        return None

    cell = min(row_cells, key=lambda item: abs(item["x"] - center_x))
    return f"{year}-{month:02d}-{cell['day']:02d}"


def ocr_image(image_path: Path) -> str:
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", "jpn+eng", "--psm", "6"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip()


def extract_focus_events(path: Path, url: str, debug: bool = False) -> list[dict]:
    year, month = infer_year_month(path)
    events = []
    IMAGE_CROP_DIR.mkdir(parents=True, exist_ok=True)

    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        cells = find_day_cells(words, year, month)

        for index, image in enumerate(page.images, 1):
            bbox = (image["x0"], image["top"], image["x1"], image["bottom"])
            image_path = IMAGE_CROP_DIR / f"road_{path.stem}_image_{index:02d}.png"
            page.crop(bbox, strict=False).to_image(resolution=300).save(image_path)

            ocr_text = ocr_image(image_path)
            title = classify_focus_text(ocr_text)
            period_dates = parse_focus_period(ocr_text, year) if title else []
            bbox_date = date_for_bbox(bbox, cells, year, month) if title else None
            event_dates = period_dates or ([bbox_date] if bbox_date else [])

            if debug:
                one_line_text = ocr_text.replace("\n", " / ")
                print(f"OCR {path.name} #{index} bbox={bbox} text={one_line_text}")
                print(f"  classify={title} dates={event_dates} crop={image_path}")

            if not title or not event_dates:
                continue

            for event_date in event_dates:
                events.append({
                    "date": event_date,
                    "time": "未定",
                    "end_time": "",
                    "venue": "愛知県内",
                    "title": clean_text(title),
                    "source": "愛知県警",
                    "status": "confirmed",
                    "note": "重点取締",
                    "url": url,
                })

    return events


def extract_all_events_with_health(
    force_download: bool = False,
    debug_ocr: bool = False,
) -> tuple[list[dict], list[str]]:
    events = []
    messages = []
    downloaded_paths = []

    messages.extend(
        check_sequence(
            "aichi_police",
            "pdf_months",
            "months",
            PDF_MONTHS,
            min_count=1,
        )
    )

    for month_key in PDF_MONTHS:
        try:
            path, url = download_pdf(month_key, force=force_download)
        except Exception as exc:
            messages.append(
                "scraper_health_warning: "
                f"aichi_police HTML取得失敗 error={type(exc).__name__} month={month_key}"
            )
            continue
        downloaded_paths.append(path)
        place_events = extract_events(path, url)
        focus_events = extract_focus_events(path, url, debug=debug_ocr)
        print(f"{path}: 地点{len(place_events)}件 / 重点{len(focus_events)}件")
        events.extend(place_events)
        events.extend(focus_events)

    events = sort_events(dedupe_events(events))
    messages.extend(
        check_count(
            "aichi_police",
            "pdfs",
            "pdfs",
            len(downloaded_paths),
            min_count=1,
            drop_ratio=0.8,
        )
    )
    messages.extend(
        check_count(
            "aichi_police",
            "events",
            "events",
            len(events),
            min_count=1,
            drop_ratio=0.8,
        )
    )
    manifest = "\n".join(
        f"{path.name}:{path.stat().st_size if path.exists() else 0}"
        for path in downloaded_paths
    )
    messages.extend(check_structure_hash("aichi_police", manifest, "pdf_manifest"))
    if has_major_warning(messages, "aichi_police"):
        messages.append(
            build_admin_warning_message(
                "愛知県警",
                {"PDF": len(downloaded_paths), "イベント": len(events)},
            )
        )
    return events, messages


def extract_all_events(force_download: bool = False, debug_ocr: bool = False) -> list[dict]:
    events, _messages = extract_all_events_with_health(
        force_download=force_download,
        debug_ocr=debug_ocr,
    )
    return events


def dedupe_events(events: list[dict]) -> list[dict]:
    seen = set()
    unique_events = []

    for event in events:
        if event["note"] == "重点取締":
            key = (event["date"], event["venue"], event["title"], event["source"])
        else:
            key = (event["date"], event["venue"], event["title"], event["note"], event["url"])

        if key in seen:
            continue

        seen.add(key)
        unique_events.append(event)

    return unique_events


def sort_events(events: list[dict]) -> list[dict]:
    note_order = {"重点取締": 0, "取締": 1, "オービス": 2, "工事": 3, "交通規制": 4, "アジア大会": 5, "イベント": 6}
    return sorted(events, key=lambda event: (event["date"], note_order.get(event["note"], 9), event["venue"], event["title"]))


def save_road_csv(events: list[dict], csv_path: Path = DEFAULT_CSV_PATH) -> None:
    csv_path.parent.mkdir(exist_ok=True)

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(events)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and extract Aichi police road enforcement PDFs.")
    parser.add_argument("--force-download", action="store_true", help="Download PDFs even when local files already exist")
    parser.add_argument("--debug-ocr", action="store_true", help="Print OCR text, classification, dates, and bbox")
    args = parser.parse_args()

    events, health_messages = extract_all_events_with_health(
        force_download=args.force_download,
        debug_ocr=args.debug_ocr,
    )
    for message in health_messages:
        print(message)
    save_road_csv(events)
    print(f"保存: csv_events/road.csv ({len(events)}件)")


if __name__ == "__main__":
    main()
