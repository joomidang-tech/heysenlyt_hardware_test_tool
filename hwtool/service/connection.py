"""연결 유스케이스 — 자동 인식(프로브)·본 어댑터 결선·자동 연결 루프 (daemon 부팅 미러)."""

from __future__ import annotations

import subprocess
import time

from senlyt_pi.adapters.serial_port_discovery import list_candidate_ports
from senlyt_pi.pipeline.pump_health import discover_pumps, scan_addresses

import threading

from ..core.sensorium import PUMP_MODEL_LABELS
from .logbus import LOGGER, log
from .state import STATE, current_engine_cls, version

# 연결 전용 락(검증 FAIL-1 봉합·2026-09-01) — 자동/수동 연결의 상호배제(같은 tty 이중 오픈 방지).
#   ⚠️ OP_LOCK(busy)과 **분리**한다: 종전엔 자동 연결 루프가 busy_guard 를 쥔 채 주소 1~9 프로브
#   (펌프 미연결 시 ~190s/사이클·듀티 ~100%)를 돌아, 펌프를 꽂기 전엔 설정·포트맵 변경이
#   영원히 409 였다("펌프를 꽂아야 설정이 되는" 역순 강요 — 재현 6/6·60/60). 연결은 모션이
#   아니고, 모션은 require_adapter(연결 완료 후에만 통과)가 이미 막으므로 OP_LOCK 이 필요 없다.
#   설정의 기기모델 전환과 진행 중 프로브의 레이스: connect_core 가 어댑터 생성 직전에
#   current_engine_cls() 를 재조회하므로 전환 후엔 새 모델로 붙는다(프로브 자체는 read-only).
_CONNECT_LOCK = threading.Lock()


def probe_port_for_pumps(port: str) -> list[int]:
    """포트 하나를 열어 주소 1..9 프로브 — daemon `autodetect_bus` 와 동일 판정(응답=장착).

    daemon 의 `open_bus_probe` 는 프로브용 어댑터를 닫지 않는다(부팅 1회라 무해). 이 툴은
    버튼으로 반복 실행되므로 **판정 로직은 그대로 두고 뒷정리(close)만 추가**한다.
    """
    probe_adapter = current_engine_cls()(port=port, logger=LOGGER)  # 모델별 구현체(호출 전 게이트 통과).
    STATE["probe_adapter"] = probe_adapter  # estop 의 협조 중단 대상(NEW-1).
    try:
        return discover_pumps(probe_adapter.probe, scan_addresses())
    finally:
        STATE["probe_adapter"] = None
        probe_adapter.close()


def manual_connect(manual: str = "") -> "tuple[dict, int]":
    """수동 재인식(헤더 ⟳) — 진행 중 자동 프로브를 선점(협조 중단)하고 연결 락을 쥔 뒤 실행.

    자동 루프의 프로브가 락을 쥔 채 돌고 있으면(펌프 미연결 시 포트당 수 초) 프로브 어댑터에
    signal_stop 을 걸어 조기 이탈시키고 최대 8초 대기한다 — 수동 조작이 항상 우선.
    """
    pa = STATE["probe_adapter"]
    if pa is not None:
        try:
            pa.signal_stop()
        except Exception:  # noqa: BLE001 — 중단 신호 실패가 수동 연결을 막지 않는다.
            pass
    if not _CONNECT_LOCK.acquire(timeout=8.0):
        return ({"ok": False, "error": "자동 연결이 진행 중입니다 — 잠시 후 다시 시도하세요."}, 409)
    try:
        return connect_core(manual)
    finally:
        _CONNECT_LOCK.release()


def connect_core(manual: str = "", *, quiet: bool = False) -> "tuple[dict, int]":
    """자동 인식 본체 — **호출자가 `_CONNECT_LOCK` 을 쥔 상태**에서 부른다(수동·자동 루프 공용).

    반환 = (payload, http_status). quiet=True(자동 루프)면 실패 로그를 줄인다(주기 재시도라 스팸 방지).
    """
    # 기기 모델 구현체 게이트 — 이 센소리움 버전의 펌프 모델 구현체가 없으면 연결 자체를 거부
    #   (sy01b 구현체로 XCalibur 를 만지는 오배선 방지 — U=NVM 기록 위험).
    if current_engine_cls() is None:
        model = version()["pumpModel"]
        return ({"ok": False, "error": f"이 센소리움 버전의 펌프 기기({PUMP_MODEL_LABELS.get(model, model)}) 구현체가 설치되지 않았습니다 — senlyt-pi 핀 갱신이 필요합니다."}, 501)
    # 같은 버스 충돌 방어(검증 P0-5) — 이 컴퓨터에서 운영 데몬(senlytd)이 돌고 있으면 같은
    #   tty 를 동시에 열게 된다(pyserial 기본 = 배타 잠금 없음 → 프레임 교차·상태 오독).
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "senlytd"], capture_output=True, text=True, timeout=3
        )
        if r.stdout.strip() == "active":
            return ({"ok": False, "error": "운영 데몬(senlytd)이 실행 중입니다 — 같은 펌프 버스를 두 프로세스가 잡으면 프레임이 섞입니다. 먼저 `sudo systemctl stop senlytd` 후 정비하세요."}, 409)
    except Exception:  # noqa: BLE001 — systemctl 부재(맥/일반PC) = 검사 생략.
        pass
    # 기존 연결 정리(재인식 지원) — **분리 먼저, close 나중**(검증 P2-5).
    STATE["connecting"] = True  # estop 이 temp 어댑터로 같은 tty 를 겹쳐 열지 않게(P2-5).
    try:
        old, STATE["adapter"] = STATE["adapter"], None
        STATE["pumps"] = []
        STATE["port"] = None
        if old is not None:
            old.close()
        # 후보 열거 — daemon 부팅과 동일(env SENLYT_SERIAL_PORT 우선·알려진 어댑터 VID/PID 우선).
        cands = [manual] if manual else list_candidate_ports()
        if not cands:
            return ({"ok": False, "error": "시리얼 포트 후보가 없습니다 — USB-RS485 어댑터 연결을 확인하세요."}, 404)
        if not quiet:
            log("info", "펌프 자동 인식 시작", candidates=cands[:8])
        found_port, found_pumps = None, []
        for cand in cands:
            try:
                ids = probe_port_for_pumps(cand)
            except Exception as e:  # noqa: BLE001 — 포트 열기 실패 = 다음 후보(autodetect_bus 동일).
                if not quiet:
                    log("warn", "포트 프로브 실패 — 다음 후보로", port=cand, reason=str(e)[:120])
                continue
            if ids:
                found_port, found_pumps = cand, ids
                break
        if found_port is None:
            return ({"ok": False, "error": "어느 포트에서도 펌프가 응답하지 않습니다 — 24V 전원·RS485 배선·DIP 주소를 확인하세요.", "candidates": cands}, 404)
        # 새 연결 = 새 기계일 수 있다 — 용량 확인·초기화를 다시 요구(P1-5·P1-2).
        #   ⚠️ **어댑터 대입보다 먼저** 잠근다 — connect 가 OP_LOCK 밖에서 돌게 된 뒤(FAIL-1)로는
        #   "새 어댑터는 보이는데 게이트는 옛 값" 창이 모션을 통과시킬 수 있다(먼저 잠그면 창 0).
        STATE["capacity_confirmed"] = False
        STATE["initialized_after_connect"] = False
        # 본 어댑터 — daemon bootstrap 과 동일 구성(핫플러그 자가 회복 port_resolver 포함).
        #   구현체 = 센소리움 버전의 기기 모델(위 게이트 통과분 — 인터페이스는 EnginePort 동일).
        STATE["adapter"] = current_engine_cls()(
            port=found_port, logger=LOGGER, port_resolver=list_candidate_ports
        )
        STATE["adapter_model"] = version()["pumpModel"]
        STATE["port"] = found_port
        STATE["last_port"] = found_port
        STATE["pumps"] = found_pumps
        # ⚠️ estop 래치는 **해제하지 않는다**(리뷰 P1-3) — 어댑터 객체가 새것이어도 물리 펌프는
        #   같은 물건이고 플런저는 어중간한 위치다. 복구는 [약한 초기화]/[세척] 성공뿐.
        log("info", "펌프 인식 완료", port=found_port, pumps=found_pumps)
        return ({"ok": True, "port": found_port, "pumps": found_pumps}, 200)
    finally:
        STATE["connecting"] = False


def auto_connect_loop() -> None:
    """자동 연결 — 데몬 부팅 미러: 시작·연결 상실 시 주기적으로 자동 인식(수동 버튼 불필요).

    미연결 상태에서만 시도하고, **OP_LOCK(busy)은 쥐지 않는다**(검증 FAIL-1 봉합 — 종전엔
    프로브가 busy 를 거의 상시 점유해 펌프 미연결 시 설정·포트맵 변경이 전부 409 였다).
    자동/수동 상호배제는 `_CONNECT_LOCK` 이, 모션과의 배제는 require_adapter(미연결=400)가 담당.
    성공 후에는 어댑터 자체의 핫플러그 자가 회복(port_resolver)이 이어받는다.
    실패 사유는 **상태 전이 시 1회만** 로깅(NEW-4 — 3초 주기 스팸 방지)하고, senlytd 활성처럼
    금방 안 바뀌는 사유면 재시도 간격을 30초로 늘린다(systemctl fork 스팸 방지).
    """
    last_reason = None
    while True:
        sleep_s = 3.0
        try:
            if (
                STATE["adapter"] is None
                and STATE["auto_connect"]  # OFF = 자동 인식 휴면(수동 ⟳만 — 사용자 스위치).
                and _CONNECT_LOCK.acquire(blocking=False)
            ):
                try:
                    if STATE["adapter"] is None:  # 락 획득 사이 수동 연결 완료 가능 — 재확인.
                        payload, _status = connect_core(quiet=True)
                        reason = None if payload.get("ok") else payload.get("error", "")[:80]
                        if reason != last_reason:
                            if reason:
                                log("info", "자동 연결 대기 — 사유", reason=reason)
                            last_reason = reason
                        if reason and "senlytd" in reason:
                            sleep_s = 30.0  # 운영 데몬 활성 = 금방 안 바뀜 — 백오프.
                finally:
                    _CONNECT_LOCK.release()
        except Exception as e:  # noqa: BLE001 — 루프 예외 = 스레드 무음 사망(NEW-2) 방지.
            log("warn", "자동 연결 루프 오류 — 계속 재시도", reason=str(e)[:120])
            sleep_s = 10.0
        time.sleep(sleep_s)
