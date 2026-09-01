"""상태 스냅샷·설정(센소리움 버전/용량)·포트 매핑 유스케이스 — (payload, status) 반환."""

from __future__ import annotations

import time

from senlyt_pi.core.pump_guard import VALID_SYRINGE_CAPACITIES_ML

from ..adapters.engines import ENGINE_ADAPTERS
from ..core.catalog import FLAVOR_LIQUID_KO, FRAGRANCE_NOTES_KO, MAX_PORT, ROLE_LABELS
from ..core.layout import seed_layout, seed_pump_ports, seq_targets, tiles
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
        "capacityConfirmed": STATE["capacity_confirmed"],
        "pumpPorts": {str(a): {str(p): liq for p, liq in layout.items()}
                      for a, layout in STATE["pump_ports"].items()},
        "roleLabels": ROLE_LABELS,
        # 액체 카탈로그(현재 계열) — 포트 매핑 select 선택지(admin catalogFor 미러).
        "liquidCatalog": (
            [{"value": k, "label": v} for k, v in FLAVOR_LIQUID_KO.items()]
            if STATE["mode"] == "flavor"
            else [{"value": k, "label": ko} for k, ko in FRAGRANCE_NOTES_KO]
        ),
        "busy": STATE["busy"],
        "autoConnect": STATE["auto_connect"],
        "estop": STATE["estop"],
        "capacities": sorted(VALID_SYRINGE_CAPACITIES_ML),
        # 밸브 — flavor 전용 노출(admin: fragrance 에선 섹션 숨김). 낙관 표시(발행 시각 기반).
        "valveAvailable": STATE["valve"] not in ("uninit", None),
        "valveError": STATE["valve_err"],
        "valveOpen": {b: max(0, round(t - now)) for b, t in vo.items()},
        "filling": STATE["filling"],
    }


def tiles_payload() -> dict:
    """액체 타일 — admin 진단 도구의 포트 선택 UI 재료([포트 매핑] 현재 배치 기준·발견 펌프만)."""
    t = tiles(STATE["pumps"], STATE["pump_ports"], STATE["mode"])
    return {"tiles": t, "seqTargets": seq_targets(t)}


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
            STATE["sensorium"] = ver
            STATE["mode"] = v["family"]
            STATE["capacity_ml"] = v["capacityMl"]
            STATE["capacity_confirmed"] = False  # 버전이 바뀌면 실물 재확인.
            STATE["pump_ports"] = seed_pump_ports(v["family"], v["pumps"])
            # 기기 모델이 다른 버전으로 전환 = 통신 규칙이 다르다 — 현 어댑터를 내리고
            #   자동 연결 루프가 새 모델 구현체로 재인식하게 한다(busy 는 위에서 이미 409).
            if STATE["adapter"] is not None and STATE["adapter_model"] != v["pumpModel"]:
                old, STATE["adapter"] = STATE["adapter"], None
                STATE["adapter_model"] = None
                STATE["pumps"] = []
                STATE["port"] = None
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
            STATE["capacity_confirmed"] = False  # 값이 바뀌면 재확인(P1-5).
        STATE["capacity_ml"] = float(cap)
    if body.get("confirmCapacity") is True:
        STATE["capacity_confirmed"] = True
    elif body.get("confirmCapacity") is False:
        STATE["capacity_confirmed"] = False  # 체크 해제도 서버에 반영(리뷰 P2-6).
    # 자동 연결 스위치 — 명시적 불리언만 반영(진행 중 연결엔 불개입: OFF 는 다음 시도부터 쉰다).
    if body.get("autoConnect") is True:
        STATE["auto_connect"] = True
    elif body.get("autoConnect") is False:
        STATE["auto_connect"] = False
    return (state_payload(), 200)


def apply_portmap(body: dict) -> "tuple[dict, int]":
    """포트 매핑 편집 — admin 설정 '포트 매핑'의 미러(펌프 1대 전체 레이아웃 저장 또는 시드 리셋).

    검증은 admin `clampPorts`+해석기 불변식 미러: 액체 키 정규화(소문자·32자), 같은 펌프 내
    중복 액체 거부, output·air·cleaning/alcohol 각 정확히 1개(초기화·퍼지·세척의 전제).
    """
    pump = body.get("pump")
    version_pumps = version()["pumps"]
    if pump not in version_pumps:
        return ({"ok": False, "error": f"이 센소리움 버전의 펌프가 아닙니다: {pump} (버전 펌프: {version_pumps})"}, 400)
    if STATE["busy"]:
        return ({"ok": False, "error": f"작업 진행 중({STATE['busy']}) — 포트 매핑을 바꿀 수 없습니다."}, 409)
    if body.get("reset") is True:
        STATE["pump_ports"][pump] = seed_layout(STATE["mode"], pump)
        return (state_payload(), 200)
    raw = body.get("ports")
    if not isinstance(raw, dict):
        return ({"ok": False, "error": "ports 는 {\"1\": 액체|null, ...} 형태여야 합니다."}, 400)
    layout: dict[int, str] = {}
    seen: set[str] = set()
    for k, v in raw.items():
        try:
            port = int(k)
        except (TypeError, ValueError):
            return ({"ok": False, "error": f"포트 키가 정수가 아닙니다: {k}"}, 400)
        if not 1 <= port <= MAX_PORT:
            return ({"ok": False, "error": f"포트는 1~{MAX_PORT} 이어야 합니다: {port}"}, 400)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue  # 비움.
        if not isinstance(v, str):
            return ({"ok": False, "error": f"P{port} 액체 값이 문자열이 아닙니다."}, 400)
        liquid = v.strip().lower()[:32]  # normalizeLiquidKey + 32자 절단(clampPorts 미러).
        if liquid in seen:
            return ({"ok": False, "error": f"같은 액체를 두 포트에 중복 지정할 수 없습니다: {liquid}"}, 400)
        seen.add(liquid)
        layout[port] = liquid
    outputs = [p for p, l in layout.items() if l == "output"]
    airs = [p for p, l in layout.items() if l == "air"]
    cleans = [p for p, l in layout.items() if l in ("cleaning", "alcohol")]
    if len(outputs) != 1:
        return ({"ok": False, "error": f"배출(output)은 정확히 1개여야 합니다 (현재 {len(outputs)}개)."}, 400)
    if len(airs) != 1:
        return ({"ok": False, "error": f"공기(air)는 정확히 1개여야 합니다 (현재 {len(airs)}개) — 초기화·퍼지의 전제입니다."}, 400)
    # 정확히 1개 강제(리뷰 P2-4) — 0개면 세척이 모드 기본 포트로 폴백해, 그 포트에 다른 액체가
    #   매핑돼 있을 때 **그 액체를 알코올인 줄 알고 전량 소모**한다(조용한 오동작). fail-closed.
    if len(cleans) != 1:
        return ({"ok": False, "error": f"세척액/알코올 역할은 펌프당 정확히 1개여야 합니다 (현재 {len(cleans)}개) — 세척 시퀀스의 전제입니다."}, 400)
    STATE["pump_ports"][pump] = layout
    log("info", "포트 매핑 갱신", pump=pump, ports={str(p): l for p, l in sorted(layout.items())})
    return (state_payload(), 200)
