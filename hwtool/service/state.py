"""전역 상태 + 락 + 게이트 — 단일 사용자 정비 도구의 유스케이스 공용 기반.

Flask 무의존 — 게이트는 (에러 메시지, HTTP 상태) 튜플을 돌려주고 web 계층이 JSON 으로 감싼다.
그래서 게이트·스펙 파생을 시리얼/서버 없이 단위테스트할 수 있다(헥사고날 개편의 이득).
"""

from __future__ import annotations

import threading

from ..adapters.engines import engine_cls, spec_for
from ..core.layout import pump_label as _pump_label_pure
from ..core.layout import role_port as _role_port_pure
from ..core.layout import seed_pump_ports
from ..core.sensorium import DEFAULT_SENSORIUM, SENSORIUM_VERSIONS
from senlyt_pi.core.pump_guard import SyringeSpec

STATE = {
    "adapter": None,  # EnginePort 실구현(Sy01b/TecanXCalibur) | None
    "adapter_model": None,  # 연결된 어댑터의 기기 모델 id — 버전 전환 시 재연결 판정용.
    "port": None,  # str | None
    "last_port": None,  # str | None — 마지막으로 펌프가 응답한 포트(비상 estop 폴백용)
    "pumps": [],  # list[int] — 발견된 펌프 주소
    # 센소리움 버전 — 계열(mode)·펌프 구성·포트 시드·용량 기본·기기 모델을 결정하는 계약 단위.
    "sensorium": DEFAULT_SENSORIUM,
    "mode": SENSORIUM_VERSIONS[DEFAULT_SENSORIUM]["family"],  # 파생값 — 버전의 계열(flavor|fragrance)
    "capacity_ml": SENSORIUM_VERSIONS[DEFAULT_SENSORIUM]["capacityMl"],
    # ⛔ 용량 확인 게이트(검증 P1-5) — 초기화 힘(Z/Z1/Z2)·스톨전류·스텝 파생이 전부 이 값에서
    #   나온다(작은 시린지에 Full force = 씰 손상·v1.1.0 실사고). 운영자가 실물과 일치를 명시
    #   확인하기 전엔 모션 버튼을 잠근다.
    "capacity_confirmed": False,
    # 포트 매핑(admin pumpPorts 미러) — {addr(int): {port(int): liquid}}. 시드 = 센소리움 버전.
    "pump_ports": seed_pump_ports(SENSORIUM_VERSIONS[DEFAULT_SENSORIUM]["family"]),
    "busy": None,  # str | None — 진행 중 작업 라벨
    # 자동 연결 스위치(사용자 요청 2026-09-01) — False 면 주기 자동 인식이 쉰다(수동 ⟳만 동작).
    "auto_connect": True,
    "connecting": False,  # 자동 인식 진행 중(리뷰 P2-5) — estop 의 temp 어댑터 겹침 방지.
    # 진행 중 프로브 어댑터 참조(리뷰 NEW-1) — estop 이 signal_stop 으로 프로브를 즉시 중단시키기 위함.
    "probe_adapter": None,
    # ⛔ 연결 후 첫 정비 게이트(리뷰 P1-2) — 약한 초기화/세척(포트 지정 홈)을 거치기 전의 plunger/
    #   필링은 어댑터 lazy 셋업이 **포트 없는 `Z{힘}R`**(펌웨어 기본 = 포트1 흡입·마지막 포트 배출)
    #   로 돌아 포트1 액체를 빨아 버린다(2026-07-21 실사고 경로). 첫 복구 성공 전엔 모션을 잠근다.
    "initialized_after_connect": False,
    # 서버측 estop 게이트의 미러(검증 P0-2) — 래치가 서면 복구(약한 초기화·세척) 외 모션을 409 차단.
    "estop": False,
    "estop_in_progress": False,  # estop TR 발송 중(검증 P0-4) — 그동안 복구 경로도 배제.
    # 밸브(GPIO) — 지연 초기화: "uninit" → GpioValveAdapter | None(사용 불가).
    "valve": "uninit",
    "valve_err": None,
    # 밸브 낙관 표시(admin 미러 — GPIO 출력은 실측 필드가 없어 발행 시각 기반) base → 만료 epoch.
    "valve_open_until": {"sour": 0.0, "normal": 0.0},
    # 향료 필링 진행(admin 순차 패널 미러 — 툴은 로컬이라 실시간) — None | dict.
    #   {active, phase, targets:[{pump,port,label}], current(진행 인덱스), results:[...], outcome}
    "filling": None,
}
# 정비 작업 직렬화 락 — daemon 이 정비/제조를 큐로 직렬화하는 것의 미러.
#   ⚠️ 긴급 정지는 이 락을 **타지 않는다**(어댑터가 스레드 안전 + estop 래치가 in-flight 폴을 깨움).
#   밸브도 안 탄다(L3 자체 락·시리얼과 독립 — pi 규약 그대로).
OP_LOCK = threading.Lock()


def version() -> dict:
    return SENSORIUM_VERSIONS[STATE["sensorium"]]


def spec() -> SyringeSpec:
    """용량 → SyringeSpec — 풀스트로크 축은 기기 모델(센소리움 버전)이 결정(adapters.engines)."""
    return spec_for(version()["pumpModel"], STATE["capacity_ml"])


def current_engine_cls():
    """현재 센소리움 버전의 기기 모델 → 어댑터 클래스 (미설치/미등록 = None — 호출자가 거부)."""
    return engine_cls(version()["pumpModel"])


def pump_label(addr: int) -> str:
    return _pump_label_pure(STATE["mode"], addr)


def role_port(addr: int, role: str) -> int:
    return _role_port_pure(STATE["pump_ports"], STATE["mode"], addr, role)


def busy_guard(label: str):
    """작업 락 non-blocking 획득 — 실패 시 None 반환(409)."""
    if not OP_LOCK.acquire(blocking=False):
        return None
    STATE["busy"] = label
    return OP_LOCK


def release(lock) -> None:
    STATE["busy"] = None
    lock.release()


def require_adapter():
    """어댑터 존재 게이트 — (adapter, None) 또는 (None, (메시지, 400))."""
    a = STATE["adapter"]
    if a is None:
        return None, ("펌프가 연결되지 않았습니다 — 먼저 자동 인식을 실행하세요.", 400)
    return a, None


def motion_gate(*, is_recovery: bool = False):
    """모션 요청 공통 게이트 — 통과 시 None, 차단 시 (메시지, HTTP 상태).

    - estop 발송 중: 전부 차단(P0-4).
    - estop 래치: 복구 경로(약한 초기화·세척)만 통과 — admin "복구는 [약한 초기화 & 세척]" 미러.
    - 용량 미확인: 전부 차단(P1-5).
    """
    if STATE["estop_in_progress"]:
        return ("긴급 정지 발송 중 — 잠시 후 다시 시도하세요.", 409)
    if STATE["estop"] and not is_recovery:
        return ("긴급 정지 래치 상태 — [약한 초기화] 또는 [세척]으로 복구하세요.", 409)
    if not STATE["capacity_confirmed"]:
        return ("시린지 용량 확인이 필요합니다 — 설정에서 실물 용량과 일치함을 체크하세요.", 400)
    if not is_recovery and not STATE["initialized_after_connect"]:
        # 연결 후 첫 정비 게이트(P1-2) — 포트 지정 홈을 거치기 전의 lazy 셋업(Z 포트 생략) 차단.
        return ("연결 후 [약한 초기화]를 먼저 실행하세요 — 홈 기준·포트를 잡기 전의 동작은 포트1 액체를 소모합니다.", 409)
    return None
