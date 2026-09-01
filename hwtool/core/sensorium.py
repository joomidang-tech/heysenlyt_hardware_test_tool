"""센소리움 버전 레지스트리 — 연구소↔프로덕트팀 계약 단위(2026-08-24 규약 문서).

버전 하나가 **향료 팔레트 + AI 모델 + 하드웨어 구성(펌프 수·포트 배치·용량·기기 모델)** 을 함께
약속한다. 이 툴에서는 버전 선택이 계열(family: 식향/향장향 동작 분기)·펌프 목록·포트 시드·용량
기본·**펌프 기기 모델(구현체 선택자)** 을 결정한다.

⛔ 버전 id·AI 도장 값은 지어내지 않는다 — **버전은 어댑터가 알려준다**(port 계약 VersionPort
  "버전의 진실은 문서가 아니라 코드가 들고 다닌다"). 이 모듈은 ai-developer v1.3.0 어댑터의
  공식 접근자 `stamp_for("recipe")`(`heysenlyt_ai_adapter/domain/{flavor,fragrance}/stamp.py`
  — import 0 경량 모듈)를 **가능하면 직접 호출**해 세대(model)·도장(kernel_version)을 얻고,
  어댑터가 설치되지 않은 환경에서만 미러 상수로 폴백한다(web `lib/expo/stamp.ts` 미러와
  같은 패턴 — 폴백 사용 여부는 UI 에 표기해 드리프트를 숨기지 않는다).
"""

from __future__ import annotations

_MIRROR_STAMPS = {
    # 어댑터 stamp.py "recipe" 행의 미러(2026-09-01 대조) — 어댑터 미설치 환경 전용 폴백.
    "flavor": {"model": "sensorium-expo-0.1.2", "mode": "generative", "released_at": "2026-07-20",
               "kernel_version": "sensorium-expo-0.1.2+generative+2026-07-20"},
    "fragrance": {"model": "sensorium-fragrance-1.0.0", "mode": "rule", "released_at": "2026-05-28",
                  "kernel_version": "sensorium-fragrance-1.0.0+rule+2026-05-28"},
}

# 기기 모델 표기 라벨 — 모델 id 는 senlyt_pi PUMP_PRESETS 키와 동일 축.
PUMP_MODEL_LABELS = {"sy01b": "SY-01B (Runze)", "tecan_xcalibur": "XCalibur (Tecan Cavro)"}


def _load_ai_stamps() -> "tuple[dict, str]":
    """센소리움 도장 로드 — 어댑터 `stamp_for`(정본) 우선, 미설치 시 미러 폴백.

    반환 = ({family: stamp dict}, source) · source = "adapter"(정본) | "mirror"(폴백).

    ⚠️ **stamp.py 를 패키지 초기화 없이 단독 로드**한다 — 어댑터 패키지 `__init__` 은 LLM
    인프라(heysenlyt_ai_port 등)를 끌어와 정비 컴퓨터에선 대개 실패하지만, stamp 모듈 자체는
    VersionPort 계약대로 "무거운 커널 본체를 import 하지 않고 읽혀야 한다"(import 0)라서
    파일 단독 로드가 계약상 보장된 경로다.
    """
    try:
        import importlib.util
        from pathlib import Path

        spec = importlib.util.find_spec("heysenlyt_ai_adapter")
        if spec is None or not spec.submodule_search_locations:
            raise ImportError("heysenlyt_ai_adapter 미설치")
        pkg_dir = Path(list(spec.submodule_search_locations)[0])

        def load(family: str) -> dict:
            path = pkg_dir / "domain" / family / "stamp.py"
            mspec = importlib.util.spec_from_file_location(f"_hwtool_stamp_{family}", path)
            mod = importlib.util.module_from_spec(mspec)
            mspec.loader.exec_module(mod)  # import 0 모듈 — 단독 실행 안전(계약).
            st = mod.stamp_for("recipe")
            # 스키마 검증(리뷰 NEW-3) — 키가 바뀐 어댑터는 여기서 raise → 미러 폴백으로 흡수.
            #   검증 없이 통과시키면 모듈 최상위의 레지스트리 조립이 KeyError 로 죽어 툴이 안 뜬다.
            if not {"model", "kernel_version"} <= set(st):
                raise ValueError(f"stamp 스키마 불일치({family}): {sorted(st)}")
            return st

        return ({"flavor": load("flavor"), "fragrance": load("fragrance")}, "adapter")
    except Exception:  # noqa: BLE001 — 어댑터 미설치(펌프 전용 컴퓨터 등) = 미러 폴백.
        return (dict(_MIRROR_STAMPS), "mirror")


_AI_STAMPS, AI_STAMP_SOURCE = _load_ai_stamps()

# 계열별 하드웨어 구성 — 센소리움 규약에서 버전이 약속하는 HW 축(펌프 수·팔레트·용량·기기 모델).
#   pumpModel 은 정보 표기가 아니라 **구현체 선택자**다(2026-09-01) — adapters.engines 에서
#   EnginePort 구현체(Sy01b/TecanXCalibur)와 스텝 축(PUMP_PRESETS 풀스트로크 12000/3000)을 결정.
#   ⚠️ 주소별 혼합 구성({1: sy01b, 2: tecan})은 버스 소유권 설계 확정 후 확장 예정 — 현재는
#   버전당 단일 모델.
_FAMILY_HW = {
    "flavor": {"pumps": [1, 2], "capacityMl": 0.5, "pumpModel": "sy01b", "palette": "16향+당"},
    "fragrance": {"pumps": [1, 2, 3], "capacityMl": 0.5, "pumpModel": "sy01b", "palette": "27노트"},
}
# 버전 목록 = 계열 2종 × 기기 모델 2종(기본 SY-01B + XCalibur 기기변형) = 4개.
#   Tecan 변형은 사용자 지시(2026-09-01)로 툴에 추가한 **기기변형**이다 — AI 도장은 base 버전과
#   동일하고(향료 팔레트·모델 불변), 하드웨어 축(구현체·스텝 3000)만 바뀐다. id 는 지어낸 새
#   버전이 아니라 `{base 도장}+tecan` 파생 표기 — 연구소 규약에 정식 등재되면 그 id 로 대체한다.
_MODEL_VARIANTS = (
    ("sy01b", "", ""),
    ("tecan_xcalibur", "+tecan", " · XCalibur(Tecan) 기기변형"),
)
SENSORIUM_VERSIONS = {
    stamp["model"] + suffix: {
        "label": f"{stamp['model']} — {'식향' if fam == 'flavor' else '향장향'} · {_FAMILY_HW[fam]['pumps'][-1]}펌프 · {_FAMILY_HW[fam]['palette']}{label_sfx}",
        "family": fam,
        "pumps": _FAMILY_HW[fam]["pumps"],
        "capacityMl": _FAMILY_HW[fam]["capacityMl"],
        "pumpModel": model_id,
        "aiModel": stamp["kernel_version"],
    }
    for fam, stamp in _AI_STAMPS.items()
    for model_id, suffix, label_sfx in _MODEL_VARIANTS
}
DEFAULT_SENSORIUM = _AI_STAMPS["fragrance"]["model"]
