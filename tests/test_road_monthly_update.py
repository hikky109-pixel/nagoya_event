import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapers import road_pdf  # noqa: E402
from scrapers.utils import google_sheet_events as sheets  # noqa: E402
from tools.road import check_monthly_road_pdf as monthly  # noqa: E402


JST = timezone(timedelta(hours=9))


def road_record(day: str, venue: str = "名古屋市内") -> dict:
    return {
        "date": day,
        "time": "未定",
        "end_time": "",
        "venue": venue,
        "title": "交通取締予定",
        "source": "愛知県警",
        "status": "confirmed",
        "note": "取締",
        "url": "https://example.invalid/road.pdf",
    }


def page_result(html: str, etag: str = "page") -> dict:
    return {
        "ok": True,
        "status_code": 200,
        "final_url": monthly.PUBLICATION_PAGE_URL,
        "body": html,
        "length": len(html),
        "last_modified": "Sat, 01 Aug 2026 01:01:00 GMT",
        "etag": etag,
    }


def pdf_result(path: Path, etag: str = "pdf") -> dict:
    path.write_bytes(b"%PDF-test")
    return {
        "ok": True,
        "status_code": 200,
        "final_url": "https://example.invalid/torishimariyoteiR8.8.pdf",
        "path": str(path),
        "length": path.stat().st_size,
        "last_modified": "Sat, 01 Aug 2026 01:01:00 GMT",
        "etag": etag,
    }


def configure_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(monthly, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(monthly, "CSV_PATH", tmp_path / "road.csv")
    monkeypatch.setattr(monthly, "DEBUG_DIR", tmp_path / "debug")
    monkeypatch.setattr(monthly, "post_admin_discord", lambda _message: (False, "disabled"))


def test_july_to_august_month_key_and_pdf_year_month() -> None:
    now = datetime(2026, 8, 1, 10, 5, tzinfo=JST)
    assert monthly.month_key_for(8, now=now) == "R8.8"
    assert road_pdf.infer_year_month(Path("torishimariyoteiR8.8.pdf")) == (2026, 8)


def test_august_first_two_days_empty_but_third_and_later_are_kept() -> None:
    records = [road_record("2026-08-03"), road_record("2026-08-15")]
    assert monthly.future_records(records, date(2026, 8, 2)) == records


def test_1005_previous_month_only_schedules_one_retry(monkeypatch, tmp_path: Path) -> None:
    configure_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        monthly,
        "fetch_publication_page",
        lambda _now: page_result('<a href="torishimariyoteiR8.7.pdf">7月</a>'),
    )
    monkeypatch.setattr(monthly, "download_pdf", lambda _key, _now: pdf_result(tmp_path / "aug.pdf"))
    monkeypatch.setattr(monthly, "extract_target_month_records", lambda _key: ([], 0))

    result = monthly.check_monthly_pdf(now=datetime(2026, 8, 1, 10, 5, tzinfo=JST))

    assert result["status"] == "retry_scheduled"
    assert result["diagnosis"] == "publication_not_updated_yet"
    assert result["csv_preserved"] is True
    assert result["sheet_preserved"] is True


def test_1015_retry_accepts_august_records(monkeypatch, tmp_path: Path) -> None:
    configure_paths(monkeypatch, tmp_path)
    (tmp_path / "state.json").write_text(
        json.dumps({"R8_8": {"attempts": 1}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        monthly,
        "fetch_publication_page",
        lambda _now: page_result('<a href="torishimariyoteiR8.8.pdf">8月</a>', "new-page"),
    )
    monkeypatch.setattr(monthly, "download_pdf", lambda _key, _now: pdf_result(tmp_path / "aug.pdf", "new-pdf"))
    monkeypatch.setattr(
        monthly,
        "extract_target_month_records",
        lambda _key: ([road_record("2026-08-03")], 1),
    )
    monkeypatch.setattr(monthly, "regenerate_road_csv", lambda _key: (1, []))
    monkeypatch.setattr(monthly, "run_sheet_sync", lambda _date: (True, "ok", 1))

    result = monthly.check_monthly_pdf(now=datetime(2026, 8, 1, 10, 15, tzinfo=JST))

    assert result["status"] == "downloaded"
    assert result["parsed_records"] == 1
    assert result["future_records"] == 1
    assert result["sheet_sync_records"] == 1


def test_retry_still_official_no_schedule_preserves_existing_data(monkeypatch, tmp_path: Path) -> None:
    configure_paths(monkeypatch, tmp_path)
    existing = "date,time\n2026-07-31,未定\n"
    (tmp_path / "road.csv").write_text(existing, encoding="utf-8")
    (tmp_path / "state.json").write_text(
        json.dumps({"R8_8": {"attempts": 1}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        monthly,
        "fetch_publication_page",
        lambda _now: page_result('<a href="torishimariyoteiR8.8.pdf">8月</a>'),
    )
    monkeypatch.setattr(monthly, "download_pdf", lambda _key, _now: pdf_result(tmp_path / "aug.pdf"))
    monkeypatch.setattr(monthly, "extract_target_month_records", lambda _key: ([], 0))
    monkeypatch.setattr(monthly, "explicit_no_schedule", lambda _path: True)

    result = monthly.check_monthly_pdf(now=datetime(2026, 8, 1, 10, 15, tzinfo=JST))

    assert result["status"] == "official_no_schedule"
    assert (tmp_path / "road.csv").read_text(encoding="utf-8") == existing


def test_http_success_with_parser_failure_is_diagnosed(monkeypatch, tmp_path: Path) -> None:
    configure_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        monthly,
        "fetch_publication_page",
        lambda _now: page_result('<a href="torishimariyoteiR8.8.pdf">8月</a>'),
    )
    monkeypatch.setattr(monthly, "download_pdf", lambda _key, _now: pdf_result(tmp_path / "aug.pdf"))
    monkeypatch.setattr(
        monthly,
        "extract_target_month_records",
        lambda _key: (_ for _ in ()).throw(ValueError("structure changed")),
    )

    result = monthly.check_monthly_pdf(now=datetime(2026, 8, 1, 10, 5, tzinfo=JST))
    assert result["diagnosis"] == "fetch_or_parse_error"


def test_full_width_calendar_days_with_weekday_labels() -> None:
    words = []
    full_width = str.maketrans("0123456789", "０１２３４５６７８９")
    first_col = 6
    for day in range(1, 32):
        offset = first_col + day - 1
        words.append(
            {
                "text": str(day).translate(full_width),
                "x0": float((offset % 7) * 100),
                "top": float((offset // 7) * 80),
            }
        )
    words.extend([{"text": "月曜日", "x0": 0.0, "top": -20.0}])
    cells = road_pdf.find_day_cells(words, 2026, 8)
    assert [cell["day"] for cell in cells] == list(range(1, 32))


def test_current_and_history_partition_uses_target_date() -> None:
    current, past = sheets._partition_road_records(
        [road_record("2026-07-31"), road_record("2026-08-03")],
        date(2026, 8, 2),
    )
    assert [record["date"] for record in current] == ["2026-08-03"]
    assert [record["date"] for record in past] == ["2026-07-31"]


def test_empty_csv_does_not_touch_existing_sheet(tmp_path: Path) -> None:
    csv_path = tmp_path / "road.csv"
    csv_path.write_text("date,time,end_time,venue,title,source,status,note,url\n", encoding="utf-8")
    result = sheets.sync_road_csv_to_sheet(str(csv_path))
    assert result["reason"] == "empty_csv"
    assert result["synced"] is False


def test_monthly_dedupe_prevents_duplicate_registration() -> None:
    record = road_record("2026-08-03")
    assert road_pdf.dedupe_events([record, dict(record)]) == [record]


def test_timer_uses_jst_1005_and_1015_only() -> None:
    timer = (ROOT / "nagoya-road-monthly.timer").read_text(encoding="utf-8")
    assert "10:05:00 Asia/Tokyo" in timer
    assert "10:15:00 Asia/Tokyo" in timer
    assert "10:01:00" not in timer
