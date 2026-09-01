"""결과 분류·입력 클램프 — 순수 함수 (Flask·STATE 무의존).

에러코드 → (라벨·분류) JSON 은 운영 EngineExecutor 판정과 동일 축(pump_guard 단일 정본).
"""

from __future__ import annotations

from senlyt_pi.core.pump_guard import classify_engine_error_code
from senlyt_pi.test_seam.fake_engine_sentinels import (
    FAKE_EMPTY_RAW_CODE,
    FAKE_TIMEOUT_RAW_CODE,
)

from .catalog import CLASS_LABELS, ERROR_LABELS, MAX_PORT, SETTINGS_RANGES


def result_json(raw_code: int, detail: str | None = None) -> dict:
    # sentinel 선분류(검증 P1-1) — 운영 EngineExecutor 와 동일하게, 무응답·깨진 응답은
    #   classify 이전에 transient(재시도 대상)로 판정한다.
    if raw_code in (FAKE_TIMEOUT_RAW_CODE, FAKE_EMPTY_RAW_CODE):
        return {
            "ok": False,
            "code": raw_code,
            "label": ERROR_LABELS[raw_code],
            "class": "transient",
            "classLabel": CLASS_LABELS["transient"],
            "detail": detail,
        }
    cls = classify_engine_error_code(raw_code).value
    return {
        "ok": raw_code == 0,
        "code": raw_code,
        "label": ERROR_LABELS.get(raw_code, f"미분류 코드 {raw_code}"),
        "class": cls,
        "classLabel": CLASS_LABELS.get(cls, cls),
        "detail": detail,
    }


def valid_port(v) -> bool:
    return isinstance(v, int) and 1 <= v <= MAX_PORT


def clamp_setting(key: str, v, default: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    lo, hi = SETTINGS_RANGES[key]
    return int(min(max(v, lo), hi))  # admin settingsClamp 와 동일한 클램프.
