"""전역 상태 + 락 + 게이트 — 단일 사용자 정비 도구의 유스케이스 공용 기반.

Flask 무의존 — 게이트는 (에러 메시지, HTTP 상태) 튜플을 돌려주고 web 계층이 JSON 으로 감싼다.
그래서 게이트·스펙 파생을 시리얼/서버 없이 단위테스트할 수 있다(헥사고날 개편의 이득).
"""

from __future__ import annotations

import threading

from ..adapters.engines import engine_cls, spec_for
from ..core.layout import pump_label as _pump_label_pure
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
    # (용량 확인 체크 게이트는 2026-09-03 제거 — 연결이 "설정 확정 후 명시 행위"가 되면서 중복.
    #  용량 값(capacity_ml)은 그대로 초기화 힘·스텝 파생의 SoT — 설정에서 정확히 고를 것.)
    # (포트 매핑/향료 개념 제거 — 2026-09-03 사용자 확정: 이 툴은 하드웨어 테스트 벤치라
    #  "어떤 향료가 어느 포트인가"를 몰라야 한다. 포트는 그냥 번호 — 토출 테스트에서 직접 지정.)
    # 밸브 설정(밸브 제어 탭 소관·2026-09-03) — 이 기기의 회전밸브가 무엇인지 사용자가 선언.
    #   kind: "letter"=비분배(3-way 등·i/o) | "numeric"=분배(포트 번호 1..N).
    #   port_count 는 numeric 일 때만 의미(2..N — N 은 기기 보고값). 기본 = 벤치 실물(3-way).
    # 지문 불일치 무시(R9 P1-2 탈출구) — SY-01B 클론이 Tecan 파트넘버를 복제한 개체 대비.
    #   기본 OFF. 켜도 어댑터 -1003 게이트는 남는다(툴 연결단만 우회).
    "allow_fp_mismatch": False,
    "busy": None,  # str | None — 진행 중 작업 라벨
    # 자동 연결 스위치 — **기본 OFF**(개념 개편 2026-09-03: 연결은 설정을 다 고른 뒤 하는
    #   명시 행위다. 부팅하자마자 프로브가 돌면 "설정 → 연결" 순서가 뒤집힌다). ON 은 연결
    #   유지/재연결 옵션: 미연결이면 3초 주기로 현재 설정 기준 재인식.
    "auto_connect": False,
    "connecting": False,  # 자동 인식 진행 중(리뷰 P2-5) — estop 의 temp 어댑터 겹침 방지.
    # 연결 세대 카운터(2026-09-03) — 센소리움 버전 변경마다 +1. 진행 중 connect_core 가
    #   시작 시점 세대와 대조해, 연결 도중 버전이 바뀌면(=구 방언 프로브 결과) 스스로 중단한다.
    "conn_epoch": 0,
    # 진행 중 프로브 어댑터 참조(리뷰 NEW-1) — estop 이 signal_stop 으로 프로브를 즉시 중단시키기 위함.
    "probe_adapter": None,
    # ⛔ 연결 후 첫 정비 게이트(리뷰 P1-2) — 초기화(포트 지정 홈)을 거치기 전의 plunger/
    #   필링은 어댑터 lazy 셋업이 **포트 없는 `Z{힘}R`**(펌웨어 기본 = 포트1 흡입·마지막 포트 배출)
    #   로 돌아 포트1 액체를 빨아 버린다(2026-07-21 실사고 경로). 첫 복구 성공 전엔 모션을 잠근다.
    "initialized_after_connect": False,
    # 서버측 estop 게이트의 미러(검증 P0-2) — 래치가 서면 복구(초기화) 외 모션을 409 차단.
    "estop": False,
    "valve_info": None,  # ?76 판독 결과(연결 시) — None=미판독(정적 폴백)
    "estop_in_progress": False,  # estop TR 발송 중(검증 P0-4) — 그동안 복구 경로도 배제.
    # 밸브(GPIO) — 지연 초기화: "uninit" → GpioValveAdapter | None(사용 불가).
    "valve": "uninit",
    "valve_err": None,
    # 밸브 낙관 표시(admin 미러 — GPIO 출력은 실측 필드가 없어 발행 시각 기반) base → 만료 epoch.
    "valve_open_until": {"sour": 0.0, "normal": 0.0},
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
    - estop 래치: 복구 경로(초기화·세척)만 통과 — admin "복구는 [초기화 & 세척]" 미러.
    (용량 확인 체크 게이트는 2026-09-03 제거 — 연결이 "설정 확정 후 명시 행위"가 되면서
     중복 관문이 됐다. 용량 값 자체는 설정에 남아 스텝 파생에 그대로 쓰인다.)
    """
    if STATE["estop_in_progress"]:
        return ("긴급 정지 발송 중 — 잠시 후 다시 시도하세요.", 409)
    if STATE["estop"] and not is_recovery:
        return ("긴급 정지 래치 상태 — [초기화]로 복구하세요.", 409)
    if not is_recovery and not STATE["initialized_after_connect"]:
        # 연결 후 첫 정비 게이트(P1-2) — 홈 기준을 잡기 전의 플런저 이동 차단(위치 기준 미확정).
        return ("연결 후 [초기화]를 먼저 실행하세요 — 홈 기준·포트를 잡기 전의 동작은 포트1 액체를 소모합니다.", 409)
    return None
