"""Import the user-supplied October PDF locally, without network or Sheet sync.

Reuse the existing place extractor. The October PDF's place entries are all
below the dashed line (portable speed cameras); its six focus records are
visually transcribed from the image labels. No OCR installation is required.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scrapers.road_pdf import extract_events, dedupe_events, sort_events, save_road_csv


FOCUS_RECORDS = [
    (10, "交通事故死ゼロの日（携帯電話違反取締り）"),
    (20, "交通事故死ゼロの日（歩行者妨害取締り）"),
    (30, "交通事故死ゼロの日（歩行者妨害取締り）"),
    (30, "県内一斉飲酒運転取締り"),
    (31, "歓楽街の飲酒運転取締り"),
    (31, "県内一斉飲酒運転取締り"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "csv_events/road.csv")
    args = parser.parse_args()
    if hashlib.sha256(args.pdf.read_bytes()).hexdigest() != "1469a287f212d7e5f91d00372cb3dce8cb7fc6591882d0b261cc10fe2efc7637":
        raise ValueError("PDF differs from the supplied and visually reviewed October source")
    url = "https://www.pref.aichi.jp/police/koutsu/ko-shidou/images/torishimariyoteiR8.10.pdf"
    rows = dedupe_events(extract_events(args.pdf, url))
    if len(rows) != 73 or any(not r["date"].startswith("2026-10-") for r in rows):
        raise ValueError("Unexpected PDF; expected the supplied October 2026 layout")
    for row in rows:
        # The generic extractor's fixed vertical threshold misclassifies the
        # first portable-camera line as traffic enforcement in this PDF.
        row.update(title="可搬式オービス予定", note="オービス")
    for day, title in FOCUS_RECORDS:
        rows.append({"date": f"2026-10-{day:02d}", "time": "未定", "end_time": "", "venue": "愛知県内", "title": title, "source": "愛知県警", "status": "confirmed", "note": "重点取締", "url": url})
    rows = sort_events(dedupe_events(rows))
    save_road_csv(rows, args.output)
    print(f"local_road_records={len(rows)} portable_camera=73 focus=6 sheet_write=false discord_send=false")


if __name__ == "__main__":
    main()
