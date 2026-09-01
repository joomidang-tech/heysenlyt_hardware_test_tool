"""포트 배치·타일 파생 — **순수 함수**(전역 STATE 무의존 → 단위테스트 대상).

admin(heysenlyt-web)의 `portLayout.ts`/`tilesFromPumpPorts`/`seqTargets` 미러. 호출자
(service)가 상태(pump_ports·mode·pumps)를 인자로 넘긴다 — app.py 시절엔 전역 STATE 를
직접 읽어 테스트가 어려웠다(헥사고날 개편의 핵심 이득).
"""

from __future__ import annotations

from .catalog import (
    DEFAULT_ROLE_PORTS,
    FLAVOR_LIQUID_KO,
    FRAGRANCE_NOTES_KO,
    FRAGRANCE_PUMP_LABELS,
    SEED_FLAVOR_PORTS,
)


def seed_layout(mode: str, addr: int) -> dict:
    """펌프 1대의 시드 레이아웃 {port(int): liquid} — admin SEED_* 와 동일 배치(역할 포함)."""
    if mode == "flavor":
        layout = dict(SEED_FLAVOR_PORTS.get(addr, {}))
        layout[2] = "output"
        layout[11] = "cleaning"
        layout[12] = "air"
        return layout
    layout = {1: "alcohol", 11: "output", 12: "air"}
    for j in range(9):
        idx = (addr - 1) * 9 + j
        if 0 <= idx < len(FRAGRANCE_NOTES_KO):
            layout[j + 2] = FRAGRANCE_NOTES_KO[idx][0]
    return layout


def seed_pump_ports(family: str, pumps: "list[int] | None" = None) -> dict:
    """센소리움 버전의 시드 포트 매핑 — 버전의 펌프 목록 × 계열 시드 배치."""
    addrs = pumps if pumps is not None else ([1, 2] if family == "flavor" else [1, 2, 3])
    return {a: seed_layout(family, a) for a in addrs}


def default_role_port(mode: str, role: str) -> int:
    """`portLayout.defaultRolePort` 미러 — 매핑에 역할이 없을 때의 폴백."""
    d = DEFAULT_ROLE_PORTS[mode]
    if role in ("cleaning", "alcohol"):
        return d["cleaning"]
    return d.get(role, d["air"])


def role_port(pump_ports: dict, mode: str, addr: int, role: str) -> int:
    """그 펌프의 역할 포트 — 매핑 우선·없으면 모드 기본(outputPortOf/airPortOf/cleaningPortOf 미러).

    cleaning 계열은 admin `cleaningPortOf` 처럼 cleaning → alcohol 순으로 관용 조회한다.
    """
    layout = pump_ports.get(addr, {})
    wanted = ("cleaning", "alcohol") if role in ("cleaning", "alcohol") else (role,)
    for port in sorted(layout):
        if layout[port] in wanted:
            return port
    return default_role_port(mode, role)


def pump_label(mode: str, addr: int) -> str:
    if mode == "fragrance":
        return FRAGRANCE_PUMP_LABELS.get(addr, f"{addr}펌프")
    return f"{addr}펌프"


def liquid_label(mode: str, liquid: str) -> str:
    if mode == "flavor":
        return FLAVOR_LIQUID_KO.get(liquid, liquid)
    return dict(FRAGRANCE_NOTES_KO).get(liquid, liquid)


def tiles(pumps: "list[int]", pump_ports: dict, mode: str) -> list[dict]:
    """액체 타일 목록 — admin `tilesFromPumpPorts` 미러: **포트 매핑에서** 포트 1→12 순회
    (발견된 펌프만·output/air 제외·cleaning/alcohol=펌프별 역할 타일·중복 액체 P표기)."""
    out: list[dict] = []
    for addr in sorted(pumps):
        layout = pump_ports.get(addr, {})
        for port in sorted(layout):  # 포트 1~12 순회 — admin 과 동일한 화면 배열(재검증 P2-l).
            liquid = layout[port]
            if not liquid or liquid in ("output", "air"):
                continue
            if liquid in ("cleaning", "alcohol"):
                out.append({"pump": addr, "port": port, "liquid": liquid,
                            "label": f"알코올(세척액) P{addr}", "isRole": True})
            else:
                out.append({"pump": addr, "port": port, "liquid": liquid,
                            "label": liquid_label(mode, liquid)})
    # 같은 액체 다중 펌프 → 라벨 P{addr} 구분(tilesFromPumpPorts 미러).
    count: dict[str, int] = {}
    for t in out:
        if not t.get("isRole"):
            count[t["liquid"]] = count.get(t["liquid"], 0) + 1
    for t in out:
        if not t.get("isRole") and count.get(t["liquid"], 0) > 1:
            t["label"] = f"{t['label']} P{t['pump']}"
    return out


def seq_targets(tile_list: list[dict]) -> list[dict]:
    """순차 필링 대상 — admin `seqTargets` 미러: 일반 액체(중복 액체는 첫 타일) + 펌프별
    알코올, (펌프, 포트) 정렬."""
    first_by_liquid: dict[str, dict] = {}
    for t in tile_list:
        if not t.get("isRole") and t["liquid"] not in first_by_liquid:
            first_by_liquid[t["liquid"]] = t
    out = list(first_by_liquid.values()) + [t for t in tile_list if t.get("isRole")]
    return sorted(out, key=lambda t: (t["pump"], t["port"]))
