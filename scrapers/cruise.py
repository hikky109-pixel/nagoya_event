import argparse
import csv
import re
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


SOURCE_PAGE_URL = "https://www.port-of-nagoya.jp/kanko/senpaku/1002548/index.html"
PDF_DIR = Path("data/cruise_pdfs")
PDF_PATH = PDF_DIR / "cruise_schedule.pdf"
DEFAULT_CSV_PATH = Path("csv_events/cruise.csv")
SOURCE_NAME = "名古屋港管理組合"
NOTE = "クルーズ船"
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
PDF_KEYWORDS = ("入港予定", "クルーズ船", "予定表")
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; nagoya-event-bot/1.0)",
}
ZENKAKU_TRANSLATION = str.maketrans({
    "０": "0",
    "１": "1",
    "２": "2",
    "３": "3",
    "４": "4",
    "５": "5",
    "６": "6",
    "７": "7",
    "８": "8",
    "９": "9",
    "：": ":",
    "（": "(",
    "）": ")",
})


def normalize_text(value) -> str:
    return str(value or "").translate(ZENKAKU_TRANSLATION).strip()


def compact_spaces(value: str) -> str:
    return re.sub(r"[ \t　]+", " ", normalize_text(value)).strip()


def clean_cell(value) -> str:
    return re.sub(r"\s+", " ", normalize_text(value)).strip()


def find_cruise_pdf_url(page_url: str = SOURCE_PAGE_URL) -> str:
    response = requests.get(page_url, headers=REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        link_text = anchor.get_text(" ", strip=True)
        if ".pdf" not in href.lower():
            continue
        if not any(keyword in link_text for keyword in PDF_KEYWORDS):
            continue

        score = sum(keyword in link_text for keyword in PDF_KEYWORDS)
        candidates.append((score, link_text, urljoin(page_url, href)))

    if not candidates:
        raise RuntimeError("クルーズ船入港予定PDFリンクが見つかりません")

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def download_cruise_pdf(pdf_url: str, pdf_path: Path = PDF_PATH, force: bool = True) -> Path:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if force or not pdf_path.exists():
        response = requests.get(pdf_url, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        pdf_path.write_bytes(response.content)

    return pdf_path


def reiwa_to_gregorian(reiwa_year: int) -> int:
    return 2018 + reiwa_year


def infer_year(text: str) -> int:
    normalized = normalize_text(text)

    match = re.search(r"令和\s*(\d+)\s*年\s*\(\s*(\d{4})\s*年\s*\)", normalized)
    if match:
        return int(match.group(2))

    match = re.search(r"(20\d{2})\s*年", normalized)
    if match:
        return int(match.group(1))

    match = re.search(r"令和\s*(\d+)\s*年", normalized)
    if match:
        return reiwa_to_gregorian(int(match.group(1)))

    raise RuntimeError("PDFから対象年を判定できません")


def normalize_time(value: str, default: str = "") -> str:
    text = normalize_text(value)
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return default

    return f"{int(match.group(1)):02d}:{match.group(2)}"


def parse_date_from_text(value: str, year: int) -> str | None:
    text = normalize_text(value)
    match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if not match:
        return None

    month = int(match.group(1))
    day = int(match.group(2))
    return date(year, month, day).isoformat()


def parse_arrival_time(value: str) -> str:
    match = re.search(r"([0-9０-９]{1,2}[:：][0-9０-９]{2})\s*入港", str(value or ""))
    return normalize_time(match.group(1), "未定") if match else "未定"


def parse_departure_time(value: str) -> str:
    matches = re.findall(r"([0-9０-９]{1,2}[:：][0-9０-９]{2})\s*出港", str(value or ""))
    return normalize_time(matches[-1]) if matches else ""


def clean_ship_name(value: str) -> str:
    lines = [compact_spaces(line) for line in str(value or "").splitlines()]
    kept = []

    for line in lines:
        if not line:
            continue
        if line.startswith("(") or line.endswith("代理店"):
            continue
        if "会社" in line or "エイジェンシー" in line:
            continue
        if re.search(r"\d[,\d]*\s*(ﾄﾝ|トン|m|ｍ|名)", line):
            continue
        if any(token in line for token in ("入港", "出港", "総トン", "船名", "備考")):
            continue
        kept.append(line)

    if not kept:
        return ""

    return compact_spaces("".join(kept))


def clean_venue(value: str) -> str:
    text = normalize_text(value)
    if not text:
        return ""

    lines = [compact_spaces(line) for line in text.splitlines() if compact_spaces(line)]
    joined = " ".join(lines)

    berth = ""
    pier = ""

    for line in lines:
        if "ふ頭" in line:
            pier_match = re.search(r"\(?([^()]*ふ頭)\)?", line)
            if pier_match:
                pier = pier_match.group(1).strip()
        if "号" in line and not re.search(r"\d[,\d]*\s*(ﾄﾝ|トン)", line):
            berth_match = re.search(r"([0-9０-９]+(?:[・･,、][0-9０-９]+)*\s*号)", line)
            if berth_match:
                berth = compact_spaces(berth_match.group(1))

    if not berth:
        berth_match = re.search(r"([0-9０-９]+(?:[・･,、][0-9０-９]+)*\s*号)\s*\(?[^()]*ふ頭\)?", joined)
        if berth_match:
            berth = compact_spaces(berth_match.group(1))

    if not pier:
        pier_match = re.search(r"\(?([^()]*ふ頭)\)?", joined)
        if pier_match:
            pier = pier_match.group(1).strip()

    if berth and pier:
        return f"{berth}（{pier}）"
    if pier:
        return pier
    if berth:
        return berth

    return compact_spaces(joined)


def event_from_parts(date_text: str, time_text: str, end_time_text: str, venue: str, title: str, year: int, pdf_url: str) -> dict | None:
    event_date = parse_date_from_text(date_text, year)
    title = clean_ship_name(title)

    if not event_date or not title:
        return None

    return {
        "date": event_date,
        "time": parse_arrival_time(time_text),
        "end_time": parse_departure_time(end_time_text),
        "venue": clean_venue(venue) or "不明",
        "title": title,
        "source": SOURCE_NAME,
        "status": "confirmed",
        "note": NOTE,
        "url": pdf_url,
    }


def parse_table_rows(path: Path, year: int, pdf_url: str) -> list[dict]:
    try:
        import pdfplumber
    except ModuleNotFoundError:
        return []

    events = []

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for table in tables:
                for row in table:
                    cells = [cell or "" for cell in row]
                    row_text = "\n".join(cells)
                    if "入港" not in row_text or "出港" not in row_text:
                        continue

                    date_cell = cells[1] if len(cells) > 1 else row_text
                    ship_cell = cells[2] if len(cells) > 2 else row_text
                    venue_cell = cells[7] if len(cells) > 7 else row_text
                    event = event_from_parts(
                        date_text=date_cell,
                        time_text=date_cell,
                        end_time_text=date_cell,
                        venue=venue_cell,
                        title=ship_cell,
                        year=year,
                        pdf_url=pdf_url,
                    )
                    if event:
                        events.append(event)

    return events


def strip_after_columns(value: str) -> str:
    text = normalize_text(value)
    text = re.split(r"\s{2,}", text, maxsplit=1)[0]
    text = re.sub(r"\d[,\d]*\s*(ﾄﾝ|トン|ｍ|m|名).*", "", text)
    return compact_spaces(text)


def ship_candidate_from_lines(lines: list[str], date_index: int, arrival_index: int) -> str:
    date_line = normalize_text(lines[date_index])
    date_tail = re.sub(r"^.*?\d{1,2}\s*月\s*\d{1,2}\s*日\s*\([^)]*\)", "", date_line).strip()

    arrival_line = normalize_text(lines[arrival_index])
    arrival_tail = re.sub(r"^.*?\d{1,2}:\d{2}\s*入港", "", arrival_line).strip()

    parts = []
    for value in (date_tail, arrival_tail):
        value = strip_after_columns(value)
        if value and not re.fullmatch(r"[0-9・･,、]+号", value):
            parts.append(value)

    if not parts:
        for line in lines[date_index + 1: arrival_index + 4]:
            candidate = strip_after_columns(line)
            if not candidate:
                continue
            if candidate.startswith("(") or "入港" in candidate or "出港" in candidate:
                continue
            if "ふ頭" in candidate or re.fullmatch(r"[0-9・･,、]+号", candidate):
                continue
            parts.append(candidate)
            break

    return clean_ship_name("\n".join(parts))


def venue_from_block(block_lines: list[str]) -> str:
    block = "\n".join(normalize_text(line) for line in block_lines)
    match = re.search(r"([0-9０-９]+(?:[・･,、][0-9０-９]+)*\s*号).*?\(([^()]*ふ頭)\)", block, re.S)
    if match:
        return clean_venue(f"{match.group(1)}\n（{match.group(2)}）")

    return clean_venue(block) or "不明"


def parse_text_events(text: str, year: int, pdf_url: str) -> list[dict]:
    lines = [line.rstrip() for line in normalize_text(text).splitlines()]
    events = []

    arrival_indexes = [
        index for index, line in enumerate(lines)
        if "入港" in line and re.search(r"\d{1,2}:\d{2}", line)
    ]

    for position, arrival_index in enumerate(arrival_indexes):
        date_index = None
        for index in range(arrival_index, max(-1, arrival_index - 4), -1):
            if re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*日", lines[index]):
                date_index = index
                break

        if date_index is None:
            continue

        next_arrival = arrival_indexes[position + 1] if position + 1 < len(arrival_indexes) else len(lines)
        block_lines = lines[date_index:next_arrival]
        block_text = "\n".join(block_lines)
        title = ship_candidate_from_lines(lines, date_index, arrival_index)

        event = event_from_parts(
            date_text=lines[date_index],
            time_text=lines[arrival_index],
            end_time_text=block_text,
            venue=venue_from_block(block_lines),
            title=title,
            year=year,
            pdf_url=pdf_url,
        )
        if event:
            events.append(event)

    return events


def extract_pdf_text(pdf_path: Path) -> tuple[str, bool]:
    try:
        import pdfplumber
    except ModuleNotFoundError:
        pdfplumber = None

    if pdfplumber is not None:
        with pdfplumber.open(pdf_path) as pdf:
            page_texts = [page.extract_text(layout=True) or page.extract_text() or "" for page in pdf.pages]
        return "\n".join(page_texts), True

    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout, False


def extract_pdftotext_text(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def parse_cruise_pdf(pdf_path: Path, pdf_url: str) -> list[dict]:
    full_text, used_pdfplumber = extract_pdf_text(pdf_path)
    year = infer_year(full_text)

    event_sets = [parse_text_events(full_text, year, pdf_url)]

    if used_pdfplumber:
        event_sets.append(parse_table_rows(pdf_path, year, pdf_url))
        try:
            pdftotext_text = extract_pdftotext_text(pdf_path)
            event_sets.append(parse_text_events(pdftotext_text, infer_year(pdftotext_text), pdf_url))
        except Exception:
            pass

    events = max(event_sets, key=len, default=[])
    return sort_events(dedupe_events(events))


def dedupe_events(events: list[dict]) -> list[dict]:
    unique = []
    seen = set()

    for event in events:
        key = (event["date"], event["time"], event["end_time"], event["venue"], event["title"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)

    return unique


def sort_events(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda event: (event["date"], event["time"], event["title"]))


def save_cruise_csv(events: list[dict], csv_path: Path = DEFAULT_CSV_PATH) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(events)


def scrape_cruise(force_download: bool = True, csv_path: Path = DEFAULT_CSV_PATH) -> list[dict]:
    pdf_url = find_cruise_pdf_url()
    pdf_path = download_cruise_pdf(pdf_url, force=force_download)
    events = parse_cruise_pdf(pdf_path, pdf_url)
    save_cruise_csv(events, csv_path)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and extract Nagoya Port cruise ship schedule PDF.")
    parser.add_argument("--no-force-download", action="store_true", help="Use an existing local PDF if present")
    parser.add_argument("--csv-path", default=str(DEFAULT_CSV_PATH), help="Output CSV path")
    args = parser.parse_args()

    events = scrape_cruise(force_download=not args.no_force_download, csv_path=Path(args.csv_path))
    print(f"保存: {args.csv_path} ({len(events)}件)")


if __name__ == "__main__":
    main()
