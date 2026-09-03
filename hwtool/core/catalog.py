"""admin 미러 상수·라벨 카탈로그 — 순수 데이터 (heysenlyt-web 값과 동일 유지가 계약).

원 출처 주석은 app.py 시절 그대로 보존한다 — 각 값의 SoT 는 admin(heysenlyt-web) 코드다.
"""

from __future__ import annotations

import re as _re

from senlyt_pi.test_seam.fake_engine_sentinels import (
    FAKE_EMPTY_RAW_CODE,
    FAKE_TIMEOUT_RAW_CODE,
)

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
    # 벤치 툴 관용 범위(2026-09-03) — admin(sy01b 500~) 미러였으나 XCalibur 하한은 50 이라
    #   UI 입력 200 이 500 으로 승격되는 불일치가 있었다. 툴 철학 = 관대한 클램프 + 기기 판정
    #   (모델별 상한 위반은 기기가 err3 로 정직 거부).
    #   상한 = 어댑터 프리셋 물리 상한(V 6000Hz·L 20 — PUMP_PRESETS 양 모델 동일)과 정렬.
    #   admin 흡입 기본 상한(5000)보다 넓다 — 벤치는 전 범위 실측이 목적(어댑터 _speed_cmd 가
    #   프리셋 상한으로 한 번 더 클램프하므로 물리 초과는 구조적으로 불가).
    "aspirateSpeedHz": (50, 6000),
    "dispenseSpeedHz": (50, 6000),
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
FLAVOR_LIQUID_KO = {
    "lemon": "레몬", "lime": "라임", "orange": "오렌지", "grapefruit": "자몽",
    "grape": "포도(적포도)", "muscat": "청포도(머스캣)", "apple": "사과(청사과)", "peach": "복숭아",
    "pineapple": "파인애플", "mango": "망고", "berry": "딸기/베리", "yogurt": "요구르트(유산균)",
    "plum": "매실", "yuzu": "유자", "cola": "콜라", "coffee": "커피", "sweet": "당(감미)",
}
# SEED_FLAVOR_PUMP_PORTS 미러 — 펌프1: 1~10 액체(2=output·11=cleaning·12=air 제외), 펌프2: 9액체.
SEED_FLAVOR_PORTS = {
    1: {1: "lemon", 3: "lime", 4: "orange", 5: "grapefruit", 6: "grape", 7: "muscat",
        8: "berry", 9: "yogurt", 10: "sweet"},
    2: {1: "apple", 3: "peach", 4: "pineapple", 5: "mango", 6: "plum", 7: "yuzu",
        8: "cola", 9: "coffee"},
}
# NOTE_META 27종 idx 순(1~27) — buildFragranceSeed 미러: 펌프 p 의 포트 2~10 에 9종씩.
FRAGRANCE_NOTES_KO = [
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

# 에러코드 한글 라벨 (SY-01B 매뉴얼 §4.6.2 + pump_guard 분류 주석).
ERROR_LABELS = {
    -1003: "모델 불일치(실물=Tecan · 센소리움을 XCalibur 변형으로)",
    -1002: "하드웨어 선언 미확정(센소리움 배정 후 재시작)",
    0: "정상",
    1: "초기화 오류",
    2: "잘못된 명령",
    3: "잘못된 피연산자",
    7: "미초기화(홈 상실)",
    9: "플런저 오버로드",
    10: "밸브 오버로드",
    # 매뉴얼 정의(양 기종 동일): 11 = "bypass 자세에서 플런저 이동 불가". "과다흡입"은 v1.1.0
    #   실기기에서 11 로 발현된 이력의 프로젝트 재해석 — 진단 시 두 의미 다 보이게 병기한다.
    11: "플런저 이동 불가(매뉴얼: bypass 자세 / 실측 이력: 과다흡입)",
    15: "명령 겹침(Busy/Command overflow)",
    FAKE_TIMEOUT_RAW_CODE: "무응답(타임아웃)",
    FAKE_EMPTY_RAW_CODE: "깨진 응답(프레임 아님)",
}
CLASS_LABELS = {"normal": "정상", "transient": "일시적(재시도 가능)", "permanent": "구조적(점검 필요)"}

MAX_PORT = 12  # 운영(admin) 포트 검증 상한 미러 — 실물 밸브는 다양(3-way·12구 등, 기기가 판정).


def valve_info_from_config(cfg: "str | None") -> "dict | None":
    """`?76` 구성 문자열 → 밸브 정보 — "활용-아니면-무시"(2026-09-03).

    XCalibur 실측 `9600|100K|484|3-way|AUTO` 의 밸브 필드를 보수적으로 해석한다:
    `N-port` → 분배밸브 N구(P1~PN — "N-port" 는 시린지 제외 셈법), `3-way`/`4-way`/`T`
    → 방향 선택형(way 는 시린지 포함 셈법이라 선택지는 N-1). 못 알아보면 None — 소비자는
    정적 폴백(양 매뉴얼 공통 최대 12포트 + 방향)으로 돌아가고 판정은 기기(err3)가 한다.
    ⚠️ 이 값은 자기 신고(U<n> 설정의 되읽기)다 — 밸브 교체 후 재설정 안 된 개체는 거짓말한다.
    SY-01B 는 ?76 존재하나 응답 포맷 미실측(매뉴얼 미문서화) — 실측 후 이 파서를 넓힌다.
    """
    if not cfg:
        return None
    for field in str(cfg).split("|"):
        f = field.strip()
        m = _re.match(r"^(\d+)[ -]?port", f, _re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 12:
                return {"kind": "distribution", "ports": n, "label": f}
        if _re.match(r"^([34][ -]?way|T( valve)?)$", f, _re.IGNORECASE):
            return {"kind": "directional", "ports": None, "label": f}
    return None
