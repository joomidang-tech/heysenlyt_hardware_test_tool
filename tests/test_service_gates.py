"""service 계층 게이트 — 전역 STATE 를 픽스처로 조작해 시리얼 없이 검증."""

from __future__ import annotations

import pytest

from hwtool.service import state as st


@pytest.fixture(autouse=True)
def _reset_state():
    """각 테스트 후 게이트 관련 STATE 원복 (단일 전역이므로 테스트 간 오염 방지)."""
    keys = ("estop", "estop_in_progress", "capacity_confirmed", "initialized_after_connect",
            "busy", "adapter")
    before = {k: st.STATE[k] for k in keys}
    yield
    st.STATE.update(before)


class TestMotionGate:
    def test_blocks_until_capacity_confirmed(self):
        st.STATE.update(estop=False, estop_in_progress=False, capacity_confirmed=False)
        msg, code = st.motion_gate()
        assert code == 400 and "용량" in msg

    def test_blocks_before_first_init_but_recovery_passes(self):
        st.STATE.update(estop=False, estop_in_progress=False,
                        capacity_confirmed=True, initialized_after_connect=False)
        msg, code = st.motion_gate()
        assert code == 409 and "약한 초기화" in msg
        assert st.motion_gate(is_recovery=True) is None  # 복구 경로는 통과.

    def test_estop_latch_blocks_all_but_recovery(self):
        st.STATE.update(estop=True, estop_in_progress=False,
                        capacity_confirmed=True, initialized_after_connect=True)
        assert st.motion_gate()[1] == 409
        assert st.motion_gate(is_recovery=True) is None

    def test_estop_in_progress_blocks_even_recovery(self):
        st.STATE.update(estop_in_progress=True)
        assert st.motion_gate(is_recovery=True)[1] == 409

    def test_all_open(self):
        st.STATE.update(estop=False, estop_in_progress=False,
                        capacity_confirmed=True, initialized_after_connect=True)
        assert st.motion_gate() is None


class TestBusyGuard:
    def test_non_blocking_and_release(self):
        lock = st.busy_guard("테스트 작업")
        assert lock is not None and st.STATE["busy"] == "테스트 작업"
        assert st.busy_guard("겹침") is None  # non-blocking 재획득 실패 = 409 재료.
        st.release(lock)
        assert st.STATE["busy"] is None


class TestRequireAdapter:
    def test_absent_adapter_is_400(self):
        st.STATE["adapter"] = None
        a, err = st.require_adapter()
        assert a is None and err[1] == 400
