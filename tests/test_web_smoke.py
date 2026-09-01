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


class TestPortmapValidation:
    # ⚠️ 각 케이스는 **앞선 검사를 전부 통과**시킨 뒤 목표 검사만 위반해야 실질 검증이다
    #   (검증 변이시험 M2/M7/M9 — 첫 관문에서 끝나는 페이로드는 뒤 검사를 안 밟는다).
    def test_missing_output_rejected(self, client):
        pump = st.version()["pumps"][0]
        r = client.post("/api/portmap", json={"pump": pump, "ports": {"1": "lemon"}})
        assert r.status_code == 400 and "output" in r.get_json()["error"]

    def test_missing_air_rejected(self, client):
        pump = st.version()["pumps"][0]
        r = client.post("/api/portmap", json={
            "pump": pump, "ports": {"1": "lemon", "2": "output", "11": "cleaning"}})
        assert r.status_code == 400 and "air" in r.get_json()["error"]

    def test_missing_cleaning_rejected(self, client):
        # cleaning 0개 = 세척이 모드 기본 포트의 **다른 액체를 알코올인 줄 알고 전량 소모**하는
        # 조용한 오동작 경로 — fail-closed 가드의 회귀 방지망(변이 M2 생존 봉합).
        pump = st.version()["pumps"][0]
        r = client.post("/api/portmap", json={
            "pump": pump, "ports": {"1": "lemon", "2": "output", "12": "air"}})
        assert r.status_code == 400 and "세척액" in r.get_json()["error"]

    def test_out_of_range_port_rejected(self, client):
        pump = st.version()["pumps"][0]
        r = client.post("/api/portmap", json={
            "pump": pump,
            "ports": {"99": "lemon", "2": "output", "12": "air", "11": "cleaning"}})
        assert r.status_code == 400 and "1~12" in r.get_json()["error"]

    def test_duplicate_liquid_rejected(self, client):
        pump = st.version()["pumps"][0]
        r = client.post("/api/portmap", json={
            "pump": pump,
            "ports": {"1": "lemon", "3": "lemon", "2": "output", "12": "air", "11": "cleaning"},
        })
        assert r.status_code == 400 and "중복" in r.get_json()["error"]

    def test_valid_layout_accepted_and_returns_state(self, client):
        # 성공 계약 — 원본 `return api_state()` 보존: 200 + 전체 state JSON(검증 P2-9).
        pump = st.version()["pumps"][0]
        r = client.post("/api/portmap", json={
            "pump": pump,
            "ports": {"1": "lemon", "2": "output", "12": "air", "11": "cleaning"}})
        assert r.status_code == 200
        s = r.get_json()
        assert s["pumpPorts"][str(pump)]["1"] == "lemon" and "versions" in s


class TestSettingsWhileDisconnected:
    def test_version_switch_succeeds_without_pump(self, client):
        # 검증 FAIL-1 회귀 가드 — 자동 연결 프로브가 돌아도(busy 미점유) 설정 변경이 가능해야 한다.
        st.STATE["adapter"] = None
        target = next(k for k in st.SENSORIUM_VERSIONS if k != st.STATE["sensorium"])
        r = client.post("/api/settings", json={"sensorium": target})
        assert r.status_code == 200 and r.get_json()["sensorium"] == target

    def test_auto_connect_toggle_roundtrip(self, client):
        # 자동 연결 ON/OFF 스위치(사용자 요청 2026-09-01) — 상태 반영 + 비불리언 무시.
        assert client.get("/api/state").get_json()["autoConnect"] is True
        assert client.post("/api/settings", json={"autoConnect": False}).get_json()["autoConnect"] is False
        assert st.STATE["auto_connect"] is False
        assert client.post("/api/settings", json={"autoConnect": "yes"}).get_json()["autoConnect"] is False
        assert client.post("/api/settings", json={"autoConnect": True}).get_json()["autoConnect"] is True


class TestMotionRoutesGateWithoutHardware:
    def test_plunger_requires_adapter(self, client):
        st.STATE["adapter"] = None
        r = client.post("/api/plunger", json={"op": "plungerFull", "pump": 1})
        assert r.status_code == 400  # 어댑터 게이트가 web 까지 배선됨.

    def test_filling_requires_adapter(self, client):
        st.STATE["adapter"] = None
        r = client.post("/api/filling", json={"targets": [{"pump": 1, "port": 3}], "volumeUl": 100})
        assert r.status_code == 400

    def test_logs_endpoint_alive(self, client):
        r = client.get("/api/logs?since=0")
        assert r.status_code == 200 and "logs" in r.get_json()
