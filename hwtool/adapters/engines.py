"""펌프 기기 모델 → EnginePort 구현체 결선 (아웃바운드 어댑터 레지스트리).

인터페이스(포트) = 운영 pi daemon 의 `senlyt_pi.ports.EnginePort` — 이 툴은 그 계약의
소비자다(재구현 금지). 센소리움 버전의 `pumpModel` 이 이 레지스트리에서 구현체로 해석된다:
SY-01B ↔ Tecan XCalibur (U↔N0·?↔Q·축 12000↔3000·속도 하한 — 상세는 senlyt_pi 의
`tecan_xcalibur_engine_adapter.py` 문서).

설치된 senlyt_pi 핀이 tecan 어댑터를 아직 안 담은 구버전이면 import 가 실패한다 — 그 모델은
"구현체 미설치"로 정직하게 표기하고 **연결을 거부**한다(조용한 sy01b 폴백 = 오배선 금지:
sy01b 구현체로 XCalibur 에 U 를 쏘면 NVM 설정이 바뀔 수 있다).
"""

from __future__ import annotations

from senlyt_pi.adapters.sy01b_engine_adapter import Sy01bEngineAdapter
from senlyt_pi.core.pump_guard import PUMP_PRESETS, SyringeSpec

try:
    from senlyt_pi.adapters.tecan_xcalibur_engine_adapter import TecanXCaliburEngineAdapter
except ImportError:  # 구버전 senlyt_pi 핀 — tecan 미지원.
    TecanXCaliburEngineAdapter = None

ENGINE_ADAPTERS = {"sy01b": Sy01bEngineAdapter, "tecan_xcalibur": TecanXCaliburEngineAdapter}


def engine_cls(model: str):
    """기기 모델 id → 어댑터 클래스 (미지원 = None — 호출자가 연결을 거부한다).

    "지원" 판정은 **원자적**(검증 P1-3) — 구현체(ENGINE_ADAPTERS)와 스텝 축 프리셋
    (PUMP_PRESETS) **둘 다** 있어야 한다. 한쪽만 랜딩한 어중간한 설치(예: 어댑터는 있는데
    프리셋이 없는 senlyt_pi 조합)에서 축이 조용히 sy01b 로 폴백해 4배 과다토출이 되는
    경로를 구조적으로 막는다.
    """
    cls = ENGINE_ADAPTERS.get(model)
    if cls is None or model not in PUMP_PRESETS:
        return None
    return cls


def spec_for(model: str, capacity_ml: float) -> SyringeSpec:
    """용량 → SyringeSpec — **풀스트로크 축은 기기 모델이 결정**한다.

    sy01b=12000 / tecan_xcalibur=3000(N0). 여기서 축을 안 갈아타면 같은 µL 요청이
    XCalibur 에서 4배 스텝으로 나간다(검증팀 P0 — 125µL 이하 무성 4배 과다토출).

    ⛔ fail-closed(검증 P1-3) — 미등록 모델에 조용히 sy01b 축을 씌우지 않는다(무성 오축이
    최악). `engine_cls()` 가 같은 조건으로 연결을 거부하므로 정상 경로에선 도달 불가지만,
    도달하면 즉시 예외로 표면화한다.
    """
    preset = PUMP_PRESETS.get(model)
    if preset is None:
        raise LookupError(
            f"기기 모델 '{model}' 의 스텝 축 프리셋이 설치된 senlyt_pi 에 없습니다 — "
            "핀 갱신 전엔 이 모델로 스펙을 만들 수 없습니다(오축 방지)."
        )
    return SyringeSpec(
        pump_full_stroke=preset.pump_full_stroke,
        syringe_capacity_ml=float(capacity_ml),
    )
