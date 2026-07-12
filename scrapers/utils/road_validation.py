from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRAFFIC_SAFETY_CAMPAIGNS_PATH = PROJECT_ROOT / "data" / "road" / "traffic_safety_campaigns.yml"
SPRING_TRAFFIC_SAFETY_TITLE = "春の全国交通安全運動期間中の交通指導取締り"


def parse_road_date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if text.isdigit():
        return int(text)
    return text.strip('"').strip("'")


def _load_simple_campaign_yaml(path: Path) -> dict[str, Any]:
    campaigns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_list_key: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "campaigns:":
            continue

        if stripped.startswith("- "):
            content = stripped[2:]
            if ":" in content:
                current = {}
                campaigns.append(current)
                key, value = content.split(":", 1)
                current[key.strip()] = _parse_scalar(value)
                current_list_key = None
            elif current is not None and current_list_key:
                current.setdefault(current_list_key, []).append(_parse_scalar(content))
            continue

        if current is None or ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            current[key] = _parse_scalar(value)
            current_list_key = None
        else:
            current[key] = []
            current_list_key = key

    return {"campaigns": campaigns}


def load_traffic_safety_campaigns(path: Path = TRAFFIC_SAFETY_CAMPAIGNS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return [
            {
                "id": "spring_national_traffic_safety_campaign",
                "title": SPRING_TRAFFIC_SAFETY_TITLE,
                "season": "春",
                "start_month": 4,
                "start_day": 6,
                "end_month": 4,
                "end_day": 15,
                "keywords": ["交通安全運動"],
            }
        ]

    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = _load_simple_campaign_yaml(path)

    campaigns = data.get("campaigns") if isinstance(data, dict) else []
    return [campaign for campaign in campaigns if isinstance(campaign, dict)]


def _campaign_bounds(campaign: dict[str, Any], year: int) -> tuple[date, date]:
    start = date(year, int(campaign["start_month"]), int(campaign["start_day"]))
    end = date(year, int(campaign["end_month"]), int(campaign["end_day"]))
    if end < start:
        end = date(year + 1, int(campaign["end_month"]), int(campaign["end_day"]))
    return start, end


def _campaign_matches_text(campaign: dict[str, Any], text: str) -> bool:
    keywords = campaign.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = [keywords]
    return all(str(keyword) in text for keyword in keywords)


def _log_rejected(text: str, event_date: date | None) -> None:
    one_line = str(text or "").replace("\n", " / ")
    date_text = event_date.isoformat() if event_date else ""
    print(f"road_ocr: rejected seasonal mismatch text={one_line} date={date_text}")


def traffic_safety_campaign_title(
    text: str,
    event_dates: list[str] | None = None,
    year: int | None = None,
    log_rejection: bool = True,
) -> str | None:
    dates = [parse_road_date(value) for value in event_dates or []]
    dates = [value for value in dates if value is not None]
    campaigns = [
        campaign
        for campaign in load_traffic_safety_campaigns()
        if _campaign_matches_text(campaign, text)
    ]
    if not campaigns:
        return None

    target_years = sorted({value.year for value in dates} or ({year} if year else {date.today().year}))
    for campaign in campaigns:
        for target_year in target_years:
            start, end = _campaign_bounds(campaign, target_year)
            if dates and all(start <= event_date <= end for event_date in dates):
                return str(campaign.get("title") or "")
            if not dates and str(campaign.get("season") or "") in text:
                return str(campaign.get("title") or "")

    if log_rejection:
        for event_date in dates or [None]:
            _log_rejected(text, event_date)
    return None


def is_road_event_seasonally_valid(record: dict[str, Any], log_rejection: bool = False) -> bool:
    title = str(record.get("title") or "")
    if title != SPRING_TRAFFIC_SAFETY_TITLE:
        return True

    event_date = parse_road_date(record.get("date"))
    if event_date is None:
        return True

    for campaign in load_traffic_safety_campaigns():
        if str(campaign.get("title") or "") != title:
            continue
        start, end = _campaign_bounds(campaign, event_date.year)
        if start <= event_date <= end:
            return True

    if log_rejection:
        _log_rejected(title, event_date)
    return False
