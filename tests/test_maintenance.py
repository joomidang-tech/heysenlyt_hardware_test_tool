"""maintenance 유스케이스 — 어댑터 스텁 주입으로 시리얼 없이 물리 불변식 검증 (검증 처방 반영).

스텁은 EnginePort 중 maintenance 가 실제로 쓰는 표면 4개만 구현한다 — pi 의 FakeEnginePort 는
initialize_polled/health_probe 가 없어 그대로 못 쓴다(검증 리포트 실측).
"""

from __future__ import annotations

from senlyt_pi.ports.engine_port import EngineResult

from hwtool.service import maintenance as mt
from hwtool.service import state as st


class StubAdapter:
    """EnginePort 표면 스텁 — 호출 기록 + 스크립트된 결과."""

    def __init__(self, *, init_results=None, dispense_code=0):
        self.init_calls: list[dict] = []
        self.dispense_cmds: list = []
        self.run_op_cmds: list = []
        self._init_results = init_results
        self._dispense_code = dispense_code

    def initialize_polled(self, addrs, spec, in_port=None, out_port=None, ports_by_addr=None):
        self.init_calls.append({"addrs": list(addrs), "ports_by_addr": ports_by_addr})
        return self._init_results if self._init_results is not None else {a: 0 for a in addrs}

    def dispense(self, cmd):
        self.dispense_cmds.append(cmd)
        return EngineResult(raw_error_code=self._dispense_code)

    def run_op(self, cmd):
        self.run_op_cmds.append(cmd)
        return EngineResult(raw_error_code=0)

    def health_probe(self, addr):
        return "ok"

    def rotate_valve(self, addr, target, *, out=False, spec=None):
        self.rotate_calls = getattr(self, "rotate_calls", []) + [(addr, target, out)]
        self.rotate_specs = getattr(self, "rotate_specs", []) + [spec]
        return EngineResult(raw_error_code=0)

    def plunger_to(self, addr, steps, spec, *, top_speed_hz=None, slope=None):
        self.plunger_to_calls = getattr(self, "plunger_to_calls", []) + [
            {"addr": addr, "steps": steps, "top_speed_hz": top_speed_hz, "slope": slope}]
        return EngineResult(raw_error_code=0)

    def plunger_position(self, addr):
        return 1200

    def clear_estop(self):
        self.estop_cleared = True

    def aspirate(self, cmd):
        self.aspirate_cmds = getattr(self, "aspirate_cmds", []) + [cmd]
        return EngineResult(raw_error_code=self._dispense_code)


def _connected(stub: StubAdapter, pumps=(1, 2)):
    st.STATE.update(adapter=stub, pumps=list(pumps),
                    initialized_after_connect=False,
                    estop=True, estop_in_progress=False, busy=None)


class TestInitializePumps:
    """초기화 정의(2026-09-03 사용자 확정) — **배출구를 향한 채 진행하는 기준 리셋**.

    홈 복귀 = 플런저를 끝까지 밀어냄이라 실린 액체가 전량 배출된다(피할 수 없음) — 통제
    가능한 건 방향뿐이므로 배출구 선택이 **필수**다(미선택 400 · 암묵 동작 금지 원칙).
    """

    def test_port_is_mandatory(self):
        stub = StubAdapter()
        _connected(stub)
        payload, status = mt.init_pumps({})
        assert status == 400 and "배출구" in payload["error"]
        assert stub.init_calls == []  # 프레임 0건.

    def test_distribution_port_rides_z_operands_and_park(self):
        # 분배밸브 — Z{힘},{p},{p}: 홈 내내 배출구 p 를 향하고 주차도 I{p}.
        stub = StubAdapter()
        _connected(stub)
        payload, status = mt.init_pumps({"port": 2})
        assert status == 200 and payload["ok"] is True
        assert st.STATE["estop"] is False  # estop 복구 경로.
        assert st.STATE["initialized_after_connect"] is True  # 첫 정비 게이트 개방.
        assert stub.init_calls[0]["ports_by_addr"] == {1: (2, 2), 2: (2, 2)}

    def test_directional_o_rotates_before_and_after(self):
        # 방향형(3-way) — 배출측(OR) 선회전 → 힘-전용 Z → 배출측 재확정(쉴 땐 배출구).
        stub = StubAdapter()
        _connected(stub)
        payload, status = mt.init_pumps({"port": "o"})
        assert status == 200 and payload["ok"] is True
        assert stub.init_calls[0]["ports_by_addr"] is None  # 방향형은 Z 피연산자 없음.
        assert getattr(stub, "estop_cleared", False) is True  # 회전이 래치에 안 막히게 선해제.
        # 펌프(1·2)마다 앞뒤 회전 — 전부 배출측("o").
        assert stub.rotate_calls == [(1, "o", False), (2, "o", False),
                                     (1, "o", False), (2, "o", False)]

    def test_partial_failure_keeps_gates_closed(self):
        # fail-open 방지(P2-a) — 한 펌프라도 실패면 estop 래치·첫 정비 게이트를 열지 않는다.
        stub = StubAdapter(init_results={1: 0, 2: 9})
        _connected(stub)
        payload, status = mt.init_pumps({"port": 2})
        assert status == 200 and payload["ok"] is False
        assert st.STATE["estop"] is True
        assert st.STATE["initialized_after_connect"] is False


class TestPortRoleAliases:
    def test_cleaning_accepts_alcohol_alias(self):
        # 포트 매핑 역할 규칙(세척 기능과 무관하게 유지) — alcohol 은 cleaning 의 별칭.
        from hwtool.core.layout import role_port

        ports = {1: {7: "alcohol"}}
        assert role_port(ports, "fragrance", 1, "cleaning") == 7


class TestDispensePrimitiveNoHiddenAspirate:
    """R9.5 P0 그물 — 배출 op 가 전체 사이클(dispense=_cycle)을 절대 빌리지 않는다.

    어댑터 dispense() 는 배출 전에 풀스트로크 **흡입**(A{full})을 먼저 쏜다 — 위치 readback
    (마지막 0)만 보면 착시 통과라, 여기서는 **호출 표면 자체**를 단언한다:
    배출 = rotate_valve(선택) + plunger_to(steps=0) 만. dispense() 호출 0건.
    """

    def _go(self, body):
        stub = StubAdapter()
        st.STATE.update(adapter=stub, pumps=[1], initialized_after_connect=True,
                        estop=False, estop_in_progress=False, busy=None)
        payload, status = mt.run_plunger(body)
        return stub, payload, status

    def test_dispense_is_rotate_plus_move_only(self):
        # 전량 비우기 = 슬라이더를 실린 양으로(25µL = 스텁 pre 1200 steps) → A0.
        stub, payload, status = self._go({"op": "dispense", "pump": 1, "port": 2, "volumeUl": 25,
                                          "dispHz": 400, "slope": 10})
        assert status == 200 and payload["ok"] is True
        assert stub.dispense_cmds == []  # 전체 사이클 금지(숨은 풀스트로크 흡입).
        assert stub.rotate_calls == [(1, 2, True)]  # 배출측 O{n}(R9.5 P2 — _cycle 배출 회전과 동일 프레임).
        assert stub.plunger_to_calls == [{"addr": 1, "steps": 0, "top_speed_hz": 400, "slope": 10}]

    def test_dispense_partial_uses_slider_volume(self):
        # 배출도 슬라이더 양(2026-09-03 확정) — 10µL(=480 steps)만 하강: 1200 → 720.
        stub, payload, status = self._go({"op": "dispense", "pump": 1, "port": 2, "volumeUl": 10})
        assert status == 200 and payload["ok"] is True
        assert stub.plunger_to_calls[0]["steps"] == 720 and stub.dispense_cmds == []

    def test_dispense_more_than_loaded_rejects_plunger_motion(self):
        # 실린 양(1200 steps=25µL) 초과 요청은 400 + 실린 양 안내. 회전은 허용된다(부피 무이동 —
        # 2026-09-03 재정렬: pre 는 회전 뒤에 읽어야 셋업 재실행 시에도 산 기준점이다).
        stub, payload, status = self._go({"op": "dispense", "pump": 1, "port": 2, "volumeUl": 100})
        assert status == 400 and "실린" in payload["error"] and "25" in payload["error"]
        assert getattr(stub, "plunger_to_calls", []) == []  # 플런저 프레임 0건이 불변식.

    def test_dispense_rotation_receives_spec_for_setup_ordering(self):
        # 회전에 spec 이 실려야 어댑터가 회전 **전** 셋업을 보장한다(lazy Z 순서 역전 봉합).
        stub, payload, status = self._go({"op": "dispense", "pump": 1, "port": 2, "volumeUl": 25})
        assert status == 200 and stub.rotate_specs and stub.rotate_specs[0] is not None

    def test_port_is_mandatory(self):
        # 암묵적 "현 방향 유지" 금지(2026-09-03 사용자 확정) — 미선택 = 400, 모션 프레임 0건.
        for body in ({"op": "dispense", "pump": 1}, {"op": "aspirate", "pump": 1, "volumeUl": 100},
                     {"op": "dispense", "pump": 1, "port": ""}):
            stub, payload, status = self._go(body)
            assert status == 400 and "선택" in payload["error"]
            assert getattr(stub, "plunger_to_calls", []) == [] and getattr(stub, "aspirate_cmds", []) == []

    def test_dispense_direction_o_for_three_way(self):
        # 3-way — 포트 번호 대신 "o"(배출측 OR)로 방향을 명시할 수 있다(R9.5 P2).
        stub, payload, status = self._go({"op": "dispense", "pump": 1, "port": "o", "volumeUl": 25})
        assert status == 200 and payload["ok"] is True
        assert stub.rotate_calls == [(1, "o", False)] and stub.dispense_cmds == []

    def test_aspirate_direction_i_rotates_then_no_in_port(self):
        stub, payload, status = self._go({"op": "aspirate", "pump": 1, "port": "i", "volumeUl": 100})
        assert status == 200 and payload["ok"] is True
        assert stub.rotate_calls == [(1, "i", False)]
        assert stub.aspirate_cmds[0].in_port is None  # 회전은 이미 했다 — I{n} 재발사 금지.

    def test_aspirate_still_uses_cycle_aspirate_only(self):
        stub, payload, status = self._go({"op": "aspirate", "pump": 1, "port": 3, "volumeUl": 100})
        assert status == 200 and payload["ok"] is True
        assert len(stub.aspirate_cmds) == 1 and stub.aspirate_cmds[0].in_port == 3
        assert getattr(stub, "plunger_to_calls", []) == [] and stub.dispense_cmds == []


class TestPlungerContractBoundaries:
    """테스트검증(M7·M8·M9·P3) — run_plunger 입력 계약의 경계를 직접 물어뜯는 그물.

    이 게이트들이 유일 방어선이다(어댑터 aspirate 경로엔 스텝 범위 가드가 없어, 여기가
    뚫리면 과행정 A24000 이 와이어까지 나간다 — 변이 실측). 그래서 표적 테스트로 고정한다.
    """

    def _go(self, body):
        stub = StubAdapter()
        st.STATE.update(adapter=stub, pumps=[1], initialized_after_connect=True,
                        estop=False, estop_in_progress=False, busy=None)
        payload, status = mt.run_plunger(body)
        return stub, payload, status

    def test_op_whitelist_rejects_everything_else(self):
        # M9 — op 화이트리스트를 지우면 오타가 "전량 배출"로 흘렀다.
        for bad in (None, "", "plungerFull", "ASPIRATE", ["aspirate"], 1):
            stub, payload, status = self._go({"op": bad, "pump": 1, "port": 1, "volumeUl": 100})
            assert status == 400, f"op={bad!r} 가 통과"
            assert getattr(stub, "plunger_to_calls", []) == [] and stub.dispense_cmds == []

    def test_volume_gate_blocks_overstroke_and_negative(self):
        # M8 — 용량 게이트를 지우면 500µL(=용량 2배) → steps 24000 과행정이 와이어로 나갔다.
        for bad in (500, -1, 0, "bogus"):
            stub, payload, status = self._go({"op": "aspirate", "pump": 1, "port": 1, "volumeUl": bad})
            assert status == 400, f"volumeUl={bad!r} 가 통과"
            assert getattr(stub, "aspirate_cmds", []) == []

    def test_volume_below_one_step_rejected(self):
        # P3 — 1 step 미만은 조용한 no-op 인데 200 성공으로 보였다 → 400 으로 정직하게.
        stub, payload, status = self._go({"op": "aspirate", "pump": 1, "port": 1, "volumeUl": 0.001})
        assert status == 400 and "1 step" in payload["error"]

    def test_port_range_1_to_12(self):
        # M7 — 포트 상한을 255 로 풀어도 아무도 안 죽었다. 상한 12 = 양 매뉴얼 공통 최대
        #   (XCalibur Table 3-5 · SY-01B T-03~T-12 — 15포트는 어느 매뉴얼에도 없음).
        for bad in (0, 13, 16, -1, 255, "abc"):
            stub, payload, status = self._go({"op": "aspirate", "pump": 1, "port": bad, "volumeUl": 100})
            assert status == 400, f"port={bad!r} 가 통과"

    def test_bool_pump_rejected(self):
        # P3 — JSON true 가 True==1 로 펌프 1 을 은근히 지정하는 타입 혼동.
        stub, payload, status = self._go({"op": "aspirate", "pump": True, "port": 1, "volumeUl": 100})
        assert status == 400


class TestValveInfoParser:
    """?76 밸브 구성 파서 — "활용-아니면-무시"(2026-09-03). 보수적: 아는 패턴만, 나머진 None."""

    def test_known_patterns(self):
        from hwtool.core.catalog import valve_info_from_config as v

        assert v("9600|100K|484|3-way|AUTO") == {"kind": "directional", "ports": None, "label": "3-way"}
        assert v("9600|100K|484|12-port distribution valve|AUTO") == {
            "kind": "distribution", "ports": 12, "label": "12-port distribution valve"}
        assert v("6-port")["ports"] == 6

    def test_unknown_and_out_of_range_ignored(self):
        from hwtool.core.catalog import valve_info_from_config as v

        assert v(None) is None and v("") is None
        assert v("garbage|fields|here") is None
        assert v("99-port monster") is None  # 매뉴얼 밖(>12) — 무시(폴백).
