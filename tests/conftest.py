"""테스트 격리(검증 P2-8) — 전역 STATE 스냅샷/복원 + OP_LOCK 강제 해제.

단일 전역 STATE 구조라, 어느 테스트가 무엇을 만지든 다음 테스트가 깨끗한 상태에서 시작해야
파일 단독 실행과 전체 실행의 결과가 같아진다. assert 실패로 락이 잠긴 채 남는 것도 여기서 푼다.
"""

from __future__ import annotations

import copy

import pytest

from hwtool.service import state as st


@pytest.fixture(autouse=True)
def _isolate_global_state():
    snapshot = {k: copy.deepcopy(v) if isinstance(v, (dict, list)) else v
                for k, v in st.STATE.items() if k not in ("adapter", "probe_adapter", "valve")}
    handles = {k: st.STATE[k] for k in ("adapter", "probe_adapter", "valve")}  # 객체는 참조 보존.
    yield
    st.STATE.update(snapshot)
    st.STATE.update(handles)
    if st.OP_LOCK.locked():  # assert 실패로 잠긴 락 — 다음 테스트 연쇄 409 오탐 방지.
        st.OP_LOCK.release()
