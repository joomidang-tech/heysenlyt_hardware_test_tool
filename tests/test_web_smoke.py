"""web 계층 스모크 — Flask test client 로 배선(라우트→service)을 시리얼 없이 검증."""

from __future__ import annotations

import pytest

from hwtool.service import state as st
from hwtool.web import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


class TestStateAndSettings:
    def test_state_exposes_pump_model_contract(self, client):
        s = client.get("/api/state").get_json()
        assert s["pumpModel"] in ("sy01b", "tecan_xcalibur")
        assert isinstance(s["pumpModelAvailable"], bool)
        assert all("modelAvailable" in v for v in s["versions"])

    def test_unknown_sensorium_rejected(self, client):
        r = client.post("/api/settings", json={"sensorium": "no-such-version"})
        assert r.status_code == 400

    def test_invalid_capacity_rejected(self, client):
        r = client.post("/api/settings", json={"capacityMl": 0.33})
        assert r.status_code == 400


class TestSettingsWhileDisconnected:
    def test_version_switch_succeeds_without_pump(self, client):
        # 검증 FAIL-1 회귀 가드 — 자동 연결 프로브가 돌아도(busy 미점유) 설정 변경이 가능해야 한다.
        st.STATE["adapter"] = None
        target = next(k for k in st.SENSORIUM_VERSIONS if k != st.STATE["sensorium"])
        r = client.post("/api/settings", json={"sensorium": target})
        assert r.status_code == 200 and r.get_json()["sensorium"] == target

    def test_auto_connect_toggle_roundtrip(self, client):
        # 자동 재연결 스위치 — **기본 OFF**(개편 2026-09-03: 연결 = 설정 후 명시 행위라
        # 부팅 자동 프로브 금지). 토글 반영 + 비불리언 무시는 종전 그대로.
        assert client.get("/api/state").get_json()["autoConnect"] is False
        assert client.post("/api/settings", json={"autoConnect": True}).get_json()["autoConnect"] is True
        assert st.STATE["auto_connect"] is True
        assert client.post("/api/settings", json={"autoConnect": "yes"}).get_json()["autoConnect"] is True
        assert client.post("/api/settings", json={"autoConnect": False}).get_json()["autoConnect"] is False


class TestMotionRoutesGateWithoutHardware:
    def test_disconnect_open_close_symmetry(self, client):
        # 오픈-클로즈 대칭(2026-09-03) — 미연결 끊기 = 멱등 200, 끊으면 자동 재연결도 OFF,
        # busy 중엔 409(모션 중 tty 닫기 방지).
        st.STATE["auto_connect"] = True
        r = client.post("/api/disconnect")
        assert r.status_code == 200 and r.get_json()["ok"] is True
        assert st.STATE["auto_connect"] is False and st.STATE["adapter"] is None
        st.STATE["busy"] = "초기화"
        try:
            assert client.post("/api/disconnect").status_code == 409
        finally:
            st.STATE["busy"] = None

    def test_plunger_requires_adapter(self, client):
        st.STATE["adapter"] = None
        r = client.post("/api/plunger", json={"op": "aspirate", "pump": 1, "port": 1, "volumeUl": 100})
        assert r.status_code == 400  # 어댑터 게이트가 web 까지 배선됨(유효 op 로 — 계약 검증과 분리).

    def test_new_motion_routes_require_adapter(self, client):
        # 2탭 개편(2026-09-03) 라우트 게이트 — 플런저 절대이동·토출 테스트·밸브 회전 전부
        # 어댑터 없이는 400(연결 관문이 web 까지 배선됨).
        st.STATE["adapter"] = None
        assert client.post("/api/plunger", json={"op": "aspirate", "pump": 1, "port": 1, "volumeUl": 100}).status_code == 400

    def test_logs_endpoint_alive(self, client):
        r = client.get("/api/logs?since=0")
        assert r.status_code == 200 and "logs" in r.get_json()
