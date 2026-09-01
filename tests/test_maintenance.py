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


def _connected(stub: StubAdapter, pumps=(1, 2)):
    st.STATE.update(adapter=stub, pumps=list(pumps),
                    capacity_confirmed=True, initialized_after_connect=False,
                    estop=True, estop_in_progress=False, busy=None)


class TestWeakInit:
    def test_success_opens_both_gates_and_passes_per_pump_ports(self):
        stub = StubAdapter()
        _connected(stub)
        payload, status = mt.weak_init()
        assert status == 200 and payload["ok"] is True
        assert st.STATE["estop"] is False  # estop 복구 경로.
        assert st.STATE["initialized_after_connect"] is True  # 첫 정비 게이트 개방.
        pba = stub.init_calls[0]["ports_by_addr"]
        assert set(pba) == {1, 2} and all(len(v) == 2 for v in pba.values())  # (air, output) 펌프별.

    def test_partial_failure_keeps_gates_closed(self):
        # fail-open 방지(P2-a) — 한 펌프라도 실패면 estop 래치·첫 정비 게이트를 열지 않는다.
        stub = StubAdapter(init_results={1: 0, 2: 9})
        _connected(stub)
        payload, status = mt.weak_init()
        assert status == 200 and payload["ok"] is False
        assert st.STATE["estop"] is True
        assert st.STATE["initialized_after_connect"] is False


class TestCleanAbort:
    def test_estop_mid_clean_aborts_remaining_rounds(self):
        stub = StubAdapter()
        _connected(stub)

        real = stub.dispense

        def dispense_then_estop(cmd):
            r = real(cmd)
            st.STATE["estop"] = True  # 1회차 도중 긴급 정지 — 남은 회차가 돌면 안 된다.
            return r

        stub.dispense = dispense_then_estop
        payload, status = mt.clean({"alcoholCount": 3, "purgeCount": 3})
        assert status == 200
        assert payload["aborted"] is True and payload["ok"] is False
        assert len(payload["rounds"]) == 1  # 정지 시점 이후 회차 없음.
