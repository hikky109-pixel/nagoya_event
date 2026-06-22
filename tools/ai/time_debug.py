#!/usr/bin/env python3
"""軽量な実行時間計測ログを出す。"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Iterator, TextIO

try:
    import config  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - 単体実行時の保険
    config = None  # type: ignore[assignment]


def enabled() -> bool:
    return bool(getattr(config, "GEMMA_TIME_DEBUG", True)) if config is not None else True


def emit(label: str, elapsed: float, stream: TextIO | None = None) -> None:
    if not enabled():
        return
    target = stream if stream is not None else sys.stdout
    print(f"[TIME] {label} {elapsed:.1f}s", file=target, flush=True)


@contextmanager
def timer(label: str, stream: TextIO | None = None) -> Iterator[None]:
    start = time.time()
    try:
        yield
    finally:
        emit(label, time.time() - start, stream=stream)
