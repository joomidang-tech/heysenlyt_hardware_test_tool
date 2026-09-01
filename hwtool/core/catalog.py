"""admin 미러 상수·라벨 카탈로그 — 순수 데이터 (heysenlyt-web 값과 동일 유지가 계약).

원 출처 주석은 app.py 시절 그대로 보존한다 — 각 값의 SoT 는 admin(heysenlyt-web) 코드다.
"""

from __future__ import annotations

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

MAX_PORT = 12  # 회전 밸브 12구(SY-01B·XCalibur 12-port 분배밸브 공통).
