"""연결 유스케이스 — 자동 인식(프로브)·본 어댑터 결선·자동 연결 루프 (daemon 부팅 미러)."""

from __future__ import annotations

import subprocess
import time

from senlyt_pi.adapters.serial_port_discovery import list_candidate_ports
from senlyt_pi.pipeline.pump_health import discover_pumps, scan_addresses

import threading

from ..core.catalog import valve_info_from_config
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


# ── 유저스페이스 폴백(2026-09-03 벤치 실측 경로) ─────────────────────────────
#   드라이버 없는 맥은 /dev 노드가 아예 없어 후보 0개로 죽었다. PL2303(HXN) 을 pyusb 로 직접
#   구동하는 pl2303py(리눅스 pl2303.c 대조 구현·실기기 84+왕복 검증)를 **마지막 후보**로 얹는다.
#   커널 경로(/dev)가 있으면 언제나 그쪽이 먼저다 — 라즈베리파이·드라이버 설치 맥은 기존 그대로.
USERSPACE_PORT = "pyusb:pl2303"


def _userspace_factory_or_none():
    """pl2303py 가용 시 SerialFactory 반환(미설치·미가용=None — 기존 동작 무변)."""
    try:
        from pl2303py import Pl2303HxnSerial
    except ImportError:
        return None

    def factory(port: str, baud: int, timeout_s: float):
        return Pl2303HxnSerial(baudrate=baud, timeout=timeout_s)

    return factory


def _adapter_kwargs(port: str) -> dict:
    """포트가 유저스페이스 센티널이면 serial_factory 를 얹는다(그 외 = 기존 pyserial 경로)."""
    if port != USERSPACE_PORT:
        return {}
    f = _userspace_factory_or_none()
    if f is None:
        raise IOError("유저스페이스 경로 미가용 — pip install pyusb libusb-package")
    return {"serial_factory": f}


def probe_port_for_pumps(port: str) -> list[int]:
    """포트 하나를 열어 주소 1..9 프로브 — daemon `autodetect_bus` 와 동일 판정(응답=장착).

    daemon 의 `open_bus_probe` 는 프로브용 어댑터를 닫지 않는다(부팅 1회라 무해). 이 툴은
    버튼으로 반복 실행되므로 **판정 로직은 그대로 두고 뒷정리(close)만 추가**한다.
    """
    probe_adapter = current_engine_cls()(
        port=port, logger=LOGGER, **_adapter_kwargs(port)
    )  # 모델별 구현체(호출 전 게이트 통과). 유저스페이스 센티널이면 pl2303py 주입.
    STATE["probe_adapter"] = probe_adapter  # estop 의 협조 중단 대상(NEW-1).
    # 스캔 범위 = **설정(센소리움 버전)의 펌프 주소만**(2026-09-03 — daemon 부팅 ② 미러:
    #   모드가 기대하는 주소만 프로브). 전수 1~9 는 무응답 주소당 ~6초라 1펌프 벤치에서
    #   53초를 낭비했다. 더 넓은 구성은 SENLYT_SERIAL_PORT/수동 포트로 명시하는 경로 유지.
    addrs = version()["pumps"] or scan_addresses()
    t0 = time.monotonic()
    log("info", f"후보 프로브 시작 — {port} 을 열고 설정된 펌프 주소 {addrs} 를 훑습니다", port=port)
    try:
        ids = discover_pumps(probe_adapter.probe, addrs)
        took = round(time.monotonic() - t0, 1)
        if ids:
            log("info", f"후보 프로브 결과 — 펌프 발견: 주소 {ids} ({took}초)", port=port, pumps=ids, elapsedS=took)
        else:
            log("info", f"후보 프로브 결과 — 전 주소 무응답 ({took}초) → 다음 후보", port=port, elapsedS=took)
        return ids
    finally:
        STATE["probe_adapter"] = None
        probe_adapter.close()


def disconnect() -> "tuple[dict, int]":
    """명시적 연결 끊기(오픈-클로즈 대칭·2026-09-03) — [연결]의 짝.

    연결은 [연결]로 열고 [연결 끊기]로 닫는다 — 그 사이엔 유지된다. 끊을 때 자동 재연결도
    함께 끈다(안 그러면 3초 뒤 루프가 도로 붙여 '끊기'가 거짓말이 된다). 진행 중 작업(busy)
    이 있으면 409 — 모션 중 tty 를 닫으면 플런저가 어중간한 위치에 남는다.
    """
    if STATE["busy"]:
        return ({"ok": False, "error": f"작업 진행 중({STATE['busy']}) — 완료 후 끊으세요."}, 409)
    if not _CONNECT_LOCK.acquire(timeout=8.0):
        return ({"ok": False, "error": "연결 작업이 진행 중입니다 — 잠시 후 다시 시도하세요."}, 409)
    try:
        STATE["auto_connect"] = False
        old, STATE["adapter"] = STATE["adapter"], None
        STATE["pumps"] = []
        STATE["port"] = None
        STATE["initialized_after_connect"] = False
        if old is not None:
            try:
                old.close()
            except Exception:  # noqa: BLE001 — 닫기 실패가 상태 정리를 막지 않는다.
                pass
        STATE["valve_info"] = None  # 판독 결과는 그 연결의 것 — 해제와 함께 버린다.
        log("info", "연결 해제 — 어댑터를 닫고 상태를 정리했습니다. 재연결은 설정 확인 후 [🔌 연결]")
        return ({"ok": True}, 200)
    finally:
        _CONNECT_LOCK.release()


def manual_connect(manual: str = "") -> "tuple[dict, int]":
    """수동 재인식(헤더 ⟳) — 진행 중 자동 프로브를 선점(협조 중단)하고 연결 락을 쥔 뒤 실행.

    자동 루프의 프로브가 락을 쥔 채 돌고 있으면(펌프 미연결 시 포트당 수 초) 프로브 어댑터에
    signal_stop 을 걸어 조기 이탈시키고 최대 8초 대기한다 — 수동 조작이 항상 우선.
    """
    # busy 가드 — 라우트가 아니라 유스케이스 소관(2026-09-04 감사 P3: 라우트=파싱·호출·감싸기만).
    #   정비 작업 중 재인식 = 모션 중 어댑터 교체 위험이라 409.
    if STATE["busy"]:
        return ({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}, 409)
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
            return ({"ok": False, "error": "운영 데몬(senlytd)이 실행 중 — 이 기기는 운영 기기입니다. 이 툴은 배관 없는 벤치 전용이라 운영 기기에는 쓰지 않는 것이 원칙입니다(같은 펌프 버스를 두 프로세스가 잡으면 프레임도 섞임). 벤치로 옮기거나, 정말 필요하면 `sudo systemctl stop senlytd` 후 자기 책임으로."}, 409)
    except Exception:  # noqa: BLE001 — systemctl 부재(맥/일반PC) = 검사 생략.
        pass
    # 기존 연결 정리(재인식 지원) — **분리 먼저, close 나중**(검증 P2-5).
    STATE["connecting"] = True  # estop 이 temp 어댑터로 같은 tty 를 겹쳐 열지 않게(P2-5).
    # 연결 세대 캡처(2026-09-03) — 도중에 센소리움 버전이 바뀌면(설정이 epoch 를 올린다)
    #   이 연결은 구 방언으로 찾은 결과라 무효 → 후보 사이·결선 직전에 대조해 스스로 중단.
    epoch = STATE["conn_epoch"]
    _ABORT = ({"ok": False,
               "error": "연결 중 센소리움 버전이 변경되어 연결을 중단했습니다 — 새 설정으로 다시 [🔌 연결]을 누르세요."}, 409)
    try:
        old, STATE["adapter"] = STATE["adapter"], None
        STATE["pumps"] = []
        STATE["port"] = None
        if old is not None:
            old.close()
        # 후보 열거 — daemon 부팅과 동일(env SENLYT_SERIAL_PORT 우선·알려진 어댑터 VID/PID 우선).
        #   + 툴 확장 필터(2026-09-03): 이름으로 명백한 비-펌프 포트(블루투스 이어폰 등)를 걷는다
        #   — 실측에서 cu.Buds3Pro 프로브에 68초를 낭비했다(주소 9개 × 재시도). 펌프 어댑터가
        #   이런 이름을 쓸 일은 없어 안전한 배제(미러 대상 pi 목록엔 넣지 않음 — 맥 전용 현상).
        _NON_PUMP_HINTS = ("buds", "airpods", "iphone", "beats")
        cands = [manual] if manual else [
            c for c in list_candidate_ports()
            if not any(h in c.lower() for h in _NON_PUMP_HINTS)
        ]
        # 유저스페이스 폴백 — /dev 경로 전부 실패 시의 마지막 후보(드라이버 없는 맥·2026-09-03).
        if not manual and _userspace_factory_or_none() is not None:
            cands = cands + [USERSPACE_PORT]
        if not cands:
            return ({"ok": False, "error": "시리얼 포트 후보가 없습니다 — USB-RS485 어댑터 연결을 확인하세요."}, 404)
        # 발견 프로브는 양 기종 모두 `?`(Report — Q 는 XCalibur 래치를 소진해 2026-09-03 `?` 로
        #   반전). 방언 표기는 여기서 기종 분기하지 않는다 — 종전 "tecan=Q" 분기는 어댑터 실프레임
        #   (`_probe_cmd="?"`)과 어긋난 거짓 표기였다(5팀 검증 P2 — 방언 표기의 SoT 는 어댑터).
        model = version()["pumpModel"]
        method = "?(리포트 프로브)"
        t_conn = time.monotonic()
        if not quiet:
            log("info",
                f"연결 시작 — 기기 {PUMP_MODEL_LABELS.get(model, model)} · {method} 방언 · 후보 포트 {len(cands)}개를 순서대로 시도합니다",
                model=PUMP_MODEL_LABELS.get(model, model), method=method, candidates=cands[:8])
        found_port, found_pumps = None, []
        for cand in cands:
            if STATE["conn_epoch"] != epoch:
                log("info", "연결 중단 — 센소리움 버전 변경 감지(후보 순회 중)")
                return _ABORT
            try:
                ids = probe_port_for_pumps(cand)
            except Exception as e:  # noqa: BLE001 — 포트 열기 실패 = 다음 후보(autodetect_bus 동일).
                if not quiet:
                    log("warn", "포트 프로브 실패 — 다음 후보로", port=cand, reason=str(e)[:120])
                continue
            if ids:
                found_port, found_pumps = cand, ids
                break
        if STATE["conn_epoch"] != epoch:
            log("info", "연결 중단 — 센소리움 버전 변경 감지(결선 직전)")
            return _ABORT
        if found_port is None:
            if not quiet:
                log("warn",
                    f"연결 실패 — 후보 {len(cands)}개 전부에서 펌프 무응답 ({round(time.monotonic()-t_conn,1)}초). 24V 전원·RS485 배선·DIP 주소를 확인하세요",
                    candidates=cands)
            return ({"ok": False, "error": "어느 포트에서도 펌프가 응답하지 않습니다 — 24V 전원·RS485 배선·DIP 주소를 확인하세요.", "candidates": cands}, 404)
        # 새 연결 = 새 기계일 수 있다 — 용량 확인·초기화를 다시 요구(P1-5·P1-2).
        #   ⚠️ **어댑터 대입보다 먼저** 잠근다 — connect 가 OP_LOCK 밖에서 돌게 된 뒤(FAIL-1)로는
        #   "새 어댑터는 보이는데 게이트는 옛 값" 창이 모션을 통과시킬 수 있다(먼저 잠그면 창 0).
        STATE["initialized_after_connect"] = False
        # 본 어댑터 — daemon bootstrap 과 동일 구성(핫플러그 자가 회복 port_resolver 포함).
        #   구현체 = 센소리움 버전의 기기 모델(위 게이트 통과분 — 인터페이스는 EnginePort 동일).
        STATE["adapter"] = current_engine_cls()(
            port=found_port,
            logger=LOGGER,
            # 핫플러그 자가회복 — 유저스페이스 연결은 /dev 후보가 무의미하니 자기 자신만.
            port_resolver=(
                (lambda: [USERSPACE_PORT]) if found_port == USERSPACE_PORT else list_candidate_ports
            ),
            **_adapter_kwargs(found_port),
        )
        STATE["adapter_model"] = version()["pumpModel"]
        STATE["port"] = found_port
        STATE["last_port"] = found_port
        STATE["pumps"] = found_pumps
        # ⚠️ estop 래치는 **해제하지 않는다**(리뷰 P1-3) — 어댑터 객체가 새것이어도 물리 펌프는
        #   같은 물건이고 플런저는 어중간한 위치다. 복구는 [초기화]/[세척] 성공뿐.
        # ── 모델 지문 대조(2026-09-03 — "runze 는 runze 만" · R9 P2-4 전 펌프) ──
        #   실물 & 지문이 Tecan(30xxxxxx + rev)인데 설정이 sy01b 면 연결을 거부한다(어댑터
        #   -1003 게이트의 앞단 UX). SY-01B 클론이 파트넘버까지 복제한 개체 대비(R9 P1-2):
        #   운영자 override(allowFpMismatch)로 우회 가능 — 우회 시 어댑터 게이트가 최후 방어.
        from ..adapters.engines import tecan_fingerprint_re  # 결선 경계: 구현체 직수입 금지(감사 P1).
        TECAN_FP_RE = tecan_fingerprint_re()
        fps = {}
        if not hasattr(STATE["adapter"], "model_fingerprint"):
            # 형상 오류(핀 구세대)와 "지문 못 읽음"을 같은 None 으로 접지 않는다(아키텍처 P1-3):
            #   메서드 자체가 없으면 게이트가 무성 fail-open 되는 것이므로 크게 표면화한다.
            log("error", "설치된 senlyt-pi 에 model_fingerprint 가 없습니다(requirements 핀 구세대) — 지문 게이트 없이 진행. 핀 갱신 필요")
        else:
            for _pp in found_pumps:
                try:
                    fps[_pp] = STATE["adapter"].model_fingerprint(_pp)
                except Exception:  # noqa: BLE001 — 지문 실패 = 판정 보류(기존 동작).
                    fps[_pp] = None
        tecan_hits = {a: f for a, f in fps.items() if f and TECAN_FP_RE.match(f)}
        if model != "tecan_xcalibur" and tecan_hits and not STATE.get("allow_fp_mismatch"):
            old2, STATE["adapter"] = STATE["adapter"], None
            STATE["adapter_model"] = None
            STATE["pumps"] = []
            STATE["port"] = None
            try:
                old2.close()
            except Exception:  # noqa: BLE001 — 유저스페이스 close 실패가 정리 자체를 막지 않게(R9 P2-5).
                pass
            hit = next(iter(tecan_hits.values()))
            log("error", f"연결 거부 — 실물 지문 {hit!r} = XCalibur 인데 설정은 {PUMP_MODEL_LABELS.get(model, model)}. 센소리움을 XCalibur 변형으로 바꾸고 다시 연결하세요")
            return ({"ok": False, "error": f"실물은 XCalibur({hit}) 인데 설정이 {PUMP_MODEL_LABELS.get(model, model)} 입니다 — 센소리움 버전을 XCalibur 기기변형으로 바꾼 뒤 [🔌 연결]하세요. (클론 지문 오탐이 확실하면 설정의 '지문 불일치 무시'를 켜고 재시도)"}, 409)
        if model == "tecan_xcalibur" and (not fps or not tecan_hits):
            # 역방향(설정 tecan + 실물 SY-01B)은 err 없이 1/4 과소 토출이 되는 무성 방향이다.
            #   SY-01B `&` 지문이 미실측이라 하드 차단은 못 하지만(오탐 위험), 무응답(None)까지
            #   포함해 **Tecan 이 하나도 확인 안 되면** 반드시 경고한다(종전엔 None 이면 무음).
            log("warn", f"⚠️ 설정은 XCalibur 인데 지문으로 Tecan 이 확인되지 않았습니다(지문 {fps!r}) — 실물이 SY-01B 면 경고 없이 요청량의 1/4 만 나옵니다. 실물 기종을 확인하세요")
        # ── 밸브 구성 판독(?76 · "활용-아니면-무시" 2026-09-03) — 알아보면 UI 가 동적으로
        #   (3-way=방향만·N-port=PN 까지), 못 알아보면 None → 정적 폴백(P1~12 + 방향).
        #   자기 신고 값이라 판정엔 안 쓴다 — 없는 포트는 여전히 기기가 err3 로 거부.
        vi = None
        try:
            cfg = STATE["adapter"].pump_config(found_pumps[0])
            vi = valve_info_from_config(cfg)
        except Exception:  # noqa: BLE001 — 구성 판독 실패가 연결을 막지 않는다(관측 전용).
            pass
        STATE["valve_info"] = vi
        if vi:
            log("info", f"밸브 구성 판독(?76) — 기기 보고: {vi['label']}"
                + (f" → 포트 P1~P{vi['ports']}" if vi["ports"] else " → 방향 선택(입력측/배출측)"))
        else:
            log("info", "밸브 구성 판독 불가 — 정적 폴백(P1~12 + 방향, 판정은 기기)")
        log("info",
            f"연결 완료 — {found_port} 에서 펌프 {found_pumps} 발견·결선 (기기 {PUMP_MODEL_LABELS.get(model, model)} · {method} · 총 {round(time.monotonic()-t_conn,1)}초). 이후 [초기화]로 홈 기준을 잡으세요",
            port=found_port, pumps=found_pumps,
            model=PUMP_MODEL_LABELS.get(model, model), method=method)
        return ({"ok": True, "port": found_port, "pumps": found_pumps,
                 "model": model, "method": method}, 200)
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
