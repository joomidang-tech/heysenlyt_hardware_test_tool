"""기주 솔레노이드 밸브(GPIO) 지연 초기화 — 아웃바운드 어댑터 결선 (식향 전용).

daemon bootstrap 과 **같은 env**로 구성한다(재검증 P2-i 봉합) — 핀 매핑(`SENLYT_VALVE_PINS`)·
유량·개방 상한 env 를 데몬과 동일하게 읽고, 파서도 데몬 것(`_valve_pins_from_env`)을 그대로
import 한다. 실기기(gpiozero 가용)에서만 성립.
"""

from __future__ import annotations

import threading

_VALVE_INIT_LOCK = threading.Lock()


def valve_adapter(state: dict, log) -> "object | None":
    """밸브(GPIO) 지연 초기화 — state["valve"] 를 "uninit" → 어댑터 | None 으로 확정.

    락으로 이중 생성 차단(리뷰 P2-3) — 동시 요청이 같은 BCM 핀을 두 번 클레임하면 두 번째
    예외가 정상 어댑터를 None 으로 덮어 밸브 기능이 영구 상실된다.
    """
    with _VALVE_INIT_LOCK:
        return _valve_adapter_locked(state, log)


def _valve_adapter_locked(state: dict, log):
    if state["valve"] == "uninit":
        try:
            import os

            from senlyt_pi.adapters.valve_adapter import (
                DEFAULT_FLOW_ML_PER_SEC,
                DEFAULT_MAX_OPEN_SEC,
                GpioValveAdapter,
            )
            from senlyt_pi.app.bootstrap import (
                SENLYT_VALVE_FLOW_ENV,
                SENLYT_VALVE_MAX_OPEN_ENV,
                SENLYT_VALVE_PINS_ENV,
                _float_env,
                _valve_pins_from_env,
            )

            state["valve"] = GpioValveAdapter(
                pins=_valve_pins_from_env(os.environ.get(SENLYT_VALVE_PINS_ENV)),
                flow_ml_per_sec=_float_env(os.environ, SENLYT_VALVE_FLOW_ENV, DEFAULT_FLOW_ML_PER_SEC),
                max_open_sec=_float_env(os.environ, SENLYT_VALVE_MAX_OPEN_ENV, DEFAULT_MAX_OPEN_SEC),
            )
            log("info", "밸브 어댑터 초기화(GPIO)", bases=state["valve"].available_bases())
        except Exception as e:  # noqa: BLE001 — gpiozero 부재/핀 클레임 실패 = 밸브 기능 숨김.
            state["valve"] = None
            state["valve_err"] = str(e)[:200]
            log("warn", "밸브 어댑터 사용 불가(GPIO 미가용)", reason=str(e)[:120])
    return state["valve"]
