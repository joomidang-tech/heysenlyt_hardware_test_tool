#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시린지펌프 정비 툴 (v1.3.0) — admin 점검·유지보수 화면의 로컬 미러, 운영 pi daemon 코드로 구동.

무엇인가
--------
시린지펌프(SY-01B 계열·RS485)가 연결된 컴퓨터에서 켜서, 브라우저로 펌프를 점검·정비하는 도구다.
화면 구성은 admin 콘솔의 **점검·유지보수 페이지(MaintenancePage) 3섹션을 그대로 미러**한다:

  ① 펌프 제어   — 기기 연결 상태 · 시린지 흡입/배출 · [약한 초기화] · [🧼 세척]
  ② 밸브 제어   — 신기주/베이스 기주 솔레노이드(식향 전용·GPIO) — ON/OFF(10s 자동닫힘)·N초 열기·상호배타
  ③ 진단 도구 · 향료 필링 — 단일 포트 속도 진단(흡입/배출 속도·흡입량 조절) · 순차 향료 필링

주문·제조·서버 연동은 없다 — 유지보수 어휘까지만.

"똑같이 동작"의 근거 (구조)
---------------------------
펌프·밸브 제어를 재구현하지 않는다. 운영 pi daemon 패키지 `senlyt_pi`(v1.3.0 커밋 핀,
requirements.txt)를 **그대로 import** 해서:

  - 시리얼 발견/프로브  = `serial_port_discovery` + `pump_health` (daemon 부팅과 동일)
  - 펌프 제어          = `Sy01bEngineAdapter` (버스락·폴링·에러분류·ack-tolerant 전부 그대로)
  - 밸브 제어          = `GpioValveAdapter` (상호배타 L3·자동닫힘 타이머·Active-LOW 그대로)
  - 용량→스텝 파생     = `SyringeSpec` (서버 pumpGuard.ts 와 byte-parity)

admin 서버측 조립의 미러(값까지 동일):
  - 약한 초기화 = 전 펌프 동시 홈 → `initialize_polled` (MaintenancePage.forceInitAll · estop 해제 후)
  - 전량 흡입/배출 = `run_op(plunger_full/home)` + 밸브 회전 air/output (wire.ts:1232~)
  - 세척 = 알코올 전량 스트로크 × N회(펌프 병렬 stage) + 식향 한정 에어 퍼지 × N회
    (lib/admin/maintenanceSteps.ts `cleaningSteps` 와 동일 시퀀스·동일 기본값 2/3)
  - 진단/필링 = 명시 속도의 syringe 스텝 (SettingsPage DiagTool — 흡입 기본 2000Hz)
  - 밸브 = ON 10s 상한·N초 1~10s·상호배타 (MaintenancePage 밸브 제어와 동일 상수)

포트 배치 = **센소리움 버전의 시드 + [포트 매핑] 편집**(admin pumpPorts 미러 — 펌프별).
센소리움 버전 = 향료 팔레트·AI 모델·하드웨어 구성을 함께 약속하는 계약 단위(규약 문서) —
버전 선택이 계열(flavor/fragrance)·펌프 목록·포트 시드·용량 기본을 결정한다. 역할 포트
해석은 매핑 우선·모드 기본 폴백(`portLayout.ts` outputPortOf/airPortOf/cleaningPortOf 미러).

⚠️ 로컬 전용·인증 없음 — 같은 네트워크 누구나 펌프를 움직일 수 있다. 정비 시에만 켤 것.
"""
from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request

# ── 운영 pi daemon 코드 그대로 (재구현 금지) ─────────────────────────────────────
from senlyt_pi.adapters.serial_port_discovery import list_candidate_ports
from senlyt_pi.adapters.sy01b_engine_adapter import Sy01bEngineAdapter
from senlyt_pi.core.pump_guard import (
    SyringeSpec,
    VALID_SYRINGE_CAPACITIES_ML,
    clamp_pump_preset,
    classify_engine_error_code,
    is_volume_within_gate,
)
from senlyt_pi.obs.log import StructuredLogger
from senlyt_pi.pipeline.pump_health import discover_pumps, scan_addresses
from senlyt_pi.ports.engine_port import (
    OP_PLUNGER_FULL,
    OP_PLUNGER_HOME,
    EngineDispenseCommand,
    EngineOpCommand,
)
from senlyt_pi.test_seam.fake_engine_sentinels import (
    FAKE_EMPTY_RAW_CODE,
    FAKE_TIMEOUT_RAW_CODE,
)

# ── admin 미러 상수 ────────────────────────────────────────────────────────────
# 모드별 예약 역할 기본 포트 — heysenlyt-web `portLayout.ts defaultRolePort` 와 동일값.
#   cleaning = 알코올(세척액) 포트: flavor P11(cleaning 역할) / fragrance P1(alcohol 역할)
#   (`cleaningPortOf` 폴백과 동일).
DEFAULT_ROLE_PORTS = {
    "flavor": {"output": 2, "air": 12, "cleaning": 11},
    "fragrance": {"output": 11, "air": 12, "cleaning": 1},
}
# 속도 기본값 — admin `settingsClamp.ts` FLAVOR/FRAGRANCE_DEFAULTS 와 동일값(양 모드 공통).
#   서버는 syringe 스텝에 속도를 항상 실어 보낸다 — 미전달 시 어댑터 프리셋 상한(6000Hz·L20)으로
#   떨어져 운영보다 거칠게 빨게 되므로(검증 P1-1) 여기서도 항상 싣는다.
ASPIRATE_SPEED_DEFAULT_HZ = 5000
DISPENSE_SPEED_DEFAULT_HZ = 6000
SLOPE_DEFAULT = 14
DIAG_ASPIRATE_DEFAULT_HZ = 2000  # 진단 도구 흡입 기본(DiagTool useState(2000) 미러).
SETTINGS_RANGES = {
    "aspirateSpeedHz": (500, 5000),
    "dispenseSpeedHz": (500, 6000),
    "slope": (1, 20),
}
# 세척 기본값 — cleaningSteps(mode, purgeCount=3, alcoholCount=2) + MAX_CLEAN_PURGE_COUNT=10 미러.
CLEAN_ALCOHOL_DEFAULT = 2
CLEAN_PURGE_DEFAULT = 3
MAX_CLEAN_COUNT = 10
# 밸브 — MaintenancePage VALVE_LATCH_SEC=10 · N초 1~10s(UI) 미러. pi max_open_sec 15s 는 안전천장.
VALVE_LATCH_SEC = 10
VALVE_BASES_LABEL = {"sour": "신 기주", "normal": "베이스 기주"}
# 펌프 표시 라벨 — MaintenancePage 미러(향장향 A/B/C펌프 · 식향 N펌프).
FRAGRANCE_PUMP_LABELS = {1: "A펌프", 2: "B펌프", 3: "C펌프"}

# ── 시드 포트 배치 (admin `portLayout.ts` SEED_* 미러) ─────────────────────────
#   admin 진단 도구는 기기설정 pumpPorts 의 **액체 타일**로 포트를 고른다. 이 툴엔 서버 설정이
#   없으므로 admin 이 미설정 기기의 출발점으로 쓰는 **시드 배치**를 그대로 내장한다 — 운영자가
#   admin 에서 배치를 바꾼 기기라면 admin 으로 정비할 것(전역 포트와 같은 한계·문서화).
#   라벨 = admin 카탈로그의 한글명(AROMA_FLAVORS nameKo · NOTE_META nameKo) 그대로.
_FLAVOR_LIQUID_KO = {
    "lemon": "레몬", "lime": "라임", "orange": "오렌지", "grapefruit": "자몽",
    "grape": "포도(적포도)", "muscat": "청포도(머스캣)", "apple": "사과(청사과)", "peach": "복숭아",
    "pineapple": "파인애플", "mango": "망고", "berry": "딸기/베리", "yogurt": "요구르트(유산균)",
    "plum": "매실", "yuzu": "유자", "cola": "콜라", "coffee": "커피", "sweet": "당(감미)",
}
# SEED_FLAVOR_PUMP_PORTS 미러 — 펌프1: 1~10 액체(2=output·11=cleaning·12=air 제외), 펌프2: 9액체.
_SEED_FLAVOR_PORTS = {
    1: {1: "lemon", 3: "lime", 4: "orange", 5: "grapefruit", 6: "grape", 7: "muscat",
        8: "berry", 9: "yogurt", 10: "sweet"},
    2: {1: "apple", 3: "peach", 4: "pineapple", 5: "mango", 6: "plum", 7: "yuzu",
        8: "cola", 9: "coffee"},
}
# NOTE_META 27종 idx 순(1~27) — buildFragranceSeed 미러: 펌프 p 의 포트 2~10 에 9종씩.
_FRAGRANCE_NOTES_KO = [
    ("bitter lemon", "비터 레몬"), ("lime", "라임"), ("grapefruit", "자몽"), ("bergamot", "베르가못"),
    ("orange", "오렌지"), ("green note", "그린 노트"), ("alpine lavender", "알파인 라벤더"),
    ("apple", "사과"), ("peach", "복숭아"), ("aldehydal", "알데하이드"), ("sea scent", "바다 향"),
    ("lily of the valley", "은방울꽃"), ("ivy", "아이비"), ("ginger", "진저"),
    ("bitter orange flower", "비터 오렌지 플라워"), ("violet leaves", "바이올렛 리프"),
    ("rose petals", "로즈 페탈"), ("jasmin", "자스민"), ("cedarwood", "시더우드"),
    ("vetyver", "베티버"), ("musk", "머스크"), ("sandalwood", "샌달우드"), ("iris", "아이리스"),
    ("moss", "모스"), ("amber", "앰버"), ("white musk", "화이트 머스크"), ("vanilla", "바닐라"),
]


# 예약 역할 이름 — admin portLayout `PortRoles` 미러(라벨 포함).
PORT_ROLES = ("output", "air", "cleaning", "alcohol")
ROLE_LABELS = {"output": "배출(output)", "air": "공기(air)", "cleaning": "세척액", "alcohol": "알코올(캐리어/세척)"}

# ── 센소리움 버전 레지스트리 ────────────────────────────────────────────────────
#   센소리움 버전 = 연구소↔프로덕트팀 계약 단위(2026-08-24 규약 문서) — 버전 하나가 **향료
#   팔레트 + AI 모델 + 하드웨어 구성(펌프 수·포트 배치·용량)** 을 함께 약속한다. 이 툴에서는
#   버전 선택이 계열(family: 식향/향장향 동작 분기)·펌프 목록·포트 시드·용량 기본을 결정한다.
#
#   ⛔ 버전 id·AI 도장 값은 지어내지 않는다 — **버전은 어댑터가 알려준다**(port 계약 VersionPort
#     "버전의 진실은 문서가 아니라 코드가 들고 다닌다"). 이 툴은 ai-developer v1.3.0 어댑터의
#     공식 접근자 `stamp_for("recipe")`(`heysenlyt_ai_adapter/domain/{flavor,fragrance}/stamp.py`
#     — import 0 경량 모듈)를 **가능하면 직접 호출**해 세대(model)·도장(kernel_version)을 얻고,
#     어댑터가 설치되지 않은 환경에서만 아래 미러 상수로 폴백한다(web `lib/expo/stamp.ts` 미러와
#     같은 패턴 — 폴백 사용 여부는 UI 에 표기해 드리프트를 숨기지 않는다).
#   pumpModel 은 현재 senlyt_pi 프리셋이 sy01b 단일이라 정보 표기(테칸 도입 시 프리셋과 함께 확장).
_MIRROR_STAMPS = {
    # 어댑터 stamp.py "recipe" 행의 미러(2026-09-01 대조) — 어댑터 미설치 환경 전용 폴백.
    "flavor": {"model": "sensorium-expo-0.1.2", "mode": "generative", "released_at": "2026-07-20",
               "kernel_version": "sensorium-expo-0.1.2+generative+2026-07-20"},
    "fragrance": {"model": "sensorium-fragrance-1.0.0", "mode": "rule", "released_at": "2026-05-28",
                  "kernel_version": "sensorium-fragrance-1.0.0+rule+2026-05-28"},
}


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
# 계열별 하드웨어 구성 — 센소리움 규약에서 버전이 약속하는 HW 축(펌프 수·팔레트·용량).
_FAMILY_HW = {
    "flavor": {"pumps": [1, 2], "capacityMl": 0.5, "pumpModel": "sy01b", "palette": "16향+당"},
    "fragrance": {"pumps": [1, 2, 3], "capacityMl": 0.5, "pumpModel": "sy01b", "palette": "27노트"},
}
SENSORIUM_VERSIONS = {
    stamp["model"]: {
        "label": f"{stamp['model']} — {'식향' if fam == 'flavor' else '향장향'} · {_FAMILY_HW[fam]['pumps'][-1]}펌프 · {_FAMILY_HW[fam]['palette']}",
        "family": fam,
        "pumps": _FAMILY_HW[fam]["pumps"],
        "capacityMl": _FAMILY_HW[fam]["capacityMl"],
        "pumpModel": _FAMILY_HW[fam]["pumpModel"],
        "aiModel": stamp["kernel_version"],
    }
    for fam, stamp in _AI_STAMPS.items()
}
DEFAULT_SENSORIUM = _AI_STAMPS["fragrance"]["model"]


def _version() -> dict:
    return SENSORIUM_VERSIONS[STATE["sensorium"]]


def _seed_layout(mode: str, addr: int) -> dict:
    """펌프 1대의 시드 레이아웃 {port(int): liquid} — admin SEED_* 와 동일 배치(역할 포함)."""
    if mode == "flavor":
        layout = dict(_SEED_FLAVOR_PORTS.get(addr, {}))
        layout[2] = "output"
        layout[11] = "cleaning"
        layout[12] = "air"
        return layout
    layout = {1: "alcohol", 11: "output", 12: "air"}
    for j in range(9):
        idx = (addr - 1) * 9 + j
        if 0 <= idx < len(_FRAGRANCE_NOTES_KO):
            layout[j + 2] = _FRAGRANCE_NOTES_KO[idx][0]
    return layout


def _seed_pump_ports(family: str, pumps: "list[int] | None" = None) -> dict:
    """센소리움 버전의 시드 포트 매핑 — 버전의 펌프 목록 × 계열 시드 배치."""
    addrs = pumps if pumps is not None else ([1, 2] if family == "flavor" else [1, 2, 3])
    return {a: _seed_layout(family, a) for a in addrs}


def _default_role_port(mode: str, role: str) -> int:
    """`portLayout.defaultRolePort` 미러 — 매핑에 역할이 없을 때의 폴백."""
    d = DEFAULT_ROLE_PORTS[mode]
    if role in ("cleaning", "alcohol"):
        return d["cleaning"]
    return d.get(role, d["air"])


def _role_port(addr: int, role: str) -> int:
    """그 펌프의 역할 포트 — 매핑 우선·없으면 모드 기본(outputPortOf/airPortOf/cleaningPortOf 미러).

    cleaning 계열은 admin `cleaningPortOf` 처럼 cleaning → alcohol 순으로 관용 조회한다.
    """
    layout = STATE["pump_ports"].get(addr, {})
    wanted = ("cleaning", "alcohol") if role in ("cleaning", "alcohol") else (role,)
    for port in sorted(layout):
        if layout[port] in wanted:
            return port
    return _default_role_port(STATE["mode"], role)


def _liquid_label(liquid: str) -> str:
    if STATE["mode"] == "flavor":
        return _FLAVOR_LIQUID_KO.get(liquid, liquid)
    return dict(_FRAGRANCE_NOTES_KO).get(liquid, liquid)


def _tiles() -> list[dict]:
    """액체 타일 목록 — admin `tilesFromPumpPorts` 미러: **포트 매핑에서** 포트 1→12 순회
    (발견된 펌프만·output/air 제외·cleaning/alcohol=펌프별 역할 타일·중복 액체 P표기)."""
    tiles: list[dict] = []
    for addr in sorted(STATE["pumps"]):
        layout = STATE["pump_ports"].get(addr, {})
        for port in sorted(layout):  # 포트 1~12 순회 — admin 과 동일한 화면 배열(재검증 P2-l).
            liquid = layout[port]
            if not liquid or liquid in ("output", "air"):
                continue
            if liquid in ("cleaning", "alcohol"):
                tiles.append({"pump": addr, "port": port, "liquid": liquid,
                              "label": f"알코올(세척액) P{addr}", "isRole": True})
            else:
                tiles.append({"pump": addr, "port": port, "liquid": liquid,
                              "label": _liquid_label(liquid)})
    # 같은 액체 다중 펌프 → 라벨 P{addr} 구분(tilesFromPumpPorts 미러).
    count: dict[str, int] = {}
    for t in tiles:
        if not t.get("isRole"):
            count[t["liquid"]] = count.get(t["liquid"], 0) + 1
    for t in tiles:
        if not t.get("isRole") and count.get(t["liquid"], 0) > 1:
            t["label"] = f"{t['label']} P{t['pump']}"
    return tiles


def _seq_targets(tiles: list[dict]) -> list[dict]:
    """순차 필링 대상 — admin `seqTargets` 미러: 일반 액체(중복 액체는 첫 타일) + 펌프별
    알코올, (펌프, 포트) 정렬."""
    first_by_liquid: dict[str, dict] = {}
    for t in tiles:
        if not t.get("isRole") and t["liquid"] not in first_by_liquid:
            first_by_liquid[t["liquid"]] = t
    out = list(first_by_liquid.values()) + [t for t in tiles if t.get("isRole")]
    return sorted(out, key=lambda t: (t["pump"], t["port"]))
# 에러코드 한글 라벨 (SY-01B 매뉴얼 §4.6.2 + pump_guard 분류 주석).
ERROR_LABELS = {
    0: "정상",
    1: "초기화 오류",
    2: "잘못된 명령",
    3: "잘못된 피연산자",
    7: "미초기화(홈 상실)",
    9: "플런저 오버로드",
    10: "밸브 오버로드",
    11: "플런저 이동 실패(과다흡입 의심)",
    15: "명령 겹침(Busy/Command overflow)",
    FAKE_TIMEOUT_RAW_CODE: "무응답(타임아웃)",
    FAKE_EMPTY_RAW_CODE: "깨진 응답(프레임 아님)",
}
CLASS_LABELS = {"normal": "정상", "transient": "일시적(재시도 가능)", "permanent": "구조적(점검 필요)"}

MAX_PORT = 12  # SY-01B 회전 밸브 12구.

app = Flask(__name__)

# ── 로그: 어댑터의 구조화 로그(한글)를 링버퍼로 받아 UI 로 흘린다 ────────────────
_LOG_RING: deque = deque(maxlen=2000)  # 시리얼 왕복 DEBUG 가 다작이라 넉넉히(경고 밀림 방지).
_LOG_SEQ = {"n": 0}
_LOG_LOCK = threading.Lock()


def _log_sink(rec: dict) -> None:
    with _LOG_LOCK:
        _LOG_SEQ["n"] += 1
        _LOG_RING.append({"seq": _LOG_SEQ["n"], **rec})


LOGGER = StructuredLogger(service="hw-test-tool", sink=_log_sink)


def _log(level: str, message: str, **kw) -> None:
    getattr(LOGGER, level)(message, stage="tool", **kw)


# ── 전역 상태 (단일 사용자 정비 도구) ───────────────────────────────────────────
STATE = {
    "adapter": None,  # Sy01bEngineAdapter | None
    "port": None,  # str | None
    "last_port": None,  # str | None — 마지막으로 펌프가 응답한 포트(비상 estop 폴백용)
    "pumps": [],  # list[int] — 발견된 펌프 주소
    # 센소리움 버전 — 계열(mode)·펌프 구성·포트 시드·용량 기본을 결정하는 계약 단위(레지스트리 참조).
    "sensorium": DEFAULT_SENSORIUM,
    "mode": SENSORIUM_VERSIONS[DEFAULT_SENSORIUM]["family"],  # 파생값 — 버전의 계열(flavor|fragrance)
    "capacity_ml": SENSORIUM_VERSIONS[DEFAULT_SENSORIUM]["capacityMl"],
    # ⛔ 용량 확인 게이트(검증 P1-5) — 초기화 힘(Z/Z1/Z2)·스톨전류·스텝 파생이 전부 이 값에서
    #   나온다(작은 시린지에 Full force = 씰 손상·v1.1.0 실사고). 운영자가 실물과 일치를 명시
    #   확인하기 전엔 모션 버튼을 잠근다.
    "capacity_confirmed": False,
    # 포트 매핑(admin pumpPorts 미러) — {addr(int): {port(int): liquid}}. 시드 = 센소리움 버전.
    "pump_ports": _seed_pump_ports(SENSORIUM_VERSIONS[DEFAULT_SENSORIUM]["family"]),
    "busy": None,  # str | None — 진행 중 작업 라벨
    "connecting": False,  # 자동 인식 진행 중(리뷰 P2-5) — estop 의 temp 어댑터 겹침 방지.
    # 진행 중 프로브 어댑터 참조(리뷰 NEW-1) — estop 이 signal_stop 으로 프로브를 즉시 중단시키기 위함.
    "probe_adapter": None,
    # ⛔ 연결 후 첫 정비 게이트(리뷰 P1-2) — 약한 초기화/세척(포트 지정 홈)을 거치기 전의 plunger/
    #   필링은 어댑터 lazy 셋업이 **포트 없는 `Z{힘}R`**(펌웨어 기본 = 포트1 흡입·마지막 포트 배출)
    #   로 돌아 포트1 액체를 빨아 버린다(2026-07-21 실사고 경로). 첫 복구 성공 전엔 모션을 잠근다.
    "initialized_after_connect": False,
    # 서버측 estop 게이트의 미러(검증 P0-2) — 래치가 서면 복구(약한 초기화·세척) 외 모션을 409 차단.
    "estop": False,
    "estop_in_progress": False,  # estop TR 발송 중(검증 P0-4) — 그동안 복구 경로도 배제.
    # 밸브(GPIO) — 지연 초기화: "uninit" → GpioValveAdapter | None(사용 불가).
    "valve": "uninit",
    "valve_err": None,
    # 밸브 낙관 표시(admin 미러 — GPIO 출력은 실측 필드가 없어 발행 시각 기반) base → 만료 epoch.
    "valve_open_until": {"sour": 0.0, "normal": 0.0},
    # 향료 필링 진행(admin 순차 패널 미러 — 툴은 로컬이라 실시간) — None | dict.
    #   {active, phase, targets:[{pump,port,label}], current(진행 인덱스), results:[...], outcome}
    "filling": None,
}
# 정비 작업 직렬화 락 — daemon 이 정비/제조를 큐로 직렬화하는 것의 미러.
#   ⚠️ 긴급 정지는 이 락을 **타지 않는다**(어댑터가 스레드 안전 + estop 래치가 in-flight 폴을 깨움).
#   밸브도 안 탄다(L3 자체 락·시리얼과 독립 — pi 규약 그대로).
OP_LOCK = threading.Lock()


def _spec() -> SyringeSpec:
    """용량 → SyringeSpec — daemon `auto_pump_map` 과 동일 파생(프리셋 풀스트로크)."""
    preset = clamp_pump_preset(None)
    return SyringeSpec(
        pump_full_stroke=preset.pump_full_stroke,
        syringe_capacity_ml=float(STATE["capacity_ml"]),
    )


def _pump_label(addr: int) -> str:
    if STATE["mode"] == "fragrance":
        return FRAGRANCE_PUMP_LABELS.get(addr, f"{addr}펌프")
    return f"{addr}펌프"


def _result_json(raw_code: int, detail: str | None = None) -> dict:
    # sentinel 선분류(검증 P1-1) — 운영 EngineExecutor 와 동일하게, 무응답·깨진 응답은
    #   classify 이전에 transient(재시도 대상)로 판정한다.
    if raw_code in (FAKE_TIMEOUT_RAW_CODE, FAKE_EMPTY_RAW_CODE):
        return {
            "ok": False,
            "code": raw_code,
            "label": ERROR_LABELS[raw_code],
            "class": "transient",
            "classLabel": CLASS_LABELS["transient"],
            "detail": detail,
        }
    cls = classify_engine_error_code(raw_code).value
    return {
        "ok": raw_code == 0,
        "code": raw_code,
        "label": ERROR_LABELS.get(raw_code, f"미분류 코드 {raw_code}"),
        "class": cls,
        "classLabel": CLASS_LABELS.get(cls, cls),
        "detail": detail,
    }


def _busy_guard(label: str):
    """작업 락 non-blocking 획득 — 실패 시 None 반환(409)."""
    if not OP_LOCK.acquire(blocking=False):
        return None
    STATE["busy"] = label
    return OP_LOCK


def _release(lock) -> None:
    STATE["busy"] = None
    lock.release()


def _require_adapter():
    a = STATE["adapter"]
    if a is None:
        return None, (jsonify({"ok": False, "error": "펌프가 연결되지 않았습니다 — 먼저 자동 인식을 실행하세요."}), 400)
    return a, None


def _valid_port(v) -> bool:
    return isinstance(v, int) and 1 <= v <= MAX_PORT


def _clamp(key: str, v, default: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    lo, hi = SETTINGS_RANGES[key]
    return int(min(max(v, lo), hi))  # admin settingsClamp 와 동일한 클램프.


def _motion_gate(*, is_recovery: bool = False):
    """모션 요청 공통 게이트 — 통과 시 None, 차단 시 (json, status).

    - estop 발송 중: 전부 차단(P0-4).
    - estop 래치: 복구 경로(약한 초기화·세척)만 통과 — admin "복구는 [약한 초기화 & 세척]" 미러.
    - 용량 미확인: 전부 차단(P1-5).
    """
    if STATE["estop_in_progress"]:
        return jsonify({"ok": False, "error": "긴급 정지 발송 중 — 잠시 후 다시 시도하세요."}), 409
    if STATE["estop"] and not is_recovery:
        return jsonify({"ok": False, "error": "긴급 정지 래치 상태 — [약한 초기화] 또는 [세척]으로 복구하세요."}), 409
    if not STATE["capacity_confirmed"]:
        return jsonify({"ok": False, "error": "시린지 용량 확인이 필요합니다 — 설정에서 실물 용량과 일치함을 체크하세요."}), 400
    if not is_recovery and not STATE["initialized_after_connect"]:
        # 연결 후 첫 정비 게이트(P1-2) — 포트 지정 홈을 거치기 전의 lazy 셋업(Z 포트 생략) 차단.
        return jsonify({"ok": False, "error": "연결 후 [약한 초기화]를 먼저 실행하세요 — 홈 기준·포트를 잡기 전의 동작은 포트1 액체를 소모합니다."}), 409
    return None


_VALVE_INIT_LOCK = threading.Lock()


def _valve_adapter():
    """밸브(GPIO) 지연 초기화 — daemon bootstrap 과 **같은 env**로 구성(재검증 P2-i 봉합).

    핀 매핑(`SENLYT_VALVE_PINS`)·유량·개방 상한 env 를 데몬과 동일하게 읽는다 — 파서도
    데몬 것(`_valve_pins_from_env`)을 그대로 import. 실기기(gpiozero 가용)에서만 성립.
    락으로 이중 생성 차단(리뷰 P2-3) — 동시 요청이 같은 BCM 핀을 두 번 클레임하면 두 번째
    예외가 정상 어댑터를 None 으로 덮어 밸브 기능이 영구 상실된다.
    """
    with _VALVE_INIT_LOCK:
        return _valve_adapter_locked()


def _valve_adapter_locked():
    if STATE["valve"] == "uninit":
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

            STATE["valve"] = GpioValveAdapter(
                pins=_valve_pins_from_env(os.environ.get(SENLYT_VALVE_PINS_ENV)),
                flow_ml_per_sec=_float_env(os.environ, SENLYT_VALVE_FLOW_ENV, DEFAULT_FLOW_ML_PER_SEC),
                max_open_sec=_float_env(os.environ, SENLYT_VALVE_MAX_OPEN_ENV, DEFAULT_MAX_OPEN_SEC),
            )
            _log("info", "밸브 어댑터 초기화(GPIO)", bases=STATE["valve"].available_bases())
        except Exception as e:  # noqa: BLE001 — gpiozero 부재/핀 클레임 실패 = 밸브 기능 숨김.
            STATE["valve"] = None
            STATE["valve_err"] = str(e)[:200]
            _log("warn", "밸브 어댑터 사용 불가(GPIO 미가용)", reason=str(e)[:120])
    return STATE["valve"]


def _do_estop(addrs: list[int]) -> dict:
    """긴급 정지 실행 + **검증**(P0-1) — TR 발송 후 펌프별 `?` 프로브로 생존을 재확인한다.

    밸브도 즉시 닫는다(admin "긴급 정지 시에도 밸브 즉시 닫힘" 미러 — 이미 초기화된 경우만,
    estop 하자고 GPIO 를 새로 클레임하진 않는다).
    """
    STATE["estop"] = True
    STATE["estop_in_progress"] = True
    try:
        # ⛔ 밸브 닫기는 **펌프 TR 이후 + 별도 스레드**(리뷰 P0-2) — GpioValveAdapter 는 "N초 열기"
        #   동안 L3 락을 쥔 채 잠들어, close_all 을 먼저 부르면 estop 전체가 최대 10초 물린다.
        #   펌프 정지를 절대 지연시키지 않도록 밸브 닫기를 비동기로 던진다(락 풀리는 즉시 닫힘).
        v = STATE["valve"]
        if v not in ("uninit", None):
            def _close_valves() -> None:
                try:
                    v.close_all()
                    STATE["valve_open_until"] = {"sour": 0.0, "normal": 0.0}
                except Exception:  # noqa: BLE001 — 밸브 닫힘 실패가 펌프 정지를 막지 않는다.
                    pass
            threading.Thread(target=_close_valves, daemon=True).start()
        a = STATE["adapter"]
        temp = None
        if a is None and STATE["connecting"]:
            # 자동 인식 중(리뷰 NEW-1) — **거부하지 않는다**(자동 연결 루프 때문에 이 구간이 미연결
            #   시간의 대부분이라, 거부하면 정지 도달이 사실상 막힌다 = 제1원칙 위반). 대신:
            #   ① 프로브 어댑터에 협조 중단(signal_stop — probe() 가 시도마다 확인, ~1.5s 내 이탈)
            #   ② connecting 해제를 짧게 대기(프로브가 tty 를 놓게) → 겹침 없이 TR 경로로 진행
            #   ③ 그래도 안 풀리면 **정지 도달 > 프레임 순도** — last_port 로 그냥 쏜다.
            pa = STATE["probe_adapter"]
            if pa is not None:
                try:
                    pa.signal_stop()
                except Exception:  # noqa: BLE001 — 중단 신호 실패가 정지를 막지 않는다.
                    pass
            deadline = time.monotonic() + 5.0
            while STATE["connecting"] and time.monotonic() < deadline:
                time.sleep(0.05)
            a = STATE["adapter"]  # 그 사이 인식이 성공했으면 정식 어댑터로.
            if a is None and STATE["connecting"]:
                _log("warn", "긴급정지 — 프로브 중단 대기 초과, last_port 로 강행(정지 도달 우선)")
        if a is None and STATE["last_port"]:
            # 미연결(P0-3)이어도 마지막으로 펌프가 있던 포트로 즉시 TR.
            temp = a = Sy01bEngineAdapter(port=STATE["last_port"], logger=LOGGER)
        if a is None:
            return {"ok": False, "error": "연결 이력이 없어 정지 명령을 보낼 포트를 모릅니다 — 24V 전원을 끄세요."}
        try:
            # 발견 펌프가 없으면(인식 전) 주소 1~9 전수 TR — TR 은 모션 없는 멱등 명령이라 안전.
            targets = addrs or list(scan_addresses())
            a.emergency_stop_all(targets)
            verified = {str(p): a.health_probe(p) for p in targets}
        finally:
            if temp is not None:
                temp.close()
        ok = any(v2 != "silent" for v2 in verified.values())
        return {
            "ok": ok,
            "pumps": verified,
            "note": "TR 발송 + estop 래치 — 복구는 [약한 초기화] 또는 [세척]"
            if ok
            else "⚠️ 전 펌프 무응답 — 정지 도달을 확인하지 못했습니다. 24V 전원을 직접 차단하세요.",
        }
    finally:
        STATE["estop_in_progress"] = False


def _dispense_once(
    pump: int,
    in_port: int,
    volume_ul: float,
    *,
    asp_hz: int,
    disp_hz: int,
    slope: int,
) -> dict:
    """syringe 스텝 1회 — 서버 조립과 동일 형태(I{in}→A{steps}→O{out}→A0·명시 속도).

    배출 구멍 = **그 펌프의** output 역할 포트(포트 매핑 파생 — outputPortOf 미러).
    """
    spec = _spec()
    cmd = EngineDispenseCommand(
        pump_addr=pump,
        volume_ul=float(volume_ul),
        steps=spec.steps_for_volume_ul(float(volume_ul)),
        spec=spec,
        in_port=in_port,
        out_port=_role_port(pump, "output"),
        aspirate_speed_hz=asp_hz,
        dispense_speed_hz=disp_hz,
        slope=slope,
    )
    res = STATE["adapter"].dispense(cmd)
    return {**_result_json(res.raw_error_code, res.detail), "steps": cmd.steps}


# ── 연결 ───────────────────────────────────────────────────────────────────────
def _probe_port_for_pumps(port: str) -> list[int]:
    """포트 하나를 열어 주소 1..9 프로브 — daemon `autodetect_bus` 와 동일 판정(응답=장착).

    daemon 의 `open_bus_probe` 는 프로브용 어댑터를 닫지 않는다(부팅 1회라 무해). 이 툴은
    버튼으로 반복 실행되므로 **판정 로직은 그대로 두고 뒷정리(close)만 추가**한다.
    """
    probe_adapter = Sy01bEngineAdapter(port=port, logger=LOGGER)
    STATE["probe_adapter"] = probe_adapter  # estop 의 협조 중단 대상(NEW-1).
    try:
        return discover_pumps(probe_adapter.probe, scan_addresses())
    finally:
        STATE["probe_adapter"] = None
        probe_adapter.close()


def _connect_core(manual: str = "", *, quiet: bool = False) -> "tuple[dict, int]":
    """자동 인식 본체 — **호출자가 OP_LOCK 을 쥔 상태**에서 부른다(엔드포인트·자동 연결 루프 공용).

    반환 = (payload, http_status). quiet=True(자동 루프)면 실패 로그를 줄인다(주기 재시도라 스팸 방지).
    """
    # 같은 버스 충돌 방어(검증 P0-5) — 이 컴퓨터에서 운영 데몬(senlytd)이 돌고 있으면 같은
    #   tty 를 동시에 열게 된다(pyserial 기본 = 배타 잠금 없음 → 프레임 교차·상태 오독).
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "senlytd"], capture_output=True, text=True, timeout=3
        )
        if r.stdout.strip() == "active":
            return ({"ok": False, "error": "운영 데몬(senlytd)이 실행 중입니다 — 같은 펌프 버스를 두 프로세스가 잡으면 프레임이 섞입니다. 먼저 `sudo systemctl stop senlytd` 후 정비하세요."}, 409)
    except Exception:  # noqa: BLE001 — systemctl 부재(맥/일반PC) = 검사 생략.
        pass
    # 기존 연결 정리(재인식 지원) — **분리 먼저, close 나중**(검증 P2-5).
    STATE["connecting"] = True  # estop 이 temp 어댑터로 같은 tty 를 겹쳐 열지 않게(P2-5).
    try:
        old, STATE["adapter"] = STATE["adapter"], None
        STATE["pumps"] = []
        STATE["port"] = None
        if old is not None:
            old.close()
        # 후보 열거 — daemon 부팅과 동일(env SENLYT_SERIAL_PORT 우선·알려진 어댑터 VID/PID 우선).
        cands = [manual] if manual else list_candidate_ports()
        if not cands:
            return ({"ok": False, "error": "시리얼 포트 후보가 없습니다 — USB-RS485 어댑터 연결을 확인하세요."}, 404)
        if not quiet:
            _log("info", "펌프 자동 인식 시작", candidates=cands[:8])
        found_port, found_pumps = None, []
        for cand in cands:
            try:
                ids = _probe_port_for_pumps(cand)
            except Exception as e:  # noqa: BLE001 — 포트 열기 실패 = 다음 후보(autodetect_bus 동일).
                if not quiet:
                    _log("warn", "포트 프로브 실패 — 다음 후보로", port=cand, reason=str(e)[:120])
                continue
            if ids:
                found_port, found_pumps = cand, ids
                break
        if found_port is None:
            return ({"ok": False, "error": "어느 포트에서도 펌프가 응답하지 않습니다 — 24V 전원·RS485 배선·DIP 주소를 확인하세요.", "candidates": cands}, 404)
        # 본 어댑터 — daemon bootstrap 과 동일 구성(핫플러그 자가 회복 port_resolver 포함).
        STATE["adapter"] = Sy01bEngineAdapter(
            port=found_port, logger=LOGGER, port_resolver=list_candidate_ports
        )
        STATE["port"] = found_port
        STATE["last_port"] = found_port
        STATE["pumps"] = found_pumps
        # 새 연결 = 새 기계일 수 있다 — 용량 확인·초기화를 다시 요구(P1-5·P1-2).
        STATE["capacity_confirmed"] = False
        STATE["initialized_after_connect"] = False
        # ⚠️ estop 래치는 **해제하지 않는다**(리뷰 P1-3) — 어댑터 객체가 새것이어도 물리 펌프는
        #   같은 물건이고 플런저는 어중간한 위치다. 복구는 [약한 초기화]/[세척] 성공뿐.
        _log("info", "펌프 인식 완료", port=found_port, pumps=found_pumps)
        return ({"ok": True, "port": found_port, "pumps": found_pumps}, 200)
    finally:
        STATE["connecting"] = False


@app.post("/api/connect")
def api_connect():
    """수동 재인식(헤더 ⟳) — USB 교체 직후 등. 평시 연결은 자동 연결 루프가 담당한다."""
    lock = _busy_guard("자동 인식")
    if lock is None:
        return jsonify({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}), 409
    try:
        body = request.get_json(silent=True) or {}
        payload, status = _connect_core((body.get("port") or "").strip())
        return jsonify(payload), status
    finally:
        _release(lock)


def _auto_connect_loop() -> None:
    """자동 연결 — 데몬 부팅 미러: 시작·연결 상실 시 주기적으로 자동 인식(수동 버튼 불필요).

    미연결 상태에서만 시도하고, 정비 작업 중(OP_LOCK 점유)엔 건드리지 않는다(non-blocking).
    성공 후에는 어댑터 자체의 핫플러그 자가 회복(port_resolver)이 이어받는다.
    실패 사유는 **상태 전이 시 1회만** 로깅(NEW-4 — 3초 주기 스팸 방지)하고, senlytd 활성처럼
    금방 안 바뀌는 사유면 재시도 간격을 30초로 늘린다(systemctl fork 스팸 방지).
    """
    last_reason = None
    while True:
        sleep_s = 3.0
        try:
            if STATE["adapter"] is None:
                lock = _busy_guard("자동 연결")
                if lock is not None:
                    try:
                        if STATE["adapter"] is None:  # 락 획득 사이 수동 연결 완료 가능 — 재확인.
                            payload, _status = _connect_core(quiet=True)
                            reason = None if payload.get("ok") else payload.get("error", "")[:80]
                            if reason != last_reason:
                                if reason:
                                    _log("info", "자동 연결 대기 — 사유", reason=reason)
                                last_reason = reason
                            if reason and "senlytd" in reason:
                                sleep_s = 30.0  # 운영 데몬 활성 = 금방 안 바뀜 — 백오프.
                    finally:
                        _release(lock)
        except Exception as e:  # noqa: BLE001 — 루프 예외 = 스레드 무음 사망(NEW-2) 방지.
            _log("warn", "자동 연결 루프 오류 — 계속 재시도", reason=str(e)[:120])
            sleep_s = 10.0
        time.sleep(sleep_s)


@app.get("/api/state")
def api_state():
    now = time.time()
    vo = STATE["valve_open_until"]
    return jsonify(
        {
            "connected": STATE["adapter"] is not None,
            "port": STATE["port"],
            "pumps": STATE["pumps"],
            "pumpLabels": {str(p): _pump_label(p) for p in STATE["pumps"]},
            "mode": STATE["mode"],
            "sensorium": STATE["sensorium"],
            "sensoriumLabel": _version()["label"],
            "aiStampSource": AI_STAMP_SOURCE,  # "adapter"=어댑터 정본 / "mirror"=미러 폴백(표기용)
            "versions": [
                {"id": k, "label": v["label"], "family": v["family"], "pumps": v["pumps"],
                 "pumpModel": v["pumpModel"], "aiModel": v["aiModel"]}
                for k, v in SENSORIUM_VERSIONS.items()
            ],
            "capacityMl": STATE["capacity_ml"],
            "capacityConfirmed": STATE["capacity_confirmed"],
            "pumpPorts": {str(a): {str(p): liq for p, liq in layout.items()}
                          for a, layout in STATE["pump_ports"].items()},
            "roleLabels": ROLE_LABELS,
            # 액체 카탈로그(현재 계열) — 포트 매핑 select 선택지(admin catalogFor 미러).
            "liquidCatalog": (
                [{"value": k, "label": v} for k, v in _FLAVOR_LIQUID_KO.items()]
                if STATE["mode"] == "flavor"
                else [{"value": k, "label": ko} for k, ko in _FRAGRANCE_NOTES_KO]
            ),
            "busy": STATE["busy"],
            "estop": STATE["estop"],
            "capacities": sorted(VALID_SYRINGE_CAPACITIES_ML),
            # 밸브 — flavor 전용 노출(admin: fragrance 에선 섹션 숨김). 낙관 표시(발행 시각 기반).
            "valveAvailable": STATE["valve"] not in ("uninit", None),
            "valveError": STATE["valve_err"],
            "valveOpen": {b: max(0, round(t - now)) for b, t in vo.items()},
            "filling": STATE["filling"],
        }
    )


@app.get("/api/tiles")
def api_tiles():
    """액체 타일 — admin 진단 도구의 포트 선택 UI 재료([포트 매핑] 현재 배치 기준·발견 펌프만)."""
    tiles = _tiles()
    return jsonify({"tiles": tiles, "seqTargets": _seq_targets(tiles)})


@app.post("/api/settings")
def api_settings():
    body = request.get_json(silent=True) or {}
    ver = body.get("sensorium")
    if ver is not None:
        if ver not in SENSORIUM_VERSIONS:
            return jsonify({"ok": False, "error": f"등록되지 않은 센소리움 버전입니다: {ver}"}), 400
        if ver != STATE["sensorium"]:
            if STATE["busy"]:
                return jsonify({"ok": False, "error": f"작업 진행 중({STATE['busy']}) — 센소리움 버전을 바꿀 수 없습니다."}), 409
            # 버전 전환 = 계약 전환 — 계열·펌프 구성·포트 시드·용량 기본이 함께 바뀐다(규약 문서).
            v = SENSORIUM_VERSIONS[ver]
            STATE["sensorium"] = ver
            STATE["mode"] = v["family"]
            STATE["capacity_ml"] = v["capacityMl"]
            STATE["capacity_confirmed"] = False  # 버전이 바뀌면 실물 재확인.
            STATE["pump_ports"] = _seed_pump_ports(v["family"], v["pumps"])
    cap = body.get("capacityMl")
    if isinstance(cap, (int, float)) and not isinstance(cap, bool):
        if float(cap) not in VALID_SYRINGE_CAPACITIES_ML:
            return jsonify({"ok": False, "error": f"유효 시린지 용량이 아닙니다: {cap}"}), 400
        if float(cap) != STATE["capacity_ml"]:
            # ⛔ 작업 중 용량 변경 금지(리뷰 P1-1) — 진행 중 필링/세척 스레드의 _spec() 이 새 값을
            #   읽어 과다흡입 스텝(용량 반비례)을 만든다. 버전 전환·포트맵과 같은 규약으로 409.
            if STATE["busy"]:
                return jsonify({"ok": False, "error": f"작업 진행 중({STATE['busy']}) — 시린지 용량을 바꿀 수 없습니다."}), 409
            STATE["capacity_confirmed"] = False  # 값이 바뀌면 재확인(P1-5).
        STATE["capacity_ml"] = float(cap)
    if body.get("confirmCapacity") is True:
        STATE["capacity_confirmed"] = True
    elif body.get("confirmCapacity") is False:
        STATE["capacity_confirmed"] = False  # 체크 해제도 서버에 반영(리뷰 P2-6).
    return api_state()


@app.post("/api/portmap")
def api_portmap():
    """포트 매핑 편집 — admin 설정 '포트 매핑'의 미러(펌프 1대 전체 레이아웃 저장 또는 시드 리셋).

    검증은 admin `clampPorts`+해석기 불변식 미러: 액체 키 정규화(소문자·32자), 같은 펌프 내
    중복 액체 거부, output·air·cleaning/alcohol 각 정확히 1개(초기화·퍼지·세척의 전제).
    """
    body = request.get_json(silent=True) or {}
    pump = body.get("pump")
    version_pumps = _version()["pumps"]
    if pump not in version_pumps:
        return jsonify({"ok": False, "error": f"이 센소리움 버전의 펌프가 아닙니다: {pump} (버전 펌프: {version_pumps})"}), 400
    if STATE["busy"]:
        return jsonify({"ok": False, "error": f"작업 진행 중({STATE['busy']}) — 포트 매핑을 바꿀 수 없습니다."}), 409
    if body.get("reset") is True:
        STATE["pump_ports"][pump] = _seed_layout(STATE["mode"], pump)
        return api_state()
    raw = body.get("ports")
    if not isinstance(raw, dict):
        return jsonify({"ok": False, "error": "ports 는 {\"1\": 액체|null, ...} 형태여야 합니다."}), 400
    layout: dict[int, str] = {}
    seen: set[str] = set()
    for k, v in raw.items():
        try:
            port = int(k)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"포트 키가 정수가 아닙니다: {k}"}), 400
        if not 1 <= port <= MAX_PORT:
            return jsonify({"ok": False, "error": f"포트는 1~{MAX_PORT} 이어야 합니다: {port}"}), 400
        if v is None or (isinstance(v, str) and not v.strip()):
            continue  # 비움.
        if not isinstance(v, str):
            return jsonify({"ok": False, "error": f"P{port} 액체 값이 문자열이 아닙니다."}), 400
        liquid = v.strip().lower()[:32]  # normalizeLiquidKey + 32자 절단(clampPorts 미러).
        if liquid in seen:
            return jsonify({"ok": False, "error": f"같은 액체를 두 포트에 중복 지정할 수 없습니다: {liquid}"}), 400
        seen.add(liquid)
        layout[port] = liquid
    outputs = [p for p, l in layout.items() if l == "output"]
    airs = [p for p, l in layout.items() if l == "air"]
    cleans = [p for p, l in layout.items() if l in ("cleaning", "alcohol")]
    if len(outputs) != 1:
        return jsonify({"ok": False, "error": f"배출(output)은 정확히 1개여야 합니다 (현재 {len(outputs)}개)."}), 400
    if len(airs) != 1:
        return jsonify({"ok": False, "error": f"공기(air)는 정확히 1개여야 합니다 (현재 {len(airs)}개) — 초기화·퍼지의 전제입니다."}), 400
    # 정확히 1개 강제(리뷰 P2-4) — 0개면 세척이 모드 기본 포트로 폴백해, 그 포트에 다른 액체가
    #   매핑돼 있을 때 **그 액체를 알코올인 줄 알고 전량 소모**한다(조용한 오동작). fail-closed.
    if len(cleans) != 1:
        return jsonify({"ok": False, "error": f"세척액/알코올 역할은 펌프당 정확히 1개여야 합니다 (현재 {len(cleans)}개) — 세척 시퀀스의 전제입니다."}), 400
    STATE["pump_ports"][pump] = layout
    _log("info", "포트 매핑 갱신", pump=pump, ports={str(p): l for p, l in sorted(layout.items())})
    return api_state()


# ── 상태/건강 ──────────────────────────────────────────────────────────────────
@app.get("/api/health")
def api_health():
    a, err = _require_adapter()
    if err:
        return err
    # idle 게이트 미러 — daemon 도 제조/정비 중엔 하트비트 프로브를 건너뛴다(모션 중 버스 잡음 회피).
    lock = _busy_guard("상태 점검")
    if lock is None:
        return jsonify({"ok": True, "busy": STATE["busy"], "pumps": {}})
    try:
        out = {str(p): a.health_probe(p) for p in STATE["pumps"]}
        return jsonify({"ok": True, "busy": None, "pumps": out})
    finally:
        _release(lock)


# ── ① 펌프 제어 (admin pump-control 미러) ─────────────────────────────────────
@app.post("/api/plunger")
def api_plunger():
    """시린지 흡입·배출 — admin ▼전량 흡입/▲전량 배출 (run_op + 밸브 회전 wire.ts 파생 미러)."""
    a, err = _require_adapter()
    if err:
        return err
    gate = _motion_gate()
    if gate:
        return gate
    body = request.get_json(silent=True) or {}
    op = body.get("op")  # "plungerFull" | "plungerHome"
    pump = body.get("pump")
    if op not in ("plungerFull", "plungerHome"):
        return jsonify({"ok": False, "error": "op 는 plungerFull|plungerHome 중 하나여야 합니다."}), 400
    if pump not in STATE["pumps"]:
        return jsonify({"ok": False, "error": f"연결된 펌프가 아닙니다: {pump}"}), 400
    # wire.ts:1232~ 파생 미러 — plungerFull=**그 펌프의** air 회전 · plungerHome=output 회전
    #   (admin 처럼 pumpPorts 레이아웃 우선·없으면 모드 기본 폴백).
    valve_port = _role_port(pump, "air" if op == "plungerFull" else "output")
    cmd = EngineOpCommand(
        pump_addr=pump,
        op=OP_PLUNGER_FULL if op == "plungerFull" else OP_PLUNGER_HOME,
        spec=_spec(),
        valve_port=valve_port,
    )
    label = f"{_pump_label(pump)} {'전량 흡입' if op == 'plungerFull' else '전량 배출'}"
    lock = _busy_guard(label)
    if lock is None:
        return jsonify({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}), 409
    try:
        res = a.run_op(cmd)
        return jsonify(_result_json(res.raw_error_code, res.detail))
    finally:
        _release(lock)


@app.post("/api/weak-init")
def api_weak_init():
    """약한 초기화 — 전 펌프 동시 홈(admin forceInitAll 미러 · estop 복구 경로).

    admin 은 estop 신호를 먼저 해제하고 전 펌프 initialize 스텝(stage:0)을 발행하며,
    pi 는 이를 합쳐 `initialize_polled`(주소지정 발사 + Bit5 폴 조기완료)로 실행한다 —
    여기서도 같은 함수를 같은 인자(air/output 포트)로 부른다.
    """
    a, err = _require_adapter()
    if err:
        return err
    gate = _motion_gate(is_recovery=True)
    if gate:
        return gate
    lock = _busy_guard("약한 초기화")
    if lock is None:
        return jsonify({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}), 409
    try:
        addrs = list(STATE["pumps"])
        if not addrs:
            return jsonify({"ok": False, "error": "초기화할 펌프가 없습니다."}), 400
        t0 = time.monotonic()
        # 펌프별 포트(ports_by_addr) — 데몬 시퀀서가 넘기는 것과 동일 인자(재검증 P2-2 해소).
        results = a.initialize_polled(
            addrs, _spec(),
            ports_by_addr={p: (_role_port(p, "air"), _role_port(p, "output")) for p in addrs},
        )
        elapsed = round(time.monotonic() - t0, 1)
        per = {str(addr): _result_json(code) for addr, code in results.items()}
        ok = all(code == 0 for code in results.values())
        # 복구 경로 — **성공했을 때만** 툴 래치를 열고(fail-open 방지·P2-a) 첫 정비 게이트도 연다.
        if ok:
            STATE["estop"] = False
            STATE["initialized_after_connect"] = True
        return jsonify({"ok": ok, "elapsedS": elapsed, "results": per})
    finally:
        _release(lock)


@app.post("/api/clean")
def api_clean():
    """🧼 세척 — admin `cleaningSteps` 와 동일 시퀀스를 로컬에서 실행.

    시퀀스(maintenanceSteps.ts 미러):
      phase 0. 약한 초기화(전 펌프) — admin 세척 모달 "펌프를 초기화하고 세척 사이클을 실행"
      phase 1. 알코올 펌핑 — 회차마다 전 펌프 **동시**(stage 병렬 = ThreadPool·L2 시분할 버스),
               각 펌프 자기 세척액 포트에서 전량(1 스트로크) 흡입 → 배출 × alcoholCount(기본 2)
      phase 2. 에어 퍼지(**식향 한정** — v1.1.0 패리티) — air 포트 전량 흡입→배출 × purgeCount(기본 3)

    estop 복구 경로("복구는 [약한 초기화 & 세척]")라 래치 중에도 허용, 성공 시 래치 해제.
    """
    a, err = _require_adapter()
    if err:
        return err
    gate = _motion_gate(is_recovery=True)
    if gate:
        return gate
    body = request.get_json(silent=True) or {}
    alcohol = body.get("alcoholCount", CLEAN_ALCOHOL_DEFAULT)
    purge = body.get("purgeCount", CLEAN_PURGE_DEFAULT)
    if isinstance(alcohol, bool) or not isinstance(alcohol, (int, float)):
        alcohol = CLEAN_ALCOHOL_DEFAULT
    if isinstance(purge, bool) or not isinstance(purge, (int, float)):
        purge = CLEAN_PURGE_DEFAULT
    alcohol = max(1, min(MAX_CLEAN_COUNT, int(alcohol)))  # cleaningSteps clamp 미러(1~10).
    purge = max(0, min(MAX_CLEAN_COUNT, int(purge)))  # 0 = 세척만(퍼지 생략) 허용 — admin 주석 동일.
    lock = _busy_guard("세척")
    if lock is None:
        return jsonify({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}), 409
    try:
        addrs = list(STATE["pumps"])
        if not addrs:
            return jsonify({"ok": False, "error": "세척할 펌프가 없습니다."}), 400
        spec = _spec()
        # 1스트로크 부피 — admin `cleaningSteps` 는 `defaultSyringeCapacityMl(mode)*1000` = **고정
        #   500µL**(양 모드 공통 기본 용량)이다(재검증 P2-g — 설정 용량 전량으로 하면 1.25mL 기기
        #   에서 2.5배 과다). 미러 = 500µL 고정, 단 더 작은 시린지에선 게이트 상한으로 클램프.
        max_ul = min(500.0, spec.max_volume_ul)
        t0 = time.monotonic()
        # phase 0 — 초기화(estop 래치도 어댑터가 clear) — 펌프별 포트.
        init_results = a.initialize_polled(
            addrs, spec,
            ports_by_addr={p: (_role_port(p, "air"), _role_port(p, "output")) for p in addrs},
        )
        report: dict = {"initialize": {str(p): _result_json(c) for p, c in init_results.items()}, "rounds": []}
        ok_pumps = [p for p in addrs if init_results.get(p) == 0]
        if not ok_pumps:
            return jsonify({"ok": False, "error": "초기화에 실패해 세척을 중단합니다.", **report})
        if all(c == 0 for c in init_results.values()):
            STATE["estop"] = False  # 복구 성공 — 툴 래치 해제 + 첫 정비 게이트 개방.
            STATE["initialized_after_connect"] = True

        def run_round(kind: str, role: str) -> dict:
            """한 회차 — 전 펌프 동시(pi stage 병렬과 동일), 흡입 포트는 **펌프별 역할 포트**
            (세척액 = 그 펌프 매핑의 cleaning/alcohol — 서버 cleaningPortOf 해석 미러)."""
            with ThreadPoolExecutor(max_workers=len(ok_pumps)) as ex:
                futs = {
                    p: ex.submit(
                        _dispense_once,
                        p,
                        _role_port(p, role),
                        max_ul,
                        asp_hz=ASPIRATE_SPEED_DEFAULT_HZ,
                        disp_hz=DISPENSE_SPEED_DEFAULT_HZ,
                        slope=SLOPE_DEFAULT,
                    )
                    for p in ok_pumps
                }
                return {"kind": kind, "results": {str(p): f.result() for p, f in futs.items()}}

        aborted = False
        for _ in range(alcohol):
            if STATE["estop"] or STATE["estop_in_progress"]:
                aborted = True
                break
            report["rounds"].append(run_round("cleaning", "cleaning"))
        if STATE["mode"] == "flavor" and not aborted:  # 퍼지 = v1.1.0 flavor 전용(패리티).
            for _ in range(purge):
                if STATE["estop"] or STATE["estop_in_progress"]:
                    aborted = True
                    break
                report["rounds"].append(run_round("air", "air"))
        all_ok = (not aborted) and all(
            r2["ok"] for rd in report["rounds"] for r2 in rd["results"].values()
        )
        report.update(
            {
                "ok": all_ok,
                "aborted": aborted,
                "elapsedS": round(time.monotonic() - t0, 1),
                "alcoholCount": alcohol,
                "purgeCount": purge if STATE["mode"] == "flavor" else 0,
            }
        )
        return jsonify(report)
    finally:
        _release(lock)


@app.post("/api/estop")
def api_estop():
    """긴급 정지(전체) — daemon 감시 스레드와 동일 호출 + 도달 검증 + 밸브 즉시 닫힘. 락 안 탄다."""
    return jsonify(_do_estop(list(STATE["pumps"])))


# ── ② 밸브 제어 (admin valve-control 미러 · flavor 전용) ───────────────────────
@app.post("/api/valve")
def api_valve():
    """기주 솔레노이드 밸브 — ON(10s 자동닫힘)/OFF/N초 열기. 상호배타·자동닫힘은 pi 어댑터 규약."""
    if STATE["mode"] != "flavor":
        return jsonify({"ok": False, "error": "밸브 제어는 식향 모드 전용입니다."}), 400
    v = _valve_adapter()
    if v is None:
        return jsonify({"ok": False, "error": f"밸브(GPIO)를 쓸 수 없습니다 — 라즈베리파이에서만 지원. ({STATE['valve_err']})"}), 400
    body = request.get_json(silent=True) or {}
    action = body.get("action")  # "latch_on" | "off" | "open_for"
    base = body.get("base")
    if base not in VALVE_BASES_LABEL:
        return jsonify({"ok": False, "error": "base 는 sour|normal 중 하나여야 합니다."}), 400
    # estop 게이트(재검증 P1-c) — 서버는 estop 활성 시 **모든** 정비 발행을 409 로 거부한다
    #   (commands route `estop_active`) — 밸브도 예외가 아니다. 닫기(off)만은 항상 허용(안전 방향).
    if action != "off" and (STATE["estop"] or STATE["estop_in_progress"]):
        return jsonify({"ok": False, "error": "긴급 정지 래치 상태 — 밸브 개방이 잠겼습니다. [약한 초기화] 또는 [세척]으로 복구하세요."}), 409
    label = VALVE_BASES_LABEL[base]
    if action == "off":
        v.close_all()
        STATE["valve_open_until"] = {"sour": 0.0, "normal": 0.0}
        return jsonify({"ok": True, "note": f"{label} 밸브를 닫았습니다."})
    if action == "latch_on":
        res = v.open_latch(base, float(VALVE_LATCH_SEC))
        if res.ok:
            # 상호배타 미러(pi L3 동일) — 한쪽 ON 은 다른 쪽을 닫는다.
            STATE["valve_open_until"] = {"sour": 0.0, "normal": 0.0, base: time.time() + VALVE_LATCH_SEC}
        return jsonify({"ok": res.ok, "note": f"{label} 밸브를 열었습니다 ({VALVE_LATCH_SEC}초 뒤 자동 닫힘)." if res.ok else f"밸브 개방 실패: {res.detail}"})
    if action == "open_for":
        sec = body.get("sec", 3)
        if isinstance(sec, bool) or not isinstance(sec, (int, float)):
            sec = 3
        sec = max(1, min(10, int(sec)))  # UI 1~10s(admin 확정) — pi max_open_sec 15s 는 안전천장.
        res = v.dispense_volume(base, 0.0, open_sec=float(sec))  # 블로킹 — pi finally 닫힘.
        STATE["valve_open_until"] = {"sour": 0.0, "normal": 0.0}
        return jsonify({"ok": res.ok, "note": f"{label} 밸브를 {sec}초 열었다 닫았습니다." if res.ok else f"밸브 개방 실패: {res.detail}"})
    return jsonify({"ok": False, "error": "action 은 latch_on|off|open_for 중 하나여야 합니다."}), 400


# ── ③ 진단 도구 · 향료 필링 (admin DiagTool 미러) ──────────────────────────────
def _run_filling(targets: list[dict], volume_ul: float, asp: int, disp: int, lock) -> None:
    """필링 실행 스레드 — (펌프, 포트) 순서 직렬, 진행을 STATE['filling'] 에 실시간 기록.

    admin 은 한 봉투(직렬 stage)로 발행하고 하트비트 편승 jobProgress(10~15s 해상도)로 현재
    포트를 표시한다 — 이 툴은 로컬이라 스텝 완료 즉시 갱신된다(같은 개념·더 촘촘한 해상도).
    """
    try:
        fill = STATE["filling"]
        for i, t in enumerate(targets):
            if STATE["estop"] or STATE["estop_in_progress"]:
                fill["outcome"] = "aborted"
                break
            fill["current"] = i
            r = _dispense_once(
                t["pump"], t["port"], volume_ul, asp_hz=asp, disp_hz=disp, slope=SLOPE_DEFAULT
            )
            fill["results"].append({**t, **r})
        else:
            # 마지막 스텝 직후 estop 창(리뷰 P2-7) — 완료 직전 정지가 걸렸으면 done 으로 위장하지 않는다.
            if STATE["estop"] or STATE["estop_in_progress"]:
                fill["outcome"] = "aborted"
            else:
                fill["outcome"] = "done" if all(r["ok"] for r in fill["results"]) else "failed"
    except Exception as e:  # noqa: BLE001 — 스레드라 예외를 상태로 남긴다(조용한 실종 방지).
        fill["outcome"] = "failed"
        fill["error"] = str(e)[:200]
    finally:
        fill["active"] = False
        fill["current"] = None
        _release(lock)


@app.post("/api/filling")
def api_filling():
    """향료 필링 시작 — admin `runFilling` 미러(선택 타일 1개 = 개별 실행 · 전체 = 순차 필링).

    body.targets = [{pump, port, label}] — 타일 그대로(선택 포트/순차/재필링 모두 이 한 경로,
    admin 과 동일). 비동기 시작 후 진행은 `/api/state` 의 filling 으로 폴링(순차 패널 미러).
    """
    a, err = _require_adapter()
    if err:
        return err
    gate = _motion_gate()
    if gate:
        return gate
    body = request.get_json(silent=True) or {}
    raw_targets = body.get("targets")
    volume_ul = body.get("volumeUl")
    if not isinstance(raw_targets, list) or not raw_targets:
        return jsonify({"ok": False, "error": "targets 가 비었습니다 — 포트 타일을 선택하세요."}), 400
    targets: list[dict] = []
    for t in raw_targets:
        pump, port = t.get("pump"), t.get("port")
        if pump not in STATE["pumps"] or not _valid_port(port):
            return jsonify({"ok": False, "error": f"잘못된 대상: 펌프 {pump} 포트 {port}"}), 400
        if port == _role_port(pump, "output"):
            return jsonify({"ok": False, "error": f"P{pump}의 배출(output) 포트({port})는 흡입 대상이 될 수 없습니다."}), 400
        targets.append({"pump": pump, "port": port,
                        "label": str(t.get("label") or f"P{pump}·{port}")[:40],
                        "pumpLabel": _pump_label(pump)})
    # (펌프, 포트) 정렬 — admin runFilling 의 결정론 순서(P1 전부 → P2 전부) 미러.
    targets.sort(key=lambda t: (t["pump"], t["port"]))
    if isinstance(volume_ul, bool) or not isinstance(volume_ul, (int, float)):
        return jsonify({"ok": False, "error": "volumeUl 은 숫자여야 합니다."}), 400
    spec = _spec()
    # 흡입량 = admin 슬라이더 범위 [용량/5, 용량] 클램프(표시·발행 동일 규약).
    volume_ul = min(spec.max_volume_ul, max(spec.max_volume_ul / 5, float(volume_ul)))
    # 클램프 후 재검증 — assert 금지(python -O 에서 제거·재검증 P2-n). 도달 시 명시 400.
    if not is_volume_within_gate(float(volume_ul), spec):
        return jsonify({"ok": False, "error": f"부피 게이트 위반: 0 < {volume_ul}µL ≤ {spec.max_volume_ul:.0f}µL"}), 400
    asp = _clamp("aspirateSpeedHz", body.get("aspirateSpeedHz"), DIAG_ASPIRATE_DEFAULT_HZ)
    disp = _clamp("dispenseSpeedHz", body.get("dispenseSpeedHz"), DISPENSE_SPEED_DEFAULT_HZ)
    lock = _busy_guard(f"향료 필링 ({len(targets)}포트)")
    if lock is None:
        return jsonify({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}), 409
    STATE["filling"] = {
        "active": True, "current": 0, "targets": targets, "results": [], "outcome": None,
        "error": None,  # 키를 미리 둔다 — 직렬화 중 새 키 추가는 dict 크기 변경 RuntimeError(P2-8).
        "volumeUl": volume_ul, "aspirateSpeedHz": asp, "dispenseSpeedHz": disp,
    }
    try:
        th = threading.Thread(
            target=_run_filling, args=(targets, float(volume_ul), asp, disp, lock), daemon=True
        )
        th.start()
    except Exception as e:  # noqa: BLE001 — 스레드 기동 실패 시 락 영구 잠김 방지(리뷰 P2-2).
        STATE["filling"] = None
        _release(lock)
        return jsonify({"ok": False, "error": f"필링 시작 실패: {e}"}), 500
    return jsonify({"ok": True, "started": True, "count": len(targets)})


# ── 로그 ───────────────────────────────────────────────────────────────────────
@app.get("/api/logs")
def api_logs():
    try:
        since = int(request.args.get("since", "0"))
    except ValueError:
        since = 0
    with _LOG_LOCK:
        items = [r for r in _LOG_RING if r["seq"] > since]
    return jsonify({"logs": items, "last": items[-1]["seq"] if items else since})


# ── UI ─────────────────────────────────────────────────────────────────────────
PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>시린지펌프 정비 툴 v1.3.0</title>
<style>
  :root { --bg:#f5f4f0; --card:#fff; --ink:#232019; --sub:#6f6a5e; --line:#e3e0d8;
          --accent:#4f46e5; --danger:#c02626; --ok:#15803d; --warn:#b45309; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font-family:'Noto Sans KR',system-ui,sans-serif; font-size:15px; }
  header { padding:14px 20px; background:var(--card); border-bottom:1px solid var(--line);
           display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
  header h1 { margin:0; font-size:17px; }
  header .sub { color:var(--sub); font-size:12.5px; }
  main { max-width:980px; margin:0 auto; padding:16px 20px 48px; display:grid; gap:14px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .card h2 { margin:0 0 10px; font-size:14.5px; }
  .card h3 { margin:14px 0 8px; font-size:13.5px; color:var(--sub); }
  .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  button { border:1px solid var(--line); background:#faf9f6; color:var(--ink); border-radius:8px;
           padding:7px 12px; font-size:13.5px; cursor:pointer; font-family:inherit; }
  button:hover { border-color:var(--accent); }
  button:disabled { opacity:.45; cursor:not-allowed; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  button.danger  { background:var(--danger); border-color:var(--danger); color:#fff; font-weight:700; }
  select,input { border:1px solid var(--line); border-radius:8px; padding:6px 9px; font-size:13.5px;
                 font-family:inherit; background:#fff; color:var(--ink); width:auto; }
  input[type=number] { width:86px; }
  label { font-size:12.5px; color:var(--sub); display:flex; flex-direction:column; gap:3px; }
  table { width:100%; border-collapse:collapse; font-size:13.5px; }
  th,td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); }
  th { color:var(--sub); font-weight:600; font-size:12px; }
  .pill { display:inline-block; padding:2px 9px; border-radius:99px; font-size:12px; font-weight:600; }
  .pill.ok { background:#e7f5ec; color:var(--ok); }
  .pill.garbled { background:#fdf1e2; color:var(--warn); }
  .pill.silent { background:#fbe9e9; color:var(--danger); }
  .pill.unknown { background:#eee; color:var(--sub); }
  #msg { min-height:20px; font-size:13px; white-space:pre-line; }
  #msg.ok { color:var(--ok); } #msg.err { color:var(--danger); }
  #log { background:#171512; color:#d9d4c7; border-radius:8px; padding:10px 12px; height:220px;
         overflow-y:auto; font:12px/1.55 ui-monospace,monospace; white-space:pre-wrap; word-break:break-all; }
  #log .warn { color:#f2b96b; } #log .error { color:#f08c8c; } #log .debug { color:#8b867a; }
  .busy { color:var(--warn); font-weight:600; font-size:13px; }
  /* 섹션 네비 — admin MAINT_SECTIONS 미러 */
  .setnav { display:flex; gap:6px; flex-wrap:wrap; }
  .setnav button { border-radius:99px; padding:6px 14px; }
  .setnav button.on { background:var(--ink); border-color:var(--ink); color:#fff; }
  .desc { font-size:12.5px; color:var(--sub); margin-bottom:10px; }
  /* 액체 타일 그리드 — admin diaggrid 미러(펌프 경계 줄바꿈) */
  .tilegrid { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
  .tilegrid .rowbreak { flex-basis:100%; height:0; }
  .ptile { display:flex; flex-direction:column; align-items:flex-start; gap:2px;
           border:1px solid var(--line); background:#faf9f6; border-radius:8px;
           padding:7px 10px; font-size:12.5px; cursor:pointer; min-width:96px; }
  .ptile .pp { font-size:11px; color:var(--sub); font-family:ui-monospace,monospace; }
  .ptile.sel { border-color:var(--accent); background:#eef0fe; box-shadow:0 0 0 1px var(--accent) inset; }
  .sliderrow { display:flex; align-items:center; gap:10px; margin:6px 0; font-size:13px; }
  .sliderrow .sl { min-width:180px; }
  .sliderrow input[type=range] { flex:1; }
  .sliderrow .sv { min-width:84px; text-align:right; font-family:ui-monospace,monospace; font-size:12.5px; }
  .seqrow { display:flex; gap:8px; align-items:center; font-size:12.5px; padding:2px 0; }
  .seqrow .mk { width:24px; text-align:right; color:var(--sub); font-family:ui-monospace,monospace; }
  .seqrow .mk.cur { color:var(--accent); } .seqrow .mk.done { color:var(--ok); }
  .seqrow .lbl { flex:1; } .seqrow .pp { color:var(--sub); font-family:ui-monospace,monospace; font-size:11px; }
  .seqrow .chk { color:var(--sub); font-size:11.5px; }
</style></head><body>
<header>
  <h1>🔧 시린지펌프 정비 툴</h1>
  <span class="sub">v1.3.0 — admin 점검·유지보수 미러 · 운영 pi daemon(senlyt_pi) 코드 그대로</span>
  <span id="connInfo" class="sub" style="font-weight:600"></span>
  <button class="sm" style="padding:3px 9px;font-size:12px" title="USB 교체 직후 등 즉시 재인식" onclick="doConnect()">⟳ 다시 인식</button>
  <span id="busy" class="busy"></span>
</header>
<div id="estopBanner" style="display:none;background:var(--danger);color:#fff;padding:9px 20px;font-weight:700">
  ⛔ 긴급 정지 래치 상태 — 모션 버튼이 잠겼습니다. 복구는 [약한 초기화] 또는 [🧼 세척].
</div>
<main>
  <div id="msg" style="padding:0 2px"></div>

  <div class="card">
    <h2>설정</h2>
    <div class="row">
      <label>센소리움 버전 <select id="sensorium" onchange="pushSettings()"></select></label>
      <label>시린지 용량(mL) <select id="cap" onchange="pushSettings()"></select></label>
      <span class="sub" id="verInfo"></span>
    </div>
    <div class="desc" style="margin-top:6px">센소리움 버전 = 향료 팔레트·AI 모델·하드웨어 구성(펌프 수·포트 배치·용량)을 함께 약속하는 계약 단위 —
      버전을 바꾸면 펌프 구성과 포트 매핑이 그 버전 기준으로 초기화됩니다. 포트가 실제 배관과 다르면 [포트 매핑]에서 수정하세요.</div>
    <div class="row" style="margin-top:8px">
      <label style="flex-direction:row;align-items:center;gap:6px;font-size:13px">
        <input type="checkbox" id="capConfirm" onchange="confirmCapacity(this.checked)">
        실물 시린지 용량과 일치함을 확인했습니다 <b>(체크해야 모션 버튼이 열립니다)</b>
      </label>
    </div>
  </div>

  <nav class="setnav" id="setnav"></nav>

  <!-- ① 펌프 제어 -->
  <div class="card" id="sec-pump-control">
    <h2>펌프 제어</h2>
    <div class="desc">운영자 유지보수 액션 — 화면은 버튼만 누르고 실제 펌프 구동은 운영 어댑터(senlyt_pi)가 실행합니다.</div>
    <h3>기기 연결 상태</h3>
    <table id="connTbl"><tbody></tbody></table>
    <h3 id="plungerTitle">시린지 흡입 · 배출 (유지보수)</h3>
    <table id="pumpTbl"><tbody></tbody></table>
    <div class="row" style="margin-top:12px">
      <button class="primary" onclick="doWeakInit()">약한 초기화</button>
      <button onclick="doClean()">🧼 세척</button>
      <label>알코올 회수 <input id="alcoholCount" type="number" min="1" max="10" value="2"></label>
      <label id="purgeLabel">에어 퍼지 회수 <input id="purgeCount" type="number" min="0" max="10" value="3"></label>
      <button onclick="refreshHealth()">🩺 상태 점검</button>
      <button class="danger" onclick="doEstop()">⛔ 긴급 정지</button>
    </div>
  </div>

  <!-- ② 밸브 제어 (식향 전용) -->
  <div class="card" id="sec-valve-control" style="display:none">
    <h2>밸브 제어</h2>
    <div class="desc">신기주·베이스 기주 솔레노이드 밸브 — 한 번에 1개만 열립니다(상호배타). 모든 개방은 <b>최대 10초 뒤 자동 닫힘</b>(열림 방치 방지). 긴급 정지 시에도 즉시 닫힙니다.</div>
    <div id="valveUnavail" class="desc" style="display:none;color:var(--warn)"></div>
    <table id="valveTbl"><tbody>
      <tr><td style="width:110px"><b>신 기주</b></td><td>
        <span class="row">
          <span id="vstate-sour" class="sub" style="min-width:88px">닫힘</span>
          <button onclick="valveLatch('sour')">스위치 ON (10초)</button>
          <button onclick="valveOff('sour')">OFF</button>
          <label style="flex-direction:row;align-items:center;gap:6px">
            <input id="vsec-sour" type="number" min="1" max="10" value="3" style="width:64px">초
          </label>
          <button onclick="valveOpenFor('sour')">🚰 열었다 닫기</button>
        </span></td></tr>
      <tr><td><b>베이스 기주</b></td><td>
        <span class="row">
          <span id="vstate-normal" class="sub" style="min-width:88px">닫힘</span>
          <button onclick="valveLatch('normal')">스위치 ON (10초)</button>
          <button onclick="valveOff('normal')">OFF</button>
          <label style="flex-direction:row;align-items:center;gap:6px">
            <input id="vsec-normal" type="number" min="1" max="10" value="3" style="width:64px">초
          </label>
          <button onclick="valveOpenFor('normal')">🚰 열었다 닫기</button>
        </span></td></tr>
    </tbody></table>
  </div>

  <!-- ③ 진단 도구 · 향료 필링 (admin DiagTool 미러) -->
  <div class="card" id="sec-tube-diag" style="display:none">
    <h2>진단 도구 · 향료 필링</h2>
    <div class="desc">포트 매핑(시드 기본 배치)을 따르는 액체 타일 — 타일 선택 → 흡입/배출 속도·흡입량 조절 후 실행.
      배치가 실제 배관과 다르면 [포트 매핑 및 설정]에서 수정하세요 — 타일은 현재 매핑을 따릅니다.</div>
    <div id="tileGrid" class="tilegrid"></div>
    <div class="sliderrow"><span class="sl">흡입 속도 <span class="sub">500~5000 Hz</span></span>
      <input type="range" id="dAsp" min="500" max="5000" step="50" value="2000" oninput="$('dAspV').textContent=this.value+' Hz'">
      <span class="sv" id="dAspV">2000 Hz</span></div>
    <div class="sliderrow"><span class="sl">배출 속도 <span class="sub">500~6000 Hz</span></span>
      <input type="range" id="dDisp" min="500" max="6000" step="50" value="6000" oninput="$('dDispV').textContent=this.value+' Hz'">
      <span class="sv" id="dDispV">6000 Hz</span></div>
    <div class="sliderrow"><span class="sl">흡입량 <span class="sub" id="dVolRange"></span></span>
      <input type="range" id="dVol" oninput="$('dVolV').textContent=(+this.value).toFixed(2)+' mL'">
      <span class="sv" id="dVolV"></span></div>
    <div class="row" style="margin-top:10px">
      <button id="btnSelFill" onclick="fillSelected()">포트를 선택하세요</button>
      <button id="btnSeqFill" onclick="fillAll()">모든 포트 순차 흡입/배출(모든 향료 필링)</button>
    </div>
    <div id="seqPanel" style="display:none;margin-top:10px;border-top:1px solid var(--line);padding-top:10px">
      <div id="seqMsg" class="desc"></div>
      <div id="seqList"></div>
      <div class="row" id="refillRow" style="display:none;margin-top:8px">
        <button onclick="fillRefill()" id="btnRefill"></button>
      </div>
    </div>
  </div>

  <!-- ④ 포트 매핑 (admin 설정 '포트 매핑 및 설정' 미러) -->
  <div class="card" id="sec-port-map" style="display:none">
    <h2>포트 매핑 및 설정</h2>
    <div class="desc">어느 펌프 몇 번 구멍에 어떤 액체가 꽂혀 있는지 — 실제 배관(튜브)에 맞게 배정하세요.
      규칙: 펌프마다 배출(output) 1개·공기(air) 1개·세척액/알코올 1개 필수, 같은 펌프에 같은 액체 중복 불가.
      바꾸면 타일·초기화·세척·정비 밸브 회전이 전부 이 매핑을 따릅니다.</div>
    <div id="portMapWrap"></div>
  </div>

  <div class="card"><h2>로그 <span class="sub">(pi daemon 구조화 로그 그대로)</span>
    <label style="flex-direction:row;display:inline-flex;gap:4px;margin-left:10px;font-size:12px">
      <input type="checkbox" id="showDebug"> 시리얼 왕복(DEBUG)도 표시</label></h2>
    <div id="log"></div></div>
</main>
<script>
let S = {pumps:[], busy:null, connected:false, estop:false, capacityConfirmed:false, mode:'fragrance'};
let lastLog = 0, lastResults = {}, lastHealth = {};
let TILES = [], SEQ_TARGETS = [], selTileKey = null, refillKeys = new Set();
const tileKey = (t) => t.pump+':'+t.port;
const SECTIONS = [
  {id:'sec-pump-control', label:'펌프 제어'},
  {id:'sec-valve-control', label:'밸브 제어'},
  {id:'sec-tube-diag', label:'진단 도구 · 향료 필링'},
  {id:'sec-port-map', label:'포트 매핑 및 설정'},
];
// 액체 카탈로그(선택지) — 서버 시드와 동일 소스. 역할 4종 + 계열별 액체 한글 라벨.
const ROLE_OPTS = [['output','배출(output)'],['air','공기(air)'],['cleaning','세척액'],['alcohol','알코올(캐리어/세척)']];
let curSection = 'sec-pump-control';

const $ = (id) => document.getElementById(id);
function msg(t, ok) { const m=$('msg'); m.textContent=t||''; m.className=ok?'ok':'err'; }

async function jfetch(url, body) {
  try {
    const r = await fetch(url, body===undefined?{}:{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    try { return await r.json(); }
    catch(e){ return {ok:false, error:`서버 응답 해석 실패 (HTTP ${r.status})`}; }
  } catch(e) { return {ok:false, error:'서버 연결 실패 — 툴 프로세스 상태를 확인하세요', _net:true}; }
}

const HEALTH_LABEL = {ok:'연결됨 (실측)', garbled:'응답 깨짐 — 링크 품질 점검', silent:'무응답 — 전원·케이블 점검'};
function paintHealth(p, st){
  lastHealth[p]=st;
  const el=$('hp'+p); if(!el) return;
  el.className='pill '+(st||'unknown');
  el.textContent = st ? HEALTH_LABEL[st] : '?';
}

function renderNav(){
  const nav=$('setnav'); nav.innerHTML='';
  for (const s of SECTIONS) {
    if (s.id==='sec-valve-control' && S.mode!=='flavor') continue; // admin: flavor 전용 숨김
    const b=document.createElement('button');
    b.textContent=s.label; b.className=(curSection===s.id)?'on':'';
    b.onclick=()=>{ curSection=s.id; renderNav(); renderSections(); };
    nav.appendChild(b);
  }
  if (curSection==='sec-valve-control' && S.mode!=='flavor') curSection='sec-pump-control';
}
function renderSections(){
  for (const s of SECTIONS) $(s.id).style.display=(curSection===s.id)?'block':'none';
}

function renderState(s) {
  if (s._net) return;
  const modeChanged = s.mode!==S.mode;
  onConnectChange(s);
  S = s;
  $('busy').textContent = s.busy ? ('⏳ '+s.busy+' 진행 중…') : '';
  $('estopBanner').style.display = s.estop ? 'block' : 'none';
  $('connInfo').textContent = s.connected
    ? `🟢 연결됨: ${s.port} · 펌프 ${s.pumps.join(', ')}`
    : '⚪ 자동 인식 중… (USB-RS485·펌프 24V 전원 확인)';
  const sv=$('sensorium');
  if (sv.options.length===0 && s.versions)
    s.versions.forEach(v=>{const o=document.createElement('option');o.value=v.id;o.textContent=v.label;sv.appendChild(o);});
  if (document.activeElement!==sv) sv.value = s.sensorium;   // 드롭다운 조작 중 덮어쓰기 방지
  sv.disabled = !!s.busy;                                     // 작업 중 버전 전환 잠금(서버 409와 짝)
  const ver = (s.versions||[]).find(v=>v.id===s.sensorium);
  const verPumpsOk = !s.connected || !ver || JSON.stringify(ver.pumps)===JSON.stringify(s.pumps);
  $('verInfo').textContent = (ver ? `펌프 ${ver.pumps.join(',')} · 펌프 모델 ${ver.pumpModel} · AI 도장 ${ver.aiModel}` : '')
    + (s.aiStampSource==='mirror' ? ' (미러 폴백 — 어댑터 미설치)' : '')
    + (verPumpsOk ? '' : ` — ⚠️ 버전 펌프(${ver.pumps.join(',')})와 발견 펌프(${s.pumps.join(',')})가 다릅니다`);
  const cap=$('cap');
  if (cap.options.length===0) s.capacities.forEach(c=>{const o=document.createElement('option');o.value=c;o.textContent=c;cap.appendChild(o);});
  if (document.activeElement!==cap) cap.value = s.capacityMl;
  cap.disabled = !!s.busy;                                    // 작업 중 용량 변경 잠금(P1-1 서버 409와 짝)
  $('capConfirm').checked = !!s.capacityConfirmed;
  renderPortMap(s);
  // 흡입량 슬라이더 = admin DiagTool 미러(범위 [용량/5, 용량] mL·step 용량/10·기본 = 용량 전량).
  const capMl = s.capacityMl;   // ⚠️ 위 cap(엘리먼트)과 이름 분리 — const 재선언은 SyntaxError(P0-1)
  const dv=$('dVol');
  if (dv.dataset.cap !== String(capMl)) {
    dv.min=capMl/5; dv.max=capMl; dv.step=capMl/10; dv.value=capMl; dv.dataset.cap=String(capMl);
    $('dVolRange').textContent = `${(capMl/5).toFixed(2)}~${capMl.toFixed(2)} mL`;
    $('dVolV').textContent = capMl.toFixed(2)+' mL';
  }
  $('purgeLabel').style.display = s.mode==='flavor' ? '' : 'none'; // 퍼지 = 식향 전용(v1.1.0 패리티)
  if (modeChanged) loadTiles();
  renderNav(); renderSections();
  // 밸브 상태(낙관 표시)
  if (s.mode==='flavor') {
    $('valveUnavail').style.display = s.valveError ? 'block' : 'none';
    if (s.valveError) $('valveUnavail').textContent = '밸브(GPIO) 사용 불가: '+s.valveError;
    for (const b of ['sour','normal']) {
      const remain = (s.valveOpen||{})[b]||0;
      $('vstate-'+b).textContent = remain>0 ? `열림 · ${remain}초` : '닫힘';
      $('vstate-'+b).style.color = remain>0 ? 'var(--ok)' : 'var(--sub)';
    }
  }
  const motionLocked = !!s.busy || !s.capacityConfirmed;
  // 기기 연결 상태 표
  const ct=$('connTbl').querySelector('tbody'); ct.innerHTML='';
  for (const p of s.pumps) {
    const tr=document.createElement('tr');
    tr.innerHTML=`<td style="width:140px"><b>${s.pumpLabels[p]||('펌프 '+p)}</b> <span class="sub">(주소 ${p})</span></td>
      <td><span class="pill unknown" id="hp${p}">?</span></td>`;
    ct.appendChild(tr); paintHealth(p, lastHealth[p]);
  }
  // 시린지 흡입·배출 표
  $('plungerTitle').textContent = `시린지 흡입 · 배출 (유지보수 · ${s.pumps.length}펌프)`;
  const tb=$('pumpTbl').querySelector('tbody'); tb.innerHTML='';
  for (const p of s.pumps) {
    const dis = motionLocked||s.estop ? 'disabled' : '';
    const tr=document.createElement('tr');
    tr.innerHTML = `<td style="width:140px"><b>${s.pumpLabels[p]||('펌프 '+p)}</b></td>
      <td>
        <button ${dis} title="흡입 — 플런저가 아래로 내려갑니다" onclick="doPlunger('plungerFull',${p})">▼ 전량 흡입</button>
        <button ${dis} title="배출 — 플런저가 위로 올라갑니다" onclick="doPlunger('plungerHome',${p})">▲ 전량 배출</button>
      </td>
      <td id="res${p}" class="sub">${lastResults[p]||'—'}</td>`;
    tb.appendChild(tr);
  }
  renderSeqPanel(s.filling);
  const fillBusy = !!(s.filling && s.filling.active);
  $('btnSelFill').disabled = motionLocked || s.estop || fillBusy || !selTileKey;
  $('btnSelFill').textContent = selTileKey ? '선택 포트 흡입/배출' : '포트를 선택하세요';
  $('btnSeqFill').disabled = motionLocked || s.estop || fillBusy || TILES.length===0;
  $('btnSeqFill').textContent = `모든 포트 순차 흡입/배출(모든 향료 필링) (${SEQ_TARGETS.length})`;
}

async function loadTiles(){
  const r = await jfetch('/api/tiles');
  if (r.tiles) { TILES=r.tiles; SEQ_TARGETS=r.seqTargets||[]; selTileKey=null; renderTiles(); }
}

function renderTiles(){
  const g=$('tileGrid'); g.innerHTML='';
  let prevPump=null;
  for (const t of TILES) {
    if (prevPump!==null && t.pump!==prevPump) {           // 펌프 경계 줄바꿈(admin diaggrid 미러)
      const br=document.createElement('div'); br.className='rowbreak'; g.appendChild(br);
    }
    prevPump=t.pump;
    const k=tileKey(t);
    const b=document.createElement('button');
    b.className='ptile'+(selTileKey===k?' sel':'');
    b.innerHTML=`<span>${t.label}</span><span class="pp">P${t.pump}·${t.port}</span>`;
    b.onclick=()=>{ selTileKey=(selTileKey===k)?null:k; renderTiles(); refreshState(); };
    g.appendChild(b);
  }
  if (TILES.length===0) g.innerHTML='<span class="sub">매핑된 액체가 없습니다 — 펌프를 먼저 연결하세요.</span>';
}

let lastSeqJson='', lastRefillSize=-1;
function renderSeqPanel(f){
  const panel=$('seqPanel');
  if (!f) { panel.style.display='none'; return; }
  // 변경 없으면 재렌더 금지(리뷰 P2-1) — 2.5s 폴링마다 목록을 파괴/재생성하면 운영자의
  //   체크박스 클릭이 mousedown~mouseup 사이 재렌더에 씹힌다.
  const j = JSON.stringify(f);
  if (j===lastSeqJson && refillKeys.size===lastRefillSize) return;
  lastSeqJson=j; lastRefillSize=refillKeys.size;
  panel.style.display='block';
  const total=f.targets.length, doneN=f.results.length;
  const cur = f.active && f.current!==null ? f.targets[f.current] : null;
  $('seqMsg').innerHTML = f.active
    ? (cur ? `현재 <b style="color:var(--accent)">${cur.label} (P${cur.pump}·${cur.port})</b> 흡입/배출 진행 중… (${f.current+1}/${total}) — 순서대로 진행됩니다. 잘 필링되지 않은 포트는 체크박스를 눌러 두세요.`
           : '<b>흡입/배출 진행 중…</b>')
    : f.outcome==='done' ? '향료 필링 완료 — 체크한 포트가 있으면 아래 재필링 버튼으로 그 포트만 다시 필링하세요.'
    : f.outcome==='aborted' ? '향료 필링 중단됨(긴급 정지) — 체크 목록은 유지됩니다.'
    : `향료 필링 실패${f.error?' — '+f.error:''} (체크 목록은 유지됩니다 — 확인 후 다시 실행하세요)`;
  const list=$('seqList'); list.innerHTML='';
  f.targets.forEach((t,i)=>{
    const k=tileKey(t);
    const res=f.results[i];
    const rowDone = i < doneN && !(f.active && f.current===i);
    const rowCur = f.active && f.current===i;
    const row=document.createElement('label'); row.className='seqrow'; row.style.cursor='pointer';
    const mark = rowCur?'▶':(rowDone?(res&&!res.ok?'✗':'✓'):(i+1)+'.');
    row.innerHTML=`<span class="mk ${rowCur?'cur':(rowDone?'done':'')}">${mark}</span>
      <span class="lbl">${t.label} <span class="pp">P${t.pump}·${t.port}</span>${res&&!res.ok?` <span style="color:var(--danger)">${res.label}</span>`:''}</span>
      <input type="checkbox" ${refillKeys.has(k)?'checked':''} title="이 포트가 잘 필링되지 않았나요? 체크하면 재필링 목록에 누적됩니다.">
      <span class="chk">잘 안 됐어요</span>`;
    row.querySelector('input').onchange=(e)=>{ e.target.checked?refillKeys.add(k):refillKeys.delete(k); refreshState(); };
    list.appendChild(row);
  });
  $('refillRow').style.display = (!f.active && refillKeys.size>0) ? 'flex' : 'none';
  $('btnRefill').textContent = `체크한 ${refillKeys.size}개 포트 재필링`;
}

async function startFilling(targets, label){
  if (!targets.length) return;
  // 이번 실행 대상은 재필링 목록에서 비운다(admin 계약 — 다시 체크하지 않으면 목록에서 사라짐).
  for (const t of targets) refillKeys.delete(tileKey(t));
  msg(`${label} 시작…`, true);
  const r = await jfetch('/api/filling', {targets, volumeUl: Math.round(parseFloat($('dVol').value)*1000),
    aspirateSpeedHz: parseInt($('dAsp').value), dispenseSpeedHz: parseInt($('dDisp').value)});
  if (!r.ok) { msg(r.error||'발행 실패', false); return; }
  refreshState();
}
function fillSelected(){
  const t = TILES.find(x=>tileKey(x)===selTileKey);
  if (t) startFilling([t], `${t.label} 흡입/배출`);
}
function fillAll(){
  if (!confirm(`매핑된 전 포트(${SEQ_TARGETS.length}개)를 순차 필링합니다 (펌프1 전부 → 펌프2 전부…). 계속할까요?`)) return;
  startFilling(SEQ_TARGETS, '순차 전체 필링');
}
function fillRefill(){
  startFilling(TILES.filter(t=>refillKeys.has(tileKey(t))), '재필링');
}

async function refreshState(){ renderState(await jfetch('/api/state')); }

async function doConnect(){
  msg('재인식 중… (펌프 24V 전원이 켜져 있어야 합니다)', true);
  const r = await jfetch('/api/connect', {});
  if (r.ok) { msg(`연결 완료 — ${r.port} · 펌프 ${r.pumps.join(', ')}. 시린지 용량 확인 체크 후 사용하세요.`, true); await refreshState(); loadTiles(); refreshHealth(); }
  else msg(r.error||'연결 실패', false);
}
let wasConnected=false;
function onConnectChange(s){ // 자동 연결이 붙으면 타일·상태를 갱신(연결 카드 없이도 반응).
  if (s.connected && !wasConnected) { loadTiles(); refreshHealth(); msg(`연결 완료 — ${s.port} · 펌프 ${s.pumps.join(', ')}. 시린지 용량 확인 체크 후 사용하세요.`, true); }
  wasConnected = s.connected;
}

async function pushSettings(){
  const r = await jfetch('/api/settings', {sensorium:$('sensorium').value, capacityMl:parseFloat($('cap').value)});
  if (r.error) { msg(r.error,false); refreshState(); } else { lastPortMapJson=''; renderState(r); loadTiles(); }
}

// ── 포트 매핑 편집기 (admin 설정 '포트 매핑' 미러) ──
let lastPortMapJson = '';
function renderPortMap(s){
  const wrap=$('portMapWrap');
  const j = JSON.stringify([s.sensorium, s.pumpPorts, s.liquidCatalog]);
  if (j===lastPortMapJson) return;                       // 변경 없으면 재렌더 금지(편집 중 씹힘 방지)
  if (wrap.contains(document.activeElement)) return;     // 편집 중엔 폴링 재렌더 보류
  lastPortMapJson = j;
  wrap.innerHTML='';
  const cat = s.liquidCatalog||[];
  for (const [addrS, layout] of Object.entries(s.pumpPorts||{})) {
    const addr=parseInt(addrS);
    const box=document.createElement('div');
    box.style.cssText='margin-bottom:14px;border:1px solid var(--line);border-radius:8px;padding:10px 12px';
    const discovered = s.pumps.includes(addr);
    box.innerHTML=`<div class="row" style="margin-bottom:8px"><b>${(s.pumpLabels||{})[addr]||('펌프 '+addr)}</b>
      <span class="sub">(주소 ${addr}${discovered?'':' · 미인식 — 매핑만 편집 가능'})</span>
      <button onclick="resetPortMap(${addr})">기본 배치로 초기화</button>
      <button class="primary" onclick="savePortMap(${addr})">저장</button></div>`;
    const grid=document.createElement('div');
    grid.style.cssText='display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px';
    for (let port=1; port<=12; port++) {
      const cur=(layout||{})[String(port)]||'';
      const cell=document.createElement('label');
      cell.style.cssText='font-size:12px;color:var(--sub);display:flex;flex-direction:column;gap:2px';
      const sel=document.createElement('select');
      sel.dataset.pump=addr; sel.dataset.port=port; sel.className='pmsel';
      sel.style.cssText='width:100%';
      const opts=[['','(비움)'],...ROLE_OPTS,...cat.map(c=>[c.value,c.label])];
      for (const [v,l] of opts){const o=document.createElement('option');o.value=v;o.textContent=l;sel.appendChild(o);}
      sel.value = opts.some(([v])=>v===cur) ? cur : '';
      if (cur && !opts.some(([v])=>v===cur)) {           // 카탈로그 밖 값(보존 표시)
        const o=document.createElement('option');o.value=cur;o.textContent=cur;sel.appendChild(o);sel.value=cur;
      }
      cell.innerHTML=`<span>P${port}</span>`; cell.appendChild(sel);
      grid.appendChild(cell);
    }
    box.appendChild(grid);
    wrap.appendChild(box);
  }
}
async function savePortMap(addr){
  const ports={};
  document.querySelectorAll(`.pmsel[data-pump="${addr}"]`).forEach(sel=>{ ports[sel.dataset.port]=sel.value||null; });
  const r = await jfetch('/api/portmap', {pump:addr, ports});
  if (r.error) { msg(r.error,false); return; }
  msg(`펌프 ${addr} 포트 매핑 저장됨 — 타일·초기화·세척이 새 매핑을 따릅니다.`, true);
  lastPortMapJson=''; renderState(r); loadTiles();
}
async function resetPortMap(addr){
  if (!confirm(`펌프 ${addr}의 포트 매핑을 이 센소리움 버전의 기본 배치로 되돌립니다. 계속할까요?`)) return;
  const r = await jfetch('/api/portmap', {pump:addr, reset:true});
  if (r.error) { msg(r.error,false); return; }
  msg(`펌프 ${addr} 기본 배치로 초기화됨.`, true);
  lastPortMapJson=''; renderState(r); loadTiles();
}

async function confirmCapacity(checked){
  // 해제도 서버에 반영(리뷰 P2-6) — 안 보내면 다음 폴링에 체크가 되돌아와 게이트가 계속 열려 있다.
  const r = await jfetch('/api/settings', {confirmCapacity: !!checked});
  if (r.error) { msg(r.error,false); refreshState(); } else renderState(r);
}

async function refreshHealth(){
  const r = await jfetch('/api/health');
  if (r.error) { msg(r.error,false); return; }
  if (r.busy) { msg(`작업 진행 중(${r.busy}) — 상태 점검은 작업이 끝난 뒤 가능합니다.`, true); return; }
  for (const [p,st] of Object.entries(r.pumps||{})) paintHealth(p, st);
}

function setRes(p, r){
  lastResults[p] = r.ok ? `✅ ${r.label}` : `❌ ${r.label} (${r.classLabel})`;
  const el=$('res'+p); if (el) el.textContent = lastResults[p];
}

async function doPlunger(op, p){
  msg('', true);
  const r = await jfetch('/api/plunger', {op, pump:p});
  if (r.error && r.code===undefined) { msg(r.error,false); return; }
  setRes(p, r);
  if (!r.ok) msg(`${op==='plungerFull'?'전량 흡입':'전량 배출'} 실패 — ${r.label}`, false);
  refreshState();
}

async function doWeakInit(){
  if (!confirm(`모든 펌프(${S.pumps.join(',')})를 홈으로 강제 복귀시킵니다. 진행 중 작업은 중단됩니다. 계속할까요?`)) return;
  msg('약한 초기화 중… (홈 확인 즉시 완료 — 최대 30초)', true);
  const r = await jfetch('/api/weak-init', {});
  if (r.error && !r.results) { msg(r.error,false); return; }
  for (const [p,res] of Object.entries(r.results||{})) setRes(p,res);
  msg(r.ok ? `약한 초기화 완료 (${r.elapsedS}s)` : '일부 펌프 초기화 실패 — 결과 확인', r.ok);
  refreshState(); refreshHealth();
}

async function doClean(){
  const alcohol=parseInt($('alcoholCount').value)||2;
  const purge=parseInt($('purgeCount').value)||0;
  const purgeTxt = S.mode==='flavor' ? ` · 에어 퍼지 ${purge}회` : '';
  if (!confirm(`빈 컵/공병을 배출구 아래에 두세요.\\n펌프를 초기화하고 세척 사이클을 실행합니다 (알코올 ${alcohol}회${purgeTxt}). 계속할까요?`)) return;
  msg('세척 중… (초기화 → 세척액 순환'+(S.mode==='flavor'?' → 에어 퍼지':'')+')', true);
  const r = await jfetch('/api/clean', {alcoholCount:alcohol, purgeCount:purge});
  if (r.error && !r.rounds) { msg(r.error,false); return; }
  const n=(r.rounds||[]).length;
  msg(r.ok ? `세척 완료 (${r.elapsedS}s · ${n}회차)` : (r.aborted ? '세척 중단됨(긴급 정지)' : `세척 일부 실패 — 로그 확인 (${n}회차 실행)`), r.ok);
  refreshState(); refreshHealth();
}

async function doEstop(){
  const r = await jfetch('/api/estop', {});
  for (const [p,st] of Object.entries(r.pumps||{})) paintHealth(p, st);
  msg(r.ok ? '⛔ 긴급 정지 발동 — 복구는 [약한 초기화] 또는 [세척]' : (r.note||r.error||'정지 검증 실패 — 24V 전원을 차단하세요'), r.ok);
  refreshState();
}

async function valveLatch(base){
  const r = await jfetch('/api/valve', {action:'latch_on', base});
  msg(r.note||r.error||'', r.ok); refreshState();
}
async function valveOff(base){
  const r = await jfetch('/api/valve', {action:'off', base});
  msg(r.note||r.error||'', r.ok); refreshState();
}
async function valveOpenFor(base){
  const sec=parseInt($('vsec-'+base).value)||3;
  msg(`밸브 ${sec}초 개방 중… (액체가 흐릅니다)`, true);
  const r = await jfetch('/api/valve', {action:'open_for', base, sec});
  msg(r.note||r.error||'', r.ok); refreshState();
}

async function pollLogs(){
  const showDebug = $('showDebug').checked;
  const r = await jfetch('/api/logs?since='+lastLog);
  if (r._net || r.error || !r.logs) return;
  if (r.logs.length) {
    lastLog = r.last;
    const el=$('log');
    for (const rec of r.logs) {
      if (!showDebug && rec.severity==='DEBUG') continue;
      const d=document.createElement('div');
      d.className=(rec.severity||'INFO').toLowerCase();
      const extra = rec.detail ? Object.entries(rec.detail)
        .map(([k,v])=>`${k}=${typeof v==='string'?v:JSON.stringify(v)}`).join(' ') : '';
      d.textContent = `${(rec.ts||'').slice(11,19)} ${rec.severity||''} ${rec.message||''} ${extra}`;
      el.appendChild(d);
    }
    while (el.childNodes.length>600) el.removeChild(el.firstChild);
    el.scrollTop = el.scrollHeight;
  }
}

refreshState();
loadTiles();
setInterval(refreshState, 2500);
setInterval(pollLogs, 1200);
</script>
</body></html>"""


@app.get("/")
def index():
    return PAGE


@app.errorhandler(Exception)
def _json_error(e):  # noqa: ANN001
    """예기치 못한 예외도 JSON 으로 — HTML 500 은 UI jfetch 를 조용히 죽인다(검증 P1-8)."""
    from werkzeug.exceptions import HTTPException

    if isinstance(e, HTTPException):
        return e
    _log("error", "처리되지 않은 예외", error=str(e)[:200])
    return jsonify({"ok": False, "error": f"내부 오류: {e}"}), 500


if __name__ == "__main__":
    _log("info", "정비 툴 시작", version="1.3.0", aiStampSource=AI_STAMP_SOURCE)
    # 자동 연결 — 켜면 알아서 인식(수동 버튼은 헤더 ⟳ 재인식만).
    threading.Thread(target=_auto_connect_loop, daemon=True).start()
    # threaded=True 필수 — 정비 op 가 도는 동안에도 긴급 정지 요청이 처리돼야 한다.
    app.run(host="0.0.0.0", port=8000, threaded=True)
