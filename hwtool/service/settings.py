"""상태 스냅샷·설정(센소리움 버전/용량)·포트 매핑 유스케이스 — (payload, status) 반환."""

from __future__ import annotations

import time

from senlyt_pi.core.pump_guard import VALID_SYRINGE_CAPACITIES_ML

from ..adapters.engines import ENGINE_ADAPTERS
from ..core.catalog import (
    DIAG_ASPIRATE_DEFAULT_HZ,
    DISPENSE_SPEED_DEFAULT_HZ,
    SETTINGS_RANGES,
    SLOPE_DEFAULT,
)
from ..core.sensorium import AI_STAMP_SOURCE, PUMP_MODEL_LABELS, SENSORIUM_VERSIONS
from .logbus import log
from .state import STATE, current_engine_cls, pump_label, version


def state_payload() -> dict:
    now = time.time()
    vo = STATE["valve_open_until"]
    return {
        "connected": STATE["adapter"] is not None,
        "port": STATE["port"],
        "pumps": STATE["pumps"],
        "pumpLabels": {str(p): pump_label(p) for p in STATE["pumps"]},
        "mode": STATE["mode"],
        "sensorium": STATE["sensorium"],
        "sensoriumLabel": version()["label"],
        "aiStampSource": AI_STAMP_SOURCE,  # "adapter"=어댑터 정본 / "mirror"=미러 폴백(표기용)
        # 기기 모델(인터페이스/구현체 분리) — 버전이 결정, 구현체 설치 여부를 정직 표기.
        "pumpModel": version()["pumpModel"],
        "pumpModelLabel": PUMP_MODEL_LABELS.get(version()["pumpModel"], version()["pumpModel"]),
        "pumpModelAvailable": current_engine_cls() is not None,
        "versions": [
            {"id": k, "label": v["label"], "family": v["family"], "pumps": v["pumps"],
             "pumpModel": v["pumpModel"], "aiModel": v["aiModel"],
             "modelAvailable": ENGINE_ADAPTERS.get(v["pumpModel"]) is not None}
            for k, v in SENSORIUM_VERSIONS.items()
        ],
        "capacityMl": STATE["capacity_ml"],
        "busy": STATE["busy"],
        "connecting": STATE["connecting"],
        "allowFpMismatch": STATE["allow_fp_mismatch"],
        "initializedAfterConnect": STATE["initialized_after_connect"],
        "autoConnect": STATE["auto_connect"],
        "estop": STATE["estop"],
        "capacities": sorted(VALID_SYRINGE_CAPACITIES_ML),
        # ?76 밸브 구성 판독 결과(연결 시·관측 전용) — null = 미판독(UI 는 정적 폴백).
        "valveInfo": STATE["valve_info"],
        # 속도·경사 유효 범위(클램프 SoT 그대로 노출) — UI 라벨·슬라이더가 이 값으로 그린다.
        #   어댑터 _speed_cmd 가 프리셋 물리 상한(6000Hz·L20)으로 한 번 더 클램프한다.
        "speedRanges": {
            "aspirate": SETTINGS_RANGES["aspirateSpeedHz"],
            "dispense": SETTINGS_RANGES["dispenseSpeedHz"],
            "slope": SETTINGS_RANGES["slope"],
        },
        "speedDefaults": {"aspirate": DIAG_ASPIRATE_DEFAULT_HZ, "dispense": DISPENSE_SPEED_DEFAULT_HZ,
                          "slope": SLOPE_DEFAULT},
        # 밸브 — flavor 전용 노출(admin: fragrance 에선 섹션 숨김). 낙관 표시(발행 시각 기반).
        "valveAvailable": STATE["valve"] not in ("uninit", None),
        "valveError": STATE["valve_err"],
        "valveOpen": {b: max(0, round(t - now)) for b, t in vo.items()},
            }


def apply_settings(body: dict) -> "tuple[dict, int]":
    ver = body.get("sensorium")
    if ver is not None:
        if ver not in SENSORIUM_VERSIONS:
            return ({"ok": False, "error": f"등록되지 않은 센소리움 버전입니다: {ver}"}, 400)
        if ver != STATE["sensorium"]:
            if STATE["busy"]:
                return ({"ok": False, "error": f"작업 진행 중({STATE['busy']}) — 센소리움 버전을 바꿀 수 없습니다."}, 409)
            # 버전 전환 = 계약 전환 — 계열·펌프 구성·포트 시드·용량 기본·**기기 모델**이 함께 바뀐다.
            v = SENSORIUM_VERSIONS[ver]
            # 진행 중 연결 중단(2026-09-03) — 연결 도중 버전이 바뀌면 그 연결은 **구 방언으로
            #   찾은 결과**라 무효다. epoch 를 올려 connect_core 가 스스로 중단하게 하고,
            #   진행 중 프로브엔 signal_stop 으로 조기 이탈을 건다(수동 선점과 같은 기계).
            STATE["conn_epoch"] += 1
            if STATE["connecting"]:
                pa = STATE["probe_adapter"]
                if pa is not None:
                    try:
                        pa.signal_stop()
                    except Exception:  # noqa: BLE001 — 중단 신호 실패가 설정 변경을 막지 않는다.
                        pass
                log("info", "센소리움 버전 변경 — 진행 중이던 연결을 중단합니다", newModel=v["pumpModel"])
            STATE["sensorium"] = ver
            STATE["mode"] = v["family"]
            STATE["capacity_ml"] = v["capacityMl"]
            # 기기 모델이 다른 버전으로 전환 = 통신 규칙이 다르다 — 현 어댑터를 내리고
            #   자동 연결 루프가 새 모델 구현체로 재인식하게 한다(busy 는 위에서 이미 409).
            if STATE["adapter"] is not None and STATE["adapter_model"] != v["pumpModel"]:
                old, STATE["adapter"] = STATE["adapter"], None
                STATE["adapter_model"] = None
                STATE["pumps"] = []
                STATE["port"] = None
                STATE["valve_info"] = None
                old.close()
                log("info", "기기 모델 전환 — 재인식 대기", model=v["pumpModel"])
    cap = body.get("capacityMl")
    if isinstance(cap, (int, float)) and not isinstance(cap, bool):
        if float(cap) not in VALID_SYRINGE_CAPACITIES_ML:
            return ({"ok": False, "error": f"유효 시린지 용량이 아닙니다: {cap}"}, 400)
        if float(cap) != STATE["capacity_ml"]:
            # ⛔ 작업 중 용량 변경 금지(리뷰 P1-1) — 진행 중 필링/세척 스레드의 spec() 이 새 값을
            #   읽어 과다흡입 스텝(용량 반비례)을 만든다. 버전 전환·포트맵과 같은 규약으로 409.
            if STATE["busy"]:
                return ({"ok": False, "error": f"작업 진행 중({STATE['busy']}) — 시린지 용량을 바꿀 수 없습니다."}, 409)
        STATE["capacity_ml"] = float(cap)
    if body.get("allowFpMismatch") is True:
        STATE["allow_fp_mismatch"] = True
    elif body.get("allowFpMismatch") is False:
        STATE["allow_fp_mismatch"] = False
    # 자동 연결 스위치 — 명시적 불리언만 반영(진행 중 연결엔 불개입: OFF 는 다음 시도부터 쉰다).
    if body.get("autoConnect") is True:
        STATE["auto_connect"] = True
    elif body.get("autoConnect") is False:
        STATE["auto_connect"] = False
    return (state_payload(), 200)
