"""정비 유스케이스 — estop·초기화·플런저·진단 필링·건강 점검·밸브 (전부 (payload, status) 반환).

admin(heysenlyt-web) 점검·유지보수 화면의 서버측 조립을 로컬에서 미러한다. 펌프 제어의 실체는
어댑터(senlyt_pi EnginePort 구현체) — 여기는 언제·몇 번·어떤 포트로 부를지의 오케스트레이션만.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from senlyt_pi.pipeline.pump_health import scan_addresses
from senlyt_pi.ports.engine_port import EngineDispenseCommand
from senlyt_pi.core.pump_guard import is_volume_within_gate

from ..adapters.engines import estop_fallback_cls
from ..adapters.valve import valve_adapter
from ..core.catalog import (
    ASPIRATE_SPEED_DEFAULT_HZ,
    DIAG_ASPIRATE_DEFAULT_HZ,
    DISPENSE_SPEED_DEFAULT_HZ,
    SLOPE_DEFAULT,
    VALVE_BASES_LABEL,
    VALVE_LATCH_SEC,
)
from ..core.results import clamp_setting, result_json, valid_port
from .logbus import LOGGER, log
from .state import (
    STATE,
    busy_guard,
    current_engine_cls,
    motion_gate,
    pump_label,
    release,
    require_adapter,
    spec,
)


def do_estop(addrs: list[int]) -> dict:
    """긴급 정지 실행 + **검증**(P0-1) — TR 발송 후 펌프별 상태 프로브로 생존을 재확인한다.

    밸브도 즉시 닫는다(admin "긴급 정지 시에도 밸브 즉시 닫힘" 미러 — 이미 초기화된 경우만,
    estop 하자고 GPIO 를 새로 클레임하진 않는다).
    """
    STATE["estop"] = True
    STATE["estop_in_progress"] = True
    try:
        # ⛔ 밸브 닫기는 **펌프 TR 이후 + 별도 스레드**(리뷰 P0-2) — GpioValveAdapter 는 "N초 열기"
        #   동안 L3 락을 쥔 채 잠들어, close_all 을 먼저 부르면 estop 전체가 최대 10초 물린다.
        #   펌프 정지를 절대 지연시키지 않도록 밸브 닫기를 비동기로 던진다(락 풀리는 즉시 닫힘).
        v = STATE["valve"]
        if v not in ("uninit", None):
            def _close_valves() -> None:
                try:
                    v.close_all()
                    STATE["valve_open_until"] = {"sour": 0.0, "normal": 0.0}
                except Exception:  # noqa: BLE001 — 밸브 닫힘 실패가 펌프 정지를 막지 않는다.
                    pass
            threading.Thread(target=_close_valves, daemon=True).start()
        a = STATE["adapter"]
        temp = None
        if a is None and STATE["connecting"]:
            # 자동 인식 중(리뷰 NEW-1) — **거부하지 않는다**(자동 연결 루프 때문에 이 구간이 미연결
            #   시간의 대부분이라, 거부하면 정지 도달이 사실상 막힌다 = 제1원칙 위반). 대신:
            #   ① 프로브 어댑터에 협조 중단(signal_stop — probe() 가 시도마다 확인, ~1.5s 내 이탈)
            #   ② connecting 해제를 짧게 대기(프로브가 tty 를 놓게) → 겹침 없이 TR 경로로 진행
            #   ③ 그래도 안 풀리면 **정지 도달 > 프레임 순도** — last_port 로 그냥 쏜다.
            pa = STATE["probe_adapter"]
            if pa is not None:
                try:
                    pa.signal_stop()
                except Exception:  # noqa: BLE001 — 중단 신호 실패가 정지를 막지 않는다.
                    pass
            deadline = time.monotonic() + 5.0
            while STATE["connecting"] and time.monotonic() < deadline:
                time.sleep(0.05)
            a = STATE["adapter"]  # 그 사이 인식이 성공했으면 정식 어댑터로.
            if a is None and STATE["connecting"]:
                log("warn", "긴급정지 — 프로브 중단 대기 초과, last_port 로 강행(정지 도달 우선)")
        if a is None and STATE["last_port"]:
            # 미연결(P0-3)이어도 마지막으로 펌프가 있던 포트로 즉시 TR.
            #   구현체 미설치 모델이면 sy01b 로 강행 — TR 은 양 기종 공통·모션 없음(정지 도달 우선).
            cls = current_engine_cls() or estop_fallback_cls()
            temp = a = cls(port=STATE["last_port"], logger=LOGGER)
        if a is None:
            return {"ok": False, "error": "연결 이력이 없어 정지 명령을 보낼 포트를 모릅니다 — 24V 전원을 끄세요."}
        try:
            # 발견 펌프가 없으면(인식 전) 주소 1~9 전수 TR — TR 은 모션 없는 멱등 명령이라 안전.
            targets = addrs or list(scan_addresses())
            a.emergency_stop_all(targets)
            verified = {str(p): a.health_probe(p) for p in targets}
        finally:
            if temp is not None:
                temp.close()
        ok = any(v2 != "silent" for v2 in verified.values())
        return {
            "ok": ok,
            "pumps": verified,
            "note": "TR 발송 + estop 래치 — 복구는 [초기화]"
            if ok
            else "⚠️ 전 펌프 무응답 — 정지 도달을 확인하지 못했습니다. 24V 전원을 직접 차단하세요.",
        }
    finally:
        STATE["estop_in_progress"] = False


def health_check() -> "tuple[dict, int]":
    a, err = require_adapter()
    if err:
        return ({"ok": False, "error": err[0]}, err[1])
    # idle 게이트 미러 — daemon 도 제조/정비 중엔 하트비트 프로브를 건너뛴다(모션 중 버스 잡음 회피).
    lock = busy_guard("상태 점검")
    if lock is None:
        return ({"ok": True, "busy": STATE["busy"], "pumps": {}}, 200)
    try:
        out = {str(p): a.health_probe(p) for p in STATE["pumps"]}
        return ({"ok": True, "busy": None, "pumps": out}, 200)
    finally:
        release(lock)


def run_plunger(body: dict) -> "tuple[dict, int]":
    """[흡입/배출] — 테스트 툴의 원형 프리미티브(2026-09-03 통합).

    양쪽 다 volumeUl(슬라이더)을 쓴다(2026-09-03 사용자 확정 — 흡입/배출 대칭):
    op="aspirate": (port 로 회전) → 플런저 **절대** 위치 = volumeUl.
    op="dispense": 회전 → plunger_to(현재 - volumeUl steps) — 그 양만큼만 하강. 실린 양보다
      많으면 400(실린 양을 알려줌 — 전량 비우기 = 그 값으로 요청). 어댑터 `dispense()`(전체
      사이클)를 빌리지 않는다 — 그 경로는 배출 전에 풀스트로크 **흡입**을 먼저 쏜다(R9.5 P0
      — 위치 readback 만 보면 마지막이 0이라 착시 통과).
    port = P1~12(분배) 또는 "i"/"o"(방향 — 3-way) — **필수**(암묵적 현-방향 동작 없음). 절대 이동이라 반복 안전.
    """
    a, err = require_adapter()
    if err:
        return ({"ok": False, "error": err[0]}, err[1])
    gate = motion_gate()
    if gate:
        return ({"ok": False, "error": gate[0]}, gate[1])
    op = body.get("op")
    pump = body.get("pump")
    if op not in ("aspirate", "dispense"):
        return ({"ok": False, "error": "op 는 aspirate|dispense 중 하나여야 합니다."}, 400)
    if isinstance(pump, bool) or pump not in STATE["pumps"]:
        # bool 거부(테스트검증 P3) — JSON true 가 True==1 로 펌프1을 은근히 지정하는 타입 혼동 차단.
        return ({"ok": False, "error": f"연결된 펌프가 아닙니다: {pump}"}, 400)
    port = body.get("port")
    if port in (None, ""):
        # 암묵적 "현 방향 유지" 금지(2026-09-03 사용자 확정) — 밸브가 어쩌다 향한 방향에
        #   의존하는 동작은 비결정적이다. 항상 포트(P1~12) 또는 방향(i/o)을 명시 선택.
        return ({"ok": False, "error": "포트(또는 입력측/배출측 방향)를 선택하세요 — 회전 없는 동작은 지원하지 않습니다."}, 400)
    elif isinstance(port, str) and port.strip().lower() in ("i", "o"):
        port = port.strip().lower()  # 3-way 등 비분배 — 흡입측(IR)/배출측(OR) 방향 회전(R9.5 P2).
    else:
        try:
            port = int(port)
        except (TypeError, ValueError):
            return ({"ok": False, "error": f"포트가 정수가 아닙니다: {port}"}, 400)
        if not 1 <= port <= 12:
            # 상한 12 = 양 매뉴얼 공통 최대(XCalibur Table 3-5 · SY-01B T-03~T-12) — 12 초과 포트는
            #   어느 매뉴얼에도 없다(2026-09-03 조사). 실물 축소는 여전히 기기가 err3 로 판정.
            return ({"ok": False, "error": f"포트는 1~12 이어야 합니다: {port}"}, 400)
    sp = spec()
    cap_ul = sp.syringe_capacity_ml * 1000.0
    try:
        volume_ul = float(body.get("volumeUl") or 0)
    except (TypeError, ValueError):
        return ({"ok": False, "error": "volumeUl 이 숫자가 아닙니다."}, 400)
    op_kr = "흡입" if op == "aspirate" else "배출"
    if not 0 < volume_ul <= cap_ul:
        # 배출도 슬라이더 양을 쓴다(2026-09-03) — 양 게이트는 두 op 공통.
        return ({"ok": False, "error": f"{op_kr}량은 0~{cap_ul:.0f}µL(용량) 안이어야 합니다: {volume_ul}"}, 400)
    if sp.steps_for_volume_ul(volume_ul) <= 0:
        # 1 step 미만(테스트검증 P3) — steps=0 은 조용한 no-op 인데 200 성공으로 보였다.
        return ({"ok": False, "error": f"양이 너무 작습니다(1 step 미만): {volume_ul}µL"}, 400)
    asp_hz = clamp_setting("aspirateSpeedHz", body.get("aspHz"), DIAG_ASPIRATE_DEFAULT_HZ)
    disp_hz = clamp_setting("dispenseSpeedHz", body.get("dispHz"), DISPENSE_SPEED_DEFAULT_HZ)
    slope = clamp_setting("slope", body.get("slope"), SLOPE_DEFAULT)
    port_disp = f"(P{port})" if isinstance(port, int) else ("(입력측)" if port == "i" else "(배출측)")
    label = f"{pump_label(pump)} {'흡입' if op == 'aspirate' else '배출'}" + port_disp
    lock = busy_guard(label)
    if lock is None:
        return ({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}, 409)
    try:
        if op == "aspirate":
            if isinstance(port, str):  # "i"/"o" 방향 회전(3-way) — 회전 후 in_port 없이 흡입.
                # spec 전달 = 회전 **전** 셋업 보장(2026-09-03 검증 P2) — 캐시 무효 상태에서
                #   회전부터 하면 aspirate 의 lazy 재셋업 Z 가 방금 돌린 밸브를 덮는다.
                rv = a.rotate_valve(pump, port, spec=sp)
                if rv.raw_error_code != 0:
                    return ({**result_json(rv.raw_error_code, f"흡입 회전({port.upper()}R) 실패: {rv.detail or ''}"),
                             "position": a.plunger_position(pump)}, 200)
            cmd = EngineDispenseCommand(
                pump_addr=pump,
                volume_ul=volume_ul,
                steps=sp.steps_for_volume_ul(volume_ul),
                spec=sp,
                in_port=port if isinstance(port, int) else None,
                out_port=None,
                aspirate_speed_hz=asp_hz,
                dispense_speed_hz=disp_hz,
                slope=slope,
            )
            log("info", f"{label} — {volume_ul:.0f}µL(={cmd.steps} steps) 절대 위치로 흡입 (속도 {asp_hz}Hz·경사 L{slope})")
            res = a.aspirate(cmd)  # _cycle(aspirate_only=True): 회전(있으면) → 속도 → A{steps}
        else:
            # 배출 = "회전 → A{현재-요청}" 2단 조립 — 흡입 프레임 0건(R9.5 P0 봉합).
            #   슬라이더 양만큼만 하강(2026-09-03 사용자 확정 — 흡입/배출 대칭). 회전 프레임 =
            #   분배밸브 포트는 배출측 O{n}(_cycle 배출 회전과 동일·R9.5 P2), "i"/"o" 는 방향
            #   회전(IR/OR — 3-way 는 "o" 로 배출측을 명시).
            steps = sp.steps_for_volume_ul(volume_ul)
            # 순서(2026-09-03 검증 P2 재정렬): ① 회전(spec — 셋업 보장이 여기서 돈다) →
            #   ② pre 읽기 → ③ 초과 게이트 → ④ 이동. pre 를 회전 **뒤에** 읽는 이유 —
            #   셋업이 이 회전에서 재실행(Z 홈)될 수 있고, 그러면 회전 전에 읽은 pre 는
            #   이미 죽은 기준점이다(홈 후 실제 위치 0). 회전은 부피를 옮기지 않아 선행 무해.
            frame = f"O{port}" if isinstance(port, int) else f"{port.upper()}R"
            rv = (a.rotate_valve(pump, port, out=True, spec=sp) if isinstance(port, int)
                  else a.rotate_valve(pump, port, spec=sp))
            if rv.raw_error_code != 0:
                return ({**result_json(rv.raw_error_code, f"배출 회전({frame}) 실패: {rv.detail or ''}"),
                         "position": a.plunger_position(pump)}, 200)
            pre = a.plunger_position(pump)
            if pre is None:
                return ({"ok": False,
                         "error": "플런저 위치를 읽지 못해 배출량을 계산할 수 없습니다 — [상태 점검] 후 재시도하세요."}, 409)
            if steps > pre:
                pre_ul = pre * cap_ul / sp.pump_full_stroke
                return ({"ok": False,
                         "error": f"실린 양보다 많이 배출할 수 없습니다 — 요청 {volume_ul:.0f}µL(={steps} steps), "
                                  f"실린 {pre_ul:.0f}µL(={pre} steps). 전량 비우려면 양을 {pre_ul:.0f}µL 로 맞추세요."}, 400)
            log("info", f"{label} — {volume_ul:.0f}µL(={steps} steps) 배출(A{pre - steps} 로 하강, "
                        f"속도 {disp_hz}Hz·경사 L{slope})")
            res = a.plunger_to(pump, pre - steps, sp, top_speed_hz=disp_hz, slope=slope)
        pos = a.plunger_position(pump)
        return ({**result_json(res.raw_error_code, res.detail), "position": pos}, 200)
    except OSError as e:
        # 핫플러그/링크 단절 — 500 JSON 대신 정직한 무응답 분류(-1000·transient)로 표면화(R9.5 P3).
        log("error", f"{label} — 시리얼 링크 오류: {e}")
        return ({**result_json(-1000, f"시리얼 링크 오류: {e}"), "position": None}, 200)
    finally:
        release(lock)


def init_pumps(body: "dict | None" = None) -> "tuple[dict, int]":
    """초기화 — 전 펌프 동시 홈(admin forceInitAll 미러 · estop 복구 경로).

    ⛔ **배출구 필수**(2026-09-03 사용자 확정 — "홈 복귀는 배출구를 향하고 해야 한다"):
    홈 복귀는 플런저를 0(전량 배출 위치)까지 미는 동작이라, 실린 액체가 있으면 **밸브가 향한
    포트로 전부 밀려 나간다**. 포트 무지정 Z 는 펌웨어 기본(입력측) 포트를 향할 수 있어
    위험 — 그래서 배출구(port)를 명시 선택해야 한다(미선택 = 400 · 암묵 동작 금지 원칙과 동일).
      - 분배밸브: port = 1..12 → `Z{힘},{p},{p}`(그 포트를 향한 채 홈) + 주차 `I{p}`.
      - 방향형(3-way): port = "o" → 배출측(OR) 선회전 → 힘-전용 Z → 배출측 재확정
        (Z 가 방향형 밸브를 돌리는지 미실측이라 앞뒤로 확정 — "밸브가 쉴 땐 배출구" 규칙).
    """
    body = body or {}
    a, err = require_adapter()
    if err:
        return ({"ok": False, "error": err[0]}, err[1])
    gate = motion_gate(is_recovery=True)
    if gate:
        return ({"ok": False, "error": gate[0]}, gate[1])
    lock = busy_guard("초기화")
    if lock is None:
        return ({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}, 409)
    try:
        addrs = list(STATE["pumps"])
        if not addrs:
            return ({"ok": False, "error": "초기화할 펌프가 없습니다."}, 400)
        port = body.get("port")
        if isinstance(port, str) and port.strip().lower() == "o":
            drain: "int | str" = "o"
        else:
            try:
                drain = int(port)
            except (TypeError, ValueError):
                return ({"ok": False,
                         "error": "배출구를 선택하세요 — 홈 복귀는 실린 액체를 밸브가 향한 포트로 밀어냅니다"
                                  "(분배밸브=포트 번호 · 3-way=배출측)."}, 400)
            if not 1 <= drain <= 12:
                return ({"ok": False, "error": f"배출구 포트는 1~12 이어야 합니다: {drain}"}, 400)
        t0 = time.monotonic()
        if drain == "o":
            # 방향형 — 회전이 estop 래치(폴 즉시 이탈)에 막히지 않게 복구 의도로 먼저 해제
            #   (initialize_polled 도 스스로 해제한다 — 순서만 앞당김).
            a.clear_estop()
            for ad in addrs:
                rv = a.rotate_valve(ad, "o")
                if rv.raw_error_code != 0:
                    return ({**result_json(rv.raw_error_code,
                                           f"배출측(OR) 선회전 실패 — 초기화 중단: {rv.detail or ''}")}, 200)
            results = a.initialize_polled(addrs, spec(), ports_by_addr=None)
            if all(code == 0 for code in results.values()):
                for ad in addrs:  # 배출측 재확정 — 실패해도 초기화 성패엔 불영향(warn 만).
                    rv = a.rotate_valve(ad, "o")
                    if rv.raw_error_code != 0:
                        log("warn", f"펌프 {ad} 배출측 재확정 실패(code {rv.raw_error_code}) — 밸브 자세만 미보장")
        else:
            # 분배밸브 — Z{힘},{p},{p}: 홈 스트로크 내내 배출구 p 를 향하고, 주차도 I{p}.
            results = a.initialize_polled(addrs, spec(),
                                          ports_by_addr={ad: (drain, drain) for ad in addrs})
        elapsed = round(time.monotonic() - t0, 1)
        per = {str(addr): result_json(code) for addr, code in results.items()}
        ok = all(code == 0 for code in results.values())
        # 복구 경로 — **성공했을 때만** 툴 래치를 열고(fail-open 방지·P2-a) 첫 정비 게이트도 연다.
        if ok:
            STATE["estop"] = False
            STATE["initialized_after_connect"] = True
        return ({"ok": ok, "elapsedS": elapsed, "results": per}, 200)
    finally:
        release(lock)


def valve_action(body: dict) -> "tuple[dict, int]":
    """기주 솔레노이드 밸브 — ON(10s 자동닫힘)/OFF/N초 열기. 상호배타·자동닫힘은 pi 어댑터 규약."""
    if STATE["mode"] != "flavor":
        return ({"ok": False, "error": "밸브 제어는 식향 모드 전용입니다."}, 400)
    v = valve_adapter(STATE, log)
    if v is None:
        return ({"ok": False, "error": f"밸브(GPIO)를 쓸 수 없습니다 — 라즈베리파이에서만 지원. ({STATE['valve_err']})"}, 400)
    action = body.get("action")  # "latch_on" | "off" | "open_for"
    base = body.get("base")
    if base not in VALVE_BASES_LABEL:
        return ({"ok": False, "error": "base 는 sour|normal 중 하나여야 합니다."}, 400)
    # estop 게이트(재검증 P1-c) — 서버는 estop 활성 시 **모든** 정비 발행을 409 로 거부한다
    #   (commands route `estop_active`) — 밸브도 예외가 아니다. 닫기(off)만은 항상 허용(안전 방향).
    if action != "off" and (STATE["estop"] or STATE["estop_in_progress"]):
        return ({"ok": False, "error": "긴급 정지 래치 상태 — 밸브 개방이 잠겼습니다. [초기화]로 복구하세요."}, 409)
    label = VALVE_BASES_LABEL[base]
    if action == "off":
        v.close_all()
        STATE["valve_open_until"] = {"sour": 0.0, "normal": 0.0}
        return ({"ok": True, "note": f"{label} 밸브를 닫았습니다."}, 200)
    if action == "latch_on":
        res = v.open_latch(base, float(VALVE_LATCH_SEC))
        if res.ok:
            # 상호배타 미러(pi L3 동일) — 한쪽 ON 은 다른 쪽을 닫는다.
            STATE["valve_open_until"] = {"sour": 0.0, "normal": 0.0, base: time.time() + VALVE_LATCH_SEC}
        return ({"ok": res.ok, "note": f"{label} 밸브를 열었습니다 ({VALVE_LATCH_SEC}초 뒤 자동 닫힘)." if res.ok else f"밸브 개방 실패: {res.detail}"}, 200)
    if action == "open_for":
        sec = body.get("sec", 3)
        if isinstance(sec, bool) or not isinstance(sec, (int, float)):
            sec = 3
        sec = max(1, min(10, int(sec)))  # UI 1~10s(admin 확정) — pi max_open_sec 15s 는 안전천장.
        res = v.dispense_volume(base, 0.0, open_sec=float(sec))  # 블로킹 — pi finally 닫힘.
        STATE["valve_open_until"] = {"sour": 0.0, "normal": 0.0}
        return ({"ok": res.ok, "note": f"{label} 밸브를 {sec}초 열었다 닫았습니다." if res.ok else f"밸브 개방 실패: {res.detail}"}, 200)
    return ({"ok": False, "error": "action 은 latch_on|off|open_for 중 하나여야 합니다."}, 400)


