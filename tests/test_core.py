"""core 계층 — 순수 함수 단위테스트 (시리얼·Flask·전역 STATE 무의존)."""

from __future__ import annotations

import pytest
from senlyt_pi.core.pump_guard import PUMP_PRESETS

from hwtool.adapters.engines import spec_for
from hwtool.core.layout import (
    role_port,
    seed_layout,
    seed_pump_ports,
    seq_targets,
    tiles,
)
from hwtool.core.results import clamp_setting, result_json, valid_port


class TestSeedLayout:
    def test_flavor_pump1_roles(self):
        layout = seed_layout("flavor", 1)
        assert layout[2] == "output" and layout[12] == "air" and layout[11] == "cleaning"
        assert layout[1] == "lemon"

    def test_fragrance_notes_partitioned_by_pump(self):
        # 펌프 p 의 포트 2~10 에 27종을 9개씩 — 펌프1 첫 노트 = bitter lemon, 펌프3 마지막 = vanilla.
        assert seed_layout("fragrance", 1)[2] == "bitter lemon"
        assert seed_layout("fragrance", 3)[10] == "vanilla"
        assert set(seed_pump_ports("fragrance")) == {1, 2, 3}


class TestRolePort:
    def test_mapping_first_then_mode_default(self):
        ports = {1: {5: "output", 12: "air"}}
        assert role_port(ports, "flavor", 1, "output") == 5  # 매핑 우선.
        assert role_port(ports, "flavor", 1, "cleaning") == 11  # 없으면 모드 기본(P11).
        assert role_port({}, "fragrance", 2, "cleaning") == 1  # fragrance 기본 = P1(alcohol).

    def test_cleaning_accepts_alcohol_alias(self):
        ports = {1: {7: "alcohol"}}
        assert role_port(ports, "fragrance", 1, "cleaning") == 7


class TestTiles:
    def test_roles_excluded_and_duplicates_get_pump_suffix(self):
        ports = {
            1: {1: "lemon", 2: "output", 12: "air", 11: "cleaning"},
            2: {1: "lemon", 2: "output", 12: "air", 11: "cleaning"},
        }
        ts = tiles([1, 2], ports, "flavor")
        labels = [t["label"] for t in ts if not t.get("isRole")]
        assert labels == ["레몬 P1", "레몬 P2"]  # 중복 액체 = P{addr} 구분.
        assert all(t["liquid"] not in ("output", "air") for t in ts)
        # seq_targets: 중복 액체는 첫 타일만 + 펌프별 알코올.
        seq = seq_targets(ts)
        assert [(t["pump"], t["port"]) for t in seq] == [(1, 1), (1, 11), (2, 11)]


class TestResults:
    def test_error_classification(self):
        assert result_json(0)["ok"] is True
        r9 = result_json(9)
        assert r9["ok"] is False and r9["class"] == "permanent"
        assert result_json(15)["class"] == "transient"
        assert result_json(-1000)["class"] == "transient"  # 무응답 sentinel = 재시도 대상.

    def test_clamp_and_port_validation(self):
        # 상한 = 6000(2026-09-03 확장) — 어댑터 프리셋 물리 상한과 정렬(벤치 전 범위 실측).
        assert clamp_setting("aspirateSpeedHz", 99999, 2000) == 6000
        assert clamp_setting("aspirateSpeedHz", "bogus", 2000) == 2000
        assert valid_port(12) and not valid_port(13) and not valid_port("3")


class TestSpecAxisByModel:
    def test_sy01b_axis(self):
        assert spec_for("sy01b", 0.5).pump_full_stroke == 12000

    def test_tecan_axis_present_and_correct(self):
        # ⛔ skip 금지(2026-09-03 P1) — 프리셋 부재 = 배포 형상 오류(핀 구세대)다. 형상 오류는
        #   skip 으로 조용히 넘기지 않고 실패로 드러낸다.
        assert "tecan_xcalibur" in PUMP_PRESETS, "핀 구세대 — tecan 프리셋 없음(P1-1)"
        # 기기 모델이 스텝 축을 결정한다 — tecan=3000(N0). 검증팀 P0 회귀 가드.
        assert spec_for("tecan_xcalibur", 0.5).pump_full_stroke == 3000
        assert spec_for("tecan_xcalibur", 0.5).steps_for_volume_ul(100.0) == 600

    def test_unknown_model_fails_closed(self):
        # 미등록 모델에 조용히 sy01b 축을 씌우지 않는다(검증 P1-3 — 무성 오축이 최악).
        with pytest.raises(LookupError):
            spec_for("unknown-model", 0.5)
