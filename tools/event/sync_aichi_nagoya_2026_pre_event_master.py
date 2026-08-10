#!/usr/bin/env python3
"""One-time immutable sync for the Aichi-Nagoya 2026 pre-event baseline."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.utils.google_sheet_events import sync_asia_pre_event_master_to_sheet


if __name__ == "__main__":
    print(sync_asia_pre_event_master_to_sheet())
