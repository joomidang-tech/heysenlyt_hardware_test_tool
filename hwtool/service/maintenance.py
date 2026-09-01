"""정비 유스케이스 — estop·초기화·세척·플런저·진단 필링·건강 점검·밸브 (전부 (payload, status) 반환).

admin(heysenlyt-web) 점검·유지보수 화면의 서버측 조립을 로컬에서 미러한다. 펌프 제어의 실체는
어댑터(senlyt_pi EnginePort 구현체) — 여기는 언제·몇 번·어떤 포트로 부를지의 오케스트레이션만.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from senlyt_pi.adapters.sy01b_engine_adapter import Sy01bEngineAdapter
from senlyt_pi.pipeline.pump_health import scan_addresses
from senlyt_pi.ports.engine_port import (
    OP_PLUNGER_FULL,
    OP_PLUNGER_HOME,
    EngineDispenseCommand,
    EngineOpCommand,
)
from senlyt_pi.core.pump_guard import is_volume_within_gate

from ..adapters.valve import valve_adapter
from ..core.catalog import (
    ASPIRATE_SPEED_DEFAULT_HZ,
    CLEAN_ALCOHOL_DEFAULT,
    CLEAN_PURGE_DEFAULT,
    DIAG_ASPIRATE_DEFAULT_HZ,
    DISPENSE_SPEED_DEFAULT_HZ,
    MAX_CLEAN_COUNT,
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
    role_port,
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
            cls = current_engine_cls() or Sy01bEngineAdapter
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
            "note": "TR 발송 + estop 래치 — 복구는 [약한 초기화] 또는 [세척]"
            if ok
            else "⚠️ 전 펌프 무응답 — 정지 도달을 확인하지 못했습니다. 24V 전원을 직접 차단하세요.",
        }
    finally:
        STATE["estop_in_progress"] = False


def dispense_once(
    pump: int,
    in_port: int,
    volume_ul: float,
    *,
    asp_hz: int,
    disp_hz: int,
    slope: int,
) -> dict:
    """syringe 스텝 1회 — 서버 조립과 동일 형태(I{in}→A{steps}→O{out}→A0·명시 속도).

    배출 구멍 = **그 펌프의** output 역할 포트(포트 매핑 파생 — outputPortOf 미러).
    """
    sp = spec()
    cmd = EngineDispenseCommand(
        pump_addr=pump,
        volume_ul=float(volume_ul),
        steps=sp.steps_for_volume_ul(float(volume_ul)),
        spec=sp,
        in_port=in_port,
        out_port=role_port(pump, "output"),
        aspirate_speed_hz=asp_hz,
        dispense_speed_hz=disp_hz,
        slope=slope,
    )
    res = STATE["adapter"].dispense(cmd)
    return {**result_json(res.raw_error_code, res.detail), "steps": cmd.steps}


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
    """시린지 흡입·배출 — admin ▼전량 흡입/▲전량 배출 (run_op + 밸브 회전 wire.ts 파생 미러)."""
    a, err = require_adapter()
    if err:
        return ({"ok": False, "error": err[0]}, err[1])
    gate = motion_gate()
    if gate:
        return ({"ok": False, "error": gate[0]}, gate[1])
    op = body.get("op")  # "plungerFull" | "plungerHome"
    pump = body.get("pump")
    if op not in ("plungerFull", "plungerHome"):
        return ({"ok": False, "error": "op 는 plungerFull|plungerHome 중 하나여야 합니다."}, 400)
    if pump not in STATE["pumps"]:
        return ({"ok": False, "error": f"연결된 펌프가 아닙니다: {pump}"}, 400)
    # wire.ts:1232~ 파생 미러 — plungerFull=**그 펌프의** air 회전 · plungerHome=output 회전
    #   (admin 처럼 pumpPorts 레이아웃 우선·없으면 모드 기본 폴백).
    valve_port = role_port(pump, "air" if op == "plungerFull" else "output")
    cmd = EngineOpCommand(
        pump_addr=pump,
        op=OP_PLUNGER_FULL if op == "plungerFull" else OP_PLUNGER_HOME,
        spec=spec(),
        valve_port=valve_port,
    )
    label = f"{pump_label(pump)} {'전량 흡입' if op == 'plungerFull' else '전량 배출'}"
    lock = busy_guard(label)
    if lock is None:
        return ({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}, 409)
    try:
        res = a.run_op(cmd)
        return (result_json(res.raw_error_code, res.detail), 200)
    finally:
        release(lock)


def weak_init() -> "tuple[dict, int]":
    """약한 초기화 — 전 펌프 동시 홈(admin forceInitAll 미러 · estop 복구 경로).

    admin 은 estop 신호를 먼저 해제하고 전 펌프 initialize 스텝(stage:0)을 발행하며,
    pi 는 이를 합쳐 `initialize_polled`(주소지정 발사 + Bit5 폴 조기완료)로 실행한다 —
    여기서도 같은 함수를 같은 인자(air/output 포트)로 부른다.
    """
    a, err = require_adapter()
    if err:
        return ({"ok": False, "error": err[0]}, err[1])
    gate = motion_gate(is_recovery=True)
    if gate:
        return ({"ok": False, "error": gate[0]}, gate[1])
    lock = busy_guard("약한 초기화")
    if lock is None:
        return ({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}, 409)
    try:
        addrs = list(STATE["pumps"])
        if not addrs:
            return ({"ok": False, "error": "초기화할 펌프가 없습니다."}, 400)
        t0 = time.monotonic()
        # 펌프별 포트(ports_by_addr) — 데몬 시퀀서가 넘기는 것과 동일 인자(재검증 P2-2 해소).
        results = a.initialize_polled(
            addrs, spec(),
            ports_by_addr={p: (role_port(p, "air"), role_port(p, "output")) for p in addrs},
        )
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


def clean(body: dict) -> "tuple[dict, int]":
    """🧼 세척 — admin `cleaningSteps` 와 동일 시퀀스를 로컬에서 실행.

    시퀀스(maintenanceSteps.ts 미러):
      phase 0. 약한 초기화(전 펌프) — admin 세척 모달 "펌프를 초기화하고 세척 사이클을 실행"
      phase 1. 알코올 펌핑 — 회차마다 전 펌프 **동시**(stage 병렬 = ThreadPool·L2 시분할 버스),
               각 펌프 자기 세척액 포트에서 전량(1 스트로크) 흡입 → 배출 × alcoholCount(기본 2)
      phase 2. 에어 퍼지(**식향 한정** — v1.1.0 패리티) — air 포트 전량 흡입→배출 × purgeCount(기본 3)

    estop 복구 경로("복구는 [약한 초기화 & 세척]")라 래치 중에도 허용, 성공 시 래치 해제.
    """
    a, err = require_adapter()
    if err:
        return ({"ok": False, "error": err[0]}, err[1])
    gate = motion_gate(is_recovery=True)
    if gate:
        return ({"ok": False, "error": gate[0]}, gate[1])
    alcohol = body.get("alcoholCount", CLEAN_ALCOHOL_DEFAULT)
    purge = body.get("purgeCount", CLEAN_PURGE_DEFAULT)
    if isinstance(alcohol, bool) or not isinstance(alcohol, (int, float)):
        alcohol = CLEAN_ALCOHOL_DEFAULT
    if isinstance(purge, bool) or not isinstance(purge, (int, float)):
        purge = CLEAN_PURGE_DEFAULT
    alcohol = max(1, min(MAX_CLEAN_COUNT, int(alcohol)))  # cleaningSteps clamp 미러(1~10).
    purge = max(0, min(MAX_CLEAN_COUNT, int(purge)))  # 0 = 세척만(퍼지 생략) 허용 — admin 주석 동일.
    lock = busy_guard("세척")
    if lock is None:
        return ({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}, 409)
    try:
        addrs = list(STATE["pumps"])
        if not addrs:
            return ({"ok": False, "error": "세척할 펌프가 없습니다."}, 400)
        sp = spec()
        # 1스트로크 부피 — admin `cleaningSteps` 는 `defaultSyringeCapacityMl(mode)*1000` = **고정
        #   500µL**(양 모드 공통 기본 용량)이다(재검증 P2-g — 설정 용량 전량으로 하면 1.25mL 기기
        #   에서 2.5배 과다). 미러 = 500µL 고정, 단 더 작은 시린지에선 게이트 상한으로 클램프.
        max_ul = min(500.0, sp.max_volume_ul)
        t0 = time.monotonic()
        # phase 0 — 초기화(estop 래치도 어댑터가 clear) — 펌프별 포트.
        init_results = a.initialize_polled(
            addrs, sp,
            ports_by_addr={p: (role_port(p, "air"), role_port(p, "output")) for p in addrs},
        )
        report: dict = {"initialize": {str(p): result_json(c) for p, c in init_results.items()}, "rounds": []}
        ok_pumps = [p for p in addrs if init_results.get(p) == 0]
        if not ok_pumps:
            return ({"ok": False, "error": "초기화에 실패해 세척을 중단합니다.", **report}, 200)
        if all(c == 0 for c in init_results.values()):
            STATE["estop"] = False  # 복구 성공 — 툴 래치 해제 + 첫 정비 게이트 개방.
            STATE["initialized_after_connect"] = True

        def run_round(kind: str, role: str) -> dict:
            """한 회차 — 전 펌프 동시(pi stage 병렬과 동일), 흡입 포트는 **펌프별 역할 포트**
            (세척액 = 그 펌프 매핑의 cleaning/alcohol — 서버 cleaningPortOf 해석 미러)."""
            with ThreadPoolExecutor(max_workers=len(ok_pumps)) as ex:
                futs = {
                    p: ex.submit(
                        dispense_once,
                        p,
                        role_port(p, role),
                        max_ul,
                        asp_hz=ASPIRATE_SPEED_DEFAULT_HZ,
                        disp_hz=DISPENSE_SPEED_DEFAULT_HZ,
                        slope=SLOPE_DEFAULT,
                    )
                    for p in ok_pumps
                }
                return {"kind": kind, "results": {str(p): f.result() for p, f in futs.items()}}

        aborted = False
        for _ in range(alcohol):
            if STATE["estop"] or STATE["estop_in_progress"]:
                aborted = True
                break
            report["rounds"].append(run_round("cleaning", "cleaning"))
        if STATE["mode"] == "flavor" and not aborted:  # 퍼지 = v1.1.0 flavor 전용(패리티).
            for _ in range(purge):
                if STATE["estop"] or STATE["estop_in_progress"]:
                    aborted = True
                    break
                report["rounds"].append(run_round("air", "air"))
        all_ok = (not aborted) and all(
            r2["ok"] for rd in report["rounds"] for r2 in rd["results"].values()
        )
        report.update(
            {
                "ok": all_ok,
                "aborted": aborted,
                "elapsedS": round(time.monotonic() - t0, 1),
                "alcoholCount": alcohol,
                "purgeCount": purge if STATE["mode"] == "flavor" else 0,
            }
        )
        return (report, 200)
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
        return ({"ok": False, "error": "긴급 정지 래치 상태 — 밸브 개방이 잠겼습니다. [약한 초기화] 또는 [세척]으로 복구하세요."}, 409)
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


def _run_filling(targets: list[dict], volume_ul: float, asp: int, disp: int, lock) -> None:
    """필링 실행 스레드 — (펌프, 포트) 순서 직렬, 진행을 STATE['filling'] 에 실시간 기록.

    admin 은 한 봉투(직렬 stage)로 발행하고 하트비트 편승 jobProgress(10~15s 해상도)로 현재
    포트를 표시한다 — 이 툴은 로컬이라 스텝 완료 즉시 갱신된다(같은 개념·더 촘촘한 해상도).
    """
    try:
        fill = STATE["filling"]
        for i, t in enumerate(targets):
            if STATE["estop"] or STATE["estop_in_progress"]:
                fill["outcome"] = "aborted"
                break
            fill["current"] = i
            r = dispense_once(
                t["pump"], t["port"], volume_ul, asp_hz=asp, disp_hz=disp, slope=SLOPE_DEFAULT
            )
            fill["results"].append({**t, **r})
        else:
            # 마지막 스텝 직후 estop 창(리뷰 P2-7) — 완료 직전 정지가 걸렸으면 done 으로 위장하지 않는다.
            if STATE["estop"] or STATE["estop_in_progress"]:
                fill["outcome"] = "aborted"
            else:
                fill["outcome"] = "done" if all(r["ok"] for r in fill["results"]) else "failed"
    except Exception as e:  # noqa: BLE001 — 스레드라 예외를 상태로 남긴다(조용한 실종 방지).
        fill["outcome"] = "failed"
        fill["error"] = str(e)[:200]
    finally:
        fill["active"] = False
        fill["current"] = None
        release(lock)


def start_filling(body: dict) -> "tuple[dict, int]":
    """향료 필링 시작 — admin `runFilling` 미러(선택 타일 1개 = 개별 실행 · 전체 = 순차 필링).

    body.targets = [{pump, port, label}] — 타일 그대로(선택 포트/순차/재필링 모두 이 한 경로,
    admin 과 동일). 비동기 시작 후 진행은 `/api/state` 의 filling 으로 폴링(순차 패널 미러).
    """
    a, err = require_adapter()
    if err:
        return ({"ok": False, "error": err[0]}, err[1])
    del a  # 스레드가 STATE["adapter"] 를 직접 쓴다 — 존재 확인만.
    gate = motion_gate()
    if gate:
        return ({"ok": False, "error": gate[0]}, gate[1])
    raw_targets = body.get("targets")
    volume_ul = body.get("volumeUl")
    if not isinstance(raw_targets, list) or not raw_targets:
        return ({"ok": False, "error": "targets 가 비었습니다 — 포트 타일을 선택하세요."}, 400)
    targets: list[dict] = []
    for t in raw_targets:
        pump, port = t.get("pump"), t.get("port")
        if pump not in STATE["pumps"] or not valid_port(port):
            return ({"ok": False, "error": f"잘못된 대상: 펌프 {pump} 포트 {port}"}, 400)
        if port == role_port(pump, "output"):
            return ({"ok": False, "error": f"P{pump}의 배출(output) 포트({port})는 흡입 대상이 될 수 없습니다."}, 400)
        targets.append({"pump": pump, "port": port,
                        "label": str(t.get("label") or f"P{pump}·{port}")[:40],
                        "pumpLabel": pump_label(pump)})
    # (펌프, 포트) 정렬 — admin runFilling 의 결정론 순서(P1 전부 → P2 전부) 미러.
    targets.sort(key=lambda t: (t["pump"], t["port"]))
    if isinstance(volume_ul, bool) or not isinstance(volume_ul, (int, float)):
        return ({"ok": False, "error": "volumeUl 은 숫자여야 합니다."}, 400)
    sp = spec()
    # 흡입량 = admin 슬라이더 범위 [용량/5, 용량] 클램프(표시·발행 동일 규약).
    volume_ul = min(sp.max_volume_ul, max(sp.max_volume_ul / 5, float(volume_ul)))
    # 클램프 후 재검증 — assert 금지(python -O 에서 제거·재검증 P2-n). 도달 시 명시 400.
    if not is_volume_within_gate(float(volume_ul), sp):
        return ({"ok": False, "error": f"부피 게이트 위반: 0 < {volume_ul}µL ≤ {sp.max_volume_ul:.0f}µL"}, 400)
    asp = clamp_setting("aspirateSpeedHz", body.get("aspirateSpeedHz"), DIAG_ASPIRATE_DEFAULT_HZ)
    disp = clamp_setting("dispenseSpeedHz", body.get("dispenseSpeedHz"), DISPENSE_SPEED_DEFAULT_HZ)
    lock = busy_guard(f"향료 필링 ({len(targets)}포트)")
    if lock is None:
        return ({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}, 409)
    STATE["filling"] = {
        "active": True, "current": 0, "targets": targets, "results": [], "outcome": None,
        "error": None,  # 키를 미리 둔다 — 직렬화 중 새 키 추가는 dict 크기 변경 RuntimeError(P2-8).
        "volumeUl": volume_ul, "aspirateSpeedHz": asp, "dispenseSpeedHz": disp,
    }
    try:
        th = threading.Thread(
            target=_run_filling, args=(targets, float(volume_ul), asp, disp, lock), daemon=True
        )
        th.start()
    except Exception as e:  # noqa: BLE001 — 스레드 기동 실패 시 락 영구 잠김 방지(리뷰 P2-2).
        STATE["filling"] = None
        release(lock)
        return ({"ok": False, "error": f"필링 시작 실패: {e}"}, 500)
    return ({"ok": True, "started": True, "count": len(targets)}, 200)
