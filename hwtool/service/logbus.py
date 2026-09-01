"""로그 링버퍼 — pi 구조화 로그(한글)를 받아 UI 로 흘린다."""

from __future__ import annotations

import threading
from collections import deque

from senlyt_pi.obs.log import StructuredLogger

_LOG_RING: deque = deque(maxlen=2000)  # 시리얼 왕복 DEBUG 가 다작이라 넉넉히(경고 밀림 방지).
_LOG_SEQ = {"n": 0}
_LOG_LOCK = threading.Lock()


def _log_sink(rec: dict) -> None:
    with _LOG_LOCK:
        _LOG_SEQ["n"] += 1
        _LOG_RING.append({"seq": _LOG_SEQ["n"], **rec})


LOGGER = StructuredLogger(service="hw-test-tool", sink=_log_sink)


def log(level: str, message: str, **kw) -> None:
    getattr(LOGGER, level)(message, stage="tool", **kw)


def logs_since(since: int) -> "tuple[list[dict], int]":
    with _LOG_LOCK:
        items = [r for r in _LOG_RING if r["seq"] > since]
    return items, (items[-1]["seq"] if items else since)
