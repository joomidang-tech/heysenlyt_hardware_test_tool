"""service 계층 게이트 — 전역 STATE 를 픽스처로 조작해 시리얼 없이 검증."""

from __future__ import annotations

import pytest

from hwtool.service import state as st


@pytest.fixture(autouse=True)
def _reset_state():
    """각 테스트 후 게이트 관련 STATE 원복 (단일 전역이므로 테스트 간 오염 방지)."""
    keys = ("estop", "estop_in_progress", "initialized_after_connect",
            "busy", "adapter")
    before = {k: st.STATE[k] for k in keys}
    yield
    st.STATE.update(before)


class TestMotionGate:
    def test_blocks_before_first_init_but_recovery_passes(self):
        st.STATE.update(estop=False, estop_in_progress=False,
                        initialized_after_connect=False)
        msg, code = st.motion_gate()
        assert code == 409 and "초기화" in msg
        assert st.motion_gate(is_recovery=True) is None  # 복구 경로는 통과.

    def test_estop_latch_blocks_all_but_recovery(self):
        st.STATE.update(estop=True, estop_in_progress=False,
                        initialized_after_connect=True)
        assert st.motion_gate()[1] == 409
        assert st.motion_gate(is_recovery=True) is None

    def test_estop_in_progress_blocks_even_recovery(self):
        st.STATE.update(estop_in_progress=True)
        assert st.motion_gate(is_recovery=True)[1] == 409

    def test_all_open(self):
        st.STATE.update(estop=False, estop_in_progress=False,
                        initialized_after_connect=True)
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

class TestConnEpochAbort:
    """연결 중 센소리움 버전 변경 = 진행 중 연결 중단(2026-09-03)."""

    def test_version_change_bumps_epoch_and_signals_probe(self):
        from hwtool.service import settings as se

        class _Probe:
            stopped = False
            def signal_stop(self): self.stopped = True

        pa = _Probe()
        before = st.STATE["conn_epoch"]
        st.STATE.update(connecting=True, probe_adapter=pa, busy=None)
        try:
            other = next(v for v in se.SENSORIUM_VERSIONS if v != st.STATE["sensorium"])
            payload, code = se.apply_settings({"sensorium": other})
            assert code == 200
            assert st.STATE["conn_epoch"] == before + 1
            assert pa.stopped is True  # 진행 중 프로브에 조기 이탈 신호.
        finally:
            st.STATE.update(connecting=False, probe_adapter=None,
                            sensorium=list(se.SENSORIUM_VERSIONS)[0])
            from hwtool.core.sensorium import SENSORIUM_VERSIONS as SV
            v = SV[st.STATE["sensorium"]]
            st.STATE.update(mode=v["family"], capacity_ml=v["capacityMl"])

    def test_connect_core_aborts_on_epoch_change(self, monkeypatch):
        from hwtool.service import connection as cn

        def fake_probe(port):
            st.STATE["conn_epoch"] += 1  # 프로브 도중 버전 변경 시뮬레이션.
            return [1]

        monkeypatch.setattr(cn, "probe_port_for_pumps", fake_probe)
        monkeypatch.setattr(cn, "list_candidate_ports", lambda: ["/dev/fake0"])
        monkeypatch.setattr(cn, "_userspace_factory_or_none", lambda: None)
        payload, code = cn.connect_core("")
        assert code == 409 and "센소리움 버전이 변경" in payload["error"]
        assert st.STATE["adapter"] is None  # 구 방언 결과로 결선되지 않았다.



class TestModelFingerprintConnectGate:
    """R9 — 연결단 지문 게이트(409) + override 탈출구. 어댑터는 스텁으로 주입."""

    def _run_connect(self, monkeypatch, *, fp, model_setting, override=False):
        from hwtool.service import connection as cn

        class _StubAdapter:
            def __init__(self, **kw): pass
            def probe(self, addr): return addr == 1
            def model_fingerprint(self, addr): return fp
            def close(self): pass
            def signal_stop(self): pass

        monkeypatch.setattr(cn, "list_candidate_ports", lambda: ["/dev/fake0"])
        monkeypatch.setattr(cn, "_userspace_factory_or_none", lambda: None)
        monkeypatch.setattr(cn, "current_engine_cls", lambda: _StubAdapter)
        monkeypatch.setattr(cn, "discover_pumps", lambda probe, addrs: [1])
        st.STATE.update(adapter=None, pumps=[], port=None, allow_fp_mismatch=override)
        # 설정 모델 강제 — version() 몽키패치
        monkeypatch.setattr(cn, "version", lambda: {"pumpModel": model_setting, "pumps": [1, 2]})
        try:
            return cn.connect_core("")
        finally:
            a = st.STATE.get("adapter")
            st.STATE.update(adapter=None, pumps=[], port=None, allow_fp_mismatch=False)
            if a is not None:
                a.close()

    def test_runze_setting_with_tecan_fingerprint_rejected(self, monkeypatch):
        payload, code = self._run_connect(monkeypatch, fp="30064809 C", model_setting="sy01b")
        assert code == 409 and "XCalibur" in payload["error"]
        assert st.STATE["adapter"] is None  # 정리까지(어댑터 폐기).

    def test_override_allows_connection(self, monkeypatch):
        payload, code = self._run_connect(
            monkeypatch, fp="30064809 C", model_setting="sy01b", override=True)
        assert code == 200 and payload["ok"] is True  # 탈출구 — 어댑터 -1003 이 최후 방어.

    def test_tecan_setting_with_tecan_fingerprint_passes(self, monkeypatch):
        # M5 그물(테스트검증) — 정상 조합(설정 tecan + 실물 tecan)은 게이트가 발동하면 안 된다.
        #   게이트 조건(model != tecan_xcalibur)을 지우면 정상 XCalibur 운영자가 409 로 완전
        #   잠금되는데, 이전 그물은 sy01b 설정만 다뤄 이 변이가 살아남았다.
        payload, code = self._run_connect(
            monkeypatch, fp="30064809 C", model_setting="tecan_xcalibur")
        assert code == 200 and payload["ok"] is True

    def test_unknown_fingerprint_fail_open(self, monkeypatch):
        payload, code = self._run_connect(monkeypatch, fp=None, model_setting="sy01b")
        assert code == 200 and payload["ok"] is True
