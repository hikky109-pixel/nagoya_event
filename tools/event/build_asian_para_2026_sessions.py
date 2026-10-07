"""Offline extraction of the single-page official 2 Oct 2026 session grid.

No Sheet, ticket/results API, credentials or Discord access. This deliberately
uses the pinned PDF layout rather than introducing a general matching engine.
Venue/sport labels are PDF outlines and were visually transcribed from the PDF.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[2]
SOURCE_URL = "https://www.asianparagames-2026.org/wp-content/uploads/2026/10/Session-schedule-for-Aichi-Nagoya-2026-Asian-Para-Games-Ver7-as-of-2-Oct-2026.pdf"
SOURCE_SHA256 = "a52aff85eb5f969c4b630b7116787de0061a5ef8a65ab9825be3421b31f50940"
COLUMNS = ["date", "time", "end_time", "venue", "event_name", "session_info", "availability_status"]
# Row boundaries and labels, visually checked against the official PDF.
SPORT_ROWS = [
    (139.32, "Okazaki Chuo Sogo Park Multipurpose Square", "Para Archery"),
    (174.24, "Nagoya City Mizuho Park Athletic Stadium", "Para Athletics"),
    (209.16, "Ichinomiya City Municipal Gymnasium", "Para Badminton"),
    (232.44, "Nagoya City General Gymnasium [Rainbow Hall]", "Boccia"),
    (267.36, "Izu Velodrome", "Para Cycling - Track"),
    (302.28, "Cycle Sports Center 5km Circuit Course", "Para Cycling - Road"),
    (337.20, "Nagoya City Tsuruma Park Multipurpose Sports Field [Terraspo Tsuruma]", "Blind Football"),
    (383.76, "Toyohashi Gymnasium", "Goalball"),
    (407.04, "Aichi Prefectural Martial Arts Hall", "Para Judo"),
    (441.96, "Nagoya City Trade and Industry Center", "Para Powerlifting"),
    (476.88, "Aichi Prefectural General Shooting Gallery", "Shooting Para Sport"),
    (500.16, "Okazaki Chuo Sogo Park Gymnasium", "Sitting Volleyball"),
    (523.44, "Nagoya City General Gymnasium [Rainbow Pool]", "Para Swimming"),
    (558.36, "SKY HALL TOYOTA", "Para Table Tennis"),
    (593.28, "Nagoya City Mizuho Park Gymnasium", "Para Taekwondo"),
    (628.20, "Aichi International Arena", "Wheelchair Basketball"),
    (663.12, "Nagoya City Inae Sports Center", "Para Fencing"),
    (686.40, "WING ARENA KARIYA", "Wheelchair Rugby"),
    (709.68, "Nagoya City Higashiyama Park Tennis Center", "Wheelchair Tennis"),
]
CODE_LABELS = {"W": "女子", "M": "男子", "X": "混合", "O": "オープン", "QF": "準々決勝", "SF": "準決勝", "F": "決勝"}
TIME_RANGE = re.compile(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})")


def extract_sessions(pdf_path):
    pdf_path = Path(pdf_path)
    if hashlib.sha256(pdf_path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("PDF differs from the visually reviewed 2 Oct 2026 source")
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) != 1:
            raise ValueError("Expected the one-page 2 Oct 2026 PDF")
        page = pdf.pages[0]
        if "As of 2 Oct 2026" not in page.extract_text():
            raise ValueError("Wrong PDF revision")
        words = page.extract_words()
        headers = sorted(
            [w for w in words if 108 < w["top"] < 112 and w["text"].isdigit()],
            key=lambda w: w["x0"],
        )
        if [int(w["text"]) for w in headers] != list(range(11, 25)):
            raise ValueError("Unexpected date columns")
        centers = [(w["x0"] + w["x1"]) / 2 for w in headers]
        boundaries = [432.12] + [(a + b) / 2 for a, b in zip(centers, centers[1:])] + [994.2]
        colors = {(1.0, 1.0, 0.0): "gold_medal_day", (0.866667, 0.921569, 0.968627): "competition_day", (0.741176, 0.843137, 0.933333): "competition_day"}
        output, audit = [], []
        for i, (top, venue, sport) in enumerate(SPORT_ROWS):
            bottom = SPORT_ROWS[i + 1][0] if i + 1 < len(SPORT_ROWS) else 732.96
            for j, header in enumerate(headers):
                left, right = boundaries[j:j + 2]
                cell_words = [w for w in words if left <= (w["x0"] + w["x1"]) / 2 < right and top <= w["top"] < bottom]
                if not cell_words:
                    continue
                fills = [r for r in page.rects if r["x0"] <= centers[j] <= r["x1"] and r["top"] <= top + 5 <= r["bottom"] and r["non_stroking_color"] in colors]
                if not fills:
                    raise ValueError(f"Unclassified cell: {sport} October {header['text']}")
                codes = [w["text"] for w in cell_words if re.fullmatch(r"(?:W|M|X|O|QF|SF|F)(?:/(?:W|M|X|O|QF|SF|F))*", w["text"])]
                ranges = [TIME_RANGE.fullmatch(w["text"]) for w in cell_words if TIME_RANGE.fullmatch(w["text"])]
                if len(codes) != 1 or not ranges or len(cell_words) != len(ranges) + 1:
                    raise ValueError(f"Unparsed cell: {sport} October {header['text']}: {cell_words}")
                raw_code = codes[0]
                info = " / ".join(CODE_LABELS[c] for c in raw_code.split("/")) + f"（公式表記: {raw_code}）"
                day = f"2026-10-{int(header['text']):02d}"
                for match in ranges:
                    start, end = [f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}" for t in match.groups()]
                    if end <= start:
                        raise ValueError(f"Invalid time range: {day} {sport} {start}-{end}")
                    output.append(dict(zip(COLUMNS, [day, start, end, venue, sport, info, ""])))
                audit.append({"date": day, "venue": venue, "sport": sport, "pdf_row": i + 1, "color": colors[fills[0]["non_stroking_color"]], "raw_codes": raw_code, "time_ranges": [m.group() for m in ranges]})
    output.sort(key=lambda r: (r["date"], r["time"], r["venue"], r["event_name"]))
    if len({tuple(r.values()) for r in output}) != len(output):
        raise ValueError("Duplicate sessions")
    return output, {"source_url": SOURCE_URL, "source_revision": "2026-10-02", "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(), "competition_sessions": len(output), "sport_rows": len(SPORT_ROWS), "cells": audit, "review_notes": ["Venue and sport labels are outlines: visually transcribed, retained in official English.", "Codes describe the whole daily cell; do not infer which individual time slot contains a final.", "OC 2026-10-18 and CC 2026-10-24 lack venue and times; excluded pending human confirmation.", "Blue denotes Competition Day, not official practice; included per user clarification."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=ROOT / "data/asian_para_2026/raw/session_schedule_20261002.pdf")
    parser.add_argument("--output", type=Path, default=ROOT / "data/asian_para_2026/operational/asian_para_sessions_20261002.csv")
    args = parser.parse_args()
    rows, audit = extract_sessions(args.pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    args.output.with_suffix(".audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"asian_para_competition_sessions={len(rows)} ceremonies=0")


if __name__ == "__main__":
    main()
