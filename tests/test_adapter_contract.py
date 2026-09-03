"""툴 ↔ 실어댑터 표면 계약 그물 (2026-09-03 아키텍처 검증 P1-3).

hwtool 이 실제로 부르는 어댑터 표면은 EnginePort(운영 계약 7종)보다 넓다 — 치환 보증이
Protocol 이 아니라 상속에만 걸려 있으면, 형상(핀)이 어긋나도 테스트가 침묵한다(그게
requirements 핀 구세대 사고의 발견 경로였다). 여기서 **설치된 senlyt_pi 의 두 실구현체**가
툴 요구 표면 전부를 갖는지 직접 검증한다 — 핀이 뒤처지면 이 테스트가 빨갛게 알린다.
"""

import inspect

import pytest

from senlyt_pi.adapters.sy01b_engine_adapter import Sy01bEngineAdapter

try:
    from senlyt_pi.adapters.tecan_xcalibur_engine_adapter import TecanXCaliburEngineAdapter
except ImportError:  # 핀 구세대 — 아래 테스트가 실패로 표면화한다.
    TecanXCaliburEngineAdapter = None

# hwtool(service/connection·maintenance·settings)이 부르는 어댑터 표면 전량.
REQUIRED_SURFACE = [
    # EnginePort 계약분
    "aspirate", "dispense", "emergency_stop_all", "clear_estop", "run_op",
    # 생명주기·관측(운영 daemon 도 쓰는 사실상 계약)
    "close", "signal_stop", "probe", "health_probe", "initialize_polled",
    # 벤치 프리미티브(2026-09-03)
    "rotate_valve", "plunger_to", "plunger_position", "pump_config", "model_fingerprint",
]


@pytest.mark.parametrize("cls", [Sy01bEngineAdapter, TecanXCaliburEngineAdapter],
                         ids=["sy01b", "tecan_xcalibur"])
def test_real_adapter_satisfies_tool_surface(cls):
    assert cls is not None, "tecan 어댑터 미설치 — requirements 핀이 구세대입니다(P1-1)"
    missing = [m for m in REQUIRED_SURFACE if not callable(getattr(cls, m, None))]
    assert not missing, f"{cls.__name__} 에 툴 요구 표면 누락: {missing} — 핀/구현 정합 확인"


def test_rotate_valve_accepts_spec_kwarg():
    # 회전 전 셋업 보장(spec 전달)이 시그니처 계약이다 — 없으면 TypeError 로 조용히 깨진다.
    for cls in (Sy01bEngineAdapter, TecanXCaliburEngineAdapter):
        assert cls is not None
        assert "spec" in inspect.signature(cls.rotate_valve).parameters


def test_dialect_class_seams_declared():
    # "명령어만 다르고 코드는 일치" — 방언은 클래스 선언 값으로만 갈린다(본문 재정의 최소).
    assert Sy01bEngineAdapter.MODEL_ID == "sy01b"
    assert Sy01bEngineAdapter.TERMINATE_CMD == "TR" and Sy01bEngineAdapter.MIN_SPEED_HZ == 1
    assert TecanXCaliburEngineAdapter is not None
    assert TecanXCaliburEngineAdapter.MODEL_ID == "tecan_xcalibur"
    assert TecanXCaliburEngineAdapter.TERMINATE_CMD == "T"
    assert TecanXCaliburEngineAdapter.MIN_SPEED_HZ == 50
    assert TecanXCaliburEngineAdapter.ERR7_REHOMES is False
    # 속도 공식 본문은 공유(복붙 금지 그물).
    assert TecanXCaliburEngineAdapter._speed_cmd is Sy01bEngineAdapter._speed_cmd
