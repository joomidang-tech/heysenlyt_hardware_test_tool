"""tecan_bringup_full.ipynb 빌더 — Plan 에이전트 계획(2026-09-03)을 셀로 옮긴다.

실측 조건 반영: 주소1·9600·0.25mL 시린지·2포트 밸브·건식(튜브 없음).
실행은 nbclient 로 노트북 자체를 돌려 출력이 셀에 저장된다(자산화).
"""
import json

def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s}

def code(s):
    return {"cell_type": "code", "metadata": {}, "source": s, "outputs": [], "execution_count": None}

CELL_SETUP_A = r'''# ── SETUP + Tier A: read-only 상태·위치 ─────────────────────────────────────
import time
from pl2303py import open_pump_serial

ETX = 0x03
ser = open_pump_serial(baudrate=9600, timeout=0.5)
RESULTS = {}   # 검증 목표별 판정 축적 → 마지막 요약 셀
LOG = []       # 전 왕복 hex 기록(포맷 미확정 응답 채집이 핵심 산출물)

def txn(body, deadline=1.5, addr=1):
    """`/{addr}{body}\r` 송신 → ETX 까지 수신. 전 프레임 기록."""
    tx = f"/{addr}{body}\r".encode()
    ser.reset_input_buffer()
    ser.write(tx)
    buf, t0 = b"", time.monotonic()
    while time.monotonic() - t0 < deadline:
        c = ser.read(64)
        if c:
            buf += c
            if bytes([ETX]) in buf:
                break
    LOG.append((body, tx, buf))
    print(f"  tx=/{addr}{body}  rx={buf.hex(' ') or 'SILENT'}")
    return buf

def parse(buf):
    """응답 → (상태바이트, 데이터 ASCII). 에코(/1..) 가 섞여도 /0 마스터 프레임만 취한다."""
    i = buf.find(b"/0")
    if i < 0 or len(buf) < i + 3:
        return None, ""
    st = buf[i + 2]
    j = buf.find(bytes([ETX]), i)
    data = buf[i + 3:j].decode(errors="replace") if j > i + 2 else ""
    return st, data

def err(st):  return None if st is None else st & 0x0F
def ready(st): return st is not None and bool(st & 0x20)

def check(name, cond, detail=""):
    print(f"CHECK {name}: {'PASS' if cond else 'FAIL'}  {detail}")
    if not cond:
        raise RuntimeError(f"ABORT {name}: {detail}")

def obs(name, detail):
    print(f"OBS {name}: {detail}")

print("STEP=A")
# A-1 Q 기준선 (§3.6 — 시리얼 상태 취득의 유일 정규 수단)
st, _ = parse(txn("Q"))
check("A-1 Q ready·err0", st == 0x60, f"status=0x{st:02x}" if st is not None else "무응답")
RESULTS["① 상태바이트"] = "0x60 ready·err0 실측"

# A-2 ? 플런저 절대위치
st, pos = parse(txn("?"))
check("A-2 ? err0", err(st) == 0, f"data={pos!r}")
obs("A-2 위치", pos)

# A-3 ?4 엔코더 (옵션 유무 미상 — 관측 전용)
st, enc = parse(txn("?4"))
HAS_ENCODER = err(st) == 0 and enc.strip().lstrip("-").isdigit()
obs("A-3 엔코더", f"지원={HAS_ENCODER} data={enc!r} err={err(st)}")

# A-4 ?6 밸브 위치 (타입 1차 단서 — 초기화 전이라 관측만)
st, v6 = parse(txn("?6"))
obs("A-4 ?6(초기화 전)", f"data={v6!r} err={err(st)}")

# A-5 ?10 커맨드 버퍼 — 잔류 스트링이 있으면 이후 R 이 그걸 실행한다(§3.5.8)
st, buf10 = parse(txn("?10"))
check("A-5 버퍼 비어있음", err(st) == 0 and buf10.strip() == "0", f"data={buf10!r}")

# A-6 Q 마감 — 리포트 전량이 무부작용이었는지
st, _ = parse(txn("Q"))
check("A-6 Q 유지", st == 0x60, f"status=0x{st:02x}" if st is not None else "무응답")
print("VERDICT: TIER_A_PASS")'''

CELL_B = r'''# ── Tier B: 설정 판독 전수 (read-only) ──────────────────────────────────────
# §3.5.8 전수 조사분. ⛔ ?122(비솔레노이드 기종 err3 유발)·?18(자기 리셋 카운터) 제외.
print("STEP=B")

st, fw = parse(txn("&"))            # B-1 펌웨어 파트넘버·버전
check("B-1 & 펌웨어", err(st) == 0 and fw.strip() != "", f"fw={fw!r}")
RESULTS["펌웨어(&)"] = fw.strip()

st, cksum = parse(txn("#"))         # B-2 체크섬
check("B-2 # 체크섬", err(st) == 0, f"data={cksum!r}")

st, q76 = parse(txn("?76", deadline=2.5))  # B-3 펌프 구성 (최중요 채집 — 포맷 미정의)
check("B-3 ?76 응답", err(st) in (0, 2, 3), f"err={err(st)}")
Q76_BEFORE = q76
obs("B-3 ?76 원문", repr(q76))
RESULTS["?76 포맷"] = repr(q76)[:120]

# B-4 속도 3종 readback — 번호 체계 확정 게이트(?1 이 900대=DT 체계 §3.5.8)
vals = {}
for n, (lo, hi) in {"?1": (50, 1000), "?2": (5, 6000), "?3": (50, 2700)}.items():
    st, d = parse(txn(n))
    check(f"B-4 {n} err0·범위", err(st) == 0 and d.strip().isdigit() and lo <= int(d) <= hi, f"data={d!r}")
    vals[n] = int(d)
check("B-4 단조성 v≤c≤V", vals["?1"] <= vals["?3"] <= vals["?2"], str(vals))
check("B-4 번호체계=DT", vals["?1"] >= 50 and vals["?2"] >= vals["?1"], f"?1={vals['?1']} — 위치성 값이면 CAN 체계 혼동")
obs("B-4 속도 기본값 대조", f"{vals} (공장 기본 900/1400/900)")
RESULTS["⑦ 속도 readback"] = str(vals)

# B-5 ?12 백래시 · ?24 zero gap — N0/N1 간접 판별(N0 기본 12/50, N1 은 96/400)
st, bl = parse(txn("?12")); check("B-5 ?12", err(st) == 0, f"data={bl!r}")
st, zg = parse(txn("?24")); check("B-5 ?24", err(st) == 0, f"data={zg!r}")
obs("B-5 N0 방증", f"백래시={bl} zerogap={zg} (12/50 근방=N0)")
RESULTS["③ N0 간접판별"] = f"백래시={bl} zerogap={zg}"

# B-6 수명 카운터 — Z·밸브 모션의 발생 증거 기준값
st, d = parse(txn("?15")); INIT_COUNT_0 = int(d); check("B-6 ?15", err(st) == 0, d)
st, d = parse(txn("?16")); obs("B-6 ?16 플런저이동수", d)
st, d = parse(txn("?17")); VALVE_COUNT_0 = int(d); check("B-6 ?17", err(st) == 0, d)
obs("B-6 기준", f"init={INIT_COUNT_0} valve={VALVE_COUNT_0}")

# B-7 ?120 safe-init 모드 (읽기만 — U 로 절대 안 바꿈)
st, d = parse(txn("?120")); obs("B-7 safe-init", f"{d!r} err={err(st)}")

# B-8 보조 입력
st, d = parse(txn("?13")); obs("B-8 ?13", f"{d!r} err={err(st)}")
st, d = parse(txn("?14")); obs("B-8 ?14", f"{d!r} err={err(st)}")

# B-9 ?22 — 기지값 255 스텁(§3.5.8) = 데이터 파싱 무결성 카나리아
st, d = parse(txn("?22"))
check("B-9 ?22==255", err(st) == 0 and d.strip() == "255", f"data={d!r}")

# B-10 디지털 출력 관측
st, d = parse(txn("?121")); obs("B-10 ?121", f"{d!r} err={err(st)}")

st, _ = parse(txn("Q"))
check("B-11 Q 마감", st == 0x60, f"status=0x{st:02x}" if st is not None else "무응답")
print("VERDICT: TIER_B_PASS")'''

CELL_BP = r'''# ── Tier B′: 무모션·비영속 경계 프로브 ──────────────────────────────────────
print("STEP=B'")

# B′-1 N0R — RAM 설정·무모션(§ N<n>). 직후 ?76 diff 로 "N 모드가 텍스트에 드러나는가" 확정.
st, _ = parse(txn("N0R"))
check("B'-1 N0R err0", err(st) == 0, f"status=0x{st:02x}" if st is not None else "무응답")
st, q76b = parse(txn("?76", deadline=2.5))
obs("B'-1 ?76 diff", "동일" if q76b == Q76_BEFORE else f"변화: {q76b!r}")
RESULTS["③ N0 readback"] = "?76 에 N모드 " + ("미표시(간접판별 유지)" if q76b == Q76_BEFORE else "표시됨(게이트 승격 가능)")

# B′-2 의도적 err3 — 범위 밖 속도 v10(하한 50 미달·§3.5.3). Immediate error = 무모션·재초기화 불요.
st, _ = parse(txn("v10R"))
if err(st) == 3:
    obs("B'-2 v10R", "err3 즉답 — 하한 클램프(TECAN_MIN_SPEED_HZ=50) 근거 실측 확정")
    RESULTS["⑧ err3 즉답(속도)"] = "PASS"
else:
    obs("B'-2 v10R", f"err={err(st)} — 하한 관용? 어댑터 주석 반영 필요")
    RESULTS["⑧ err3 즉답(속도)"] = f"관용 err={err(st)}"

# B′-3 Q 래치 관찰 — immediate error 한정(§3.6.3 '[Q] clears the error' 의 안전 검증 최대치)
st1, _ = parse(txn("Q"))
st2, _ = parse(txn("Q"))
obs("B'-3 Q 래치", f"1발=0x{st1:02x} 2발=0x{st2:02x}")
check("B'-3 에러가 후속을 안 막음", st2 == 0x60, f"2발=0x{st2:02x}")
RESULTS["② Q 래치(immediate)"] = f"1발 0x{st1:02x}→2발 0x{st2:02x} · 오버로드 래치는 검증불가·보류"

# B′-4 초기화 전 A4000 — 축 밖(0..3000)·무모션 거부 확인. err3 또는 err7(미초기화 래치) 둘 다 정상.
st, _ = parse(txn("A4000R"))
e = err(st)
if e in (3, 7):
    st2, pos = parse(txn("?"))
    check("B'-4 위치 불변", pos.strip() == "0", f"pos={pos!r}")
    obs("B'-4 A4000 거부", f"err{e} (모션 없음)")
    RESULTS["⑧ 축밖 A4000(1차)"] = f"err{e} 거부"
else:
    txn("TR")  # 만일 수락됐다면 즉시 정지
    check("B'-4 축가드", False, f"A4000 이 err0 수락 — 축 가드 전제 붕괴 (err={e})")

# err7 래치 소거는 성공적 Z 만 가능(§3.6.3) — Tier C 의 Z 가 곧 해소 경로다.

# B′-5 브로드캐스트 오염 프로브 — `_`(5Fh)=전체, 응답 없음이 정상.
ser.reset_input_buffer()
ser.write(b"/_Q\r")
time.sleep(0.3)
junk = ser.read(64)
st, _ = parse(txn("Q"))
obs("B'-5 브로드캐스트", f"잔여={junk.hex(' ') or '없음'} 직후Q=0x{st:02x}" if st else "직후Q 무응답")
RESULTS["브로드캐스트 오염"] = "없음" if not junk else f"오염 {junk.hex(' ')}"
print("VERDICT: TIER_BPRIME_PASS")'''

MD_C_GATE = r'''## Tier C 게이트 — 물리 확정값 (2026-09-03 사용자 확인)

| 항목 | 값 | 반영 |
|---|---|---|
| 시린지 | **0.25 mL 장착** | Z 힘: 권장표(§3.4.2 Table 3-6)상 250µL=Half(1)를 **상한**으로, 더 약한 Third(2) 먼저 → err1 시 1회만 Half 로 승격 |
| 밸브 | **2포트** (비분배 추정 — ?6/?76 채집과 교차 대조) | 밸브 테스트 = I/O 전환·readback 한정. B/E(bypass) 금지 |
| 배관 | **튜브 없음(건식)** | 공기만 이동 — Z 의 흡입/배출 포트 지정이 물리 결과를 바꾸지 않는 유일한 예외 상황(제1원칙 7 의 명시적 예외로 기록). 밸브가 문자형(비분배)이면 `Z{힘}R` 힘만 지정 |
| 주변 간섭물 | 없음(벤치) | — |

중단 규칙: 예상 밖 err ∈ {1,6,7,9,10,11} → 즉시 중단(관찰만). 모션 타임아웃 30s → TR 후 중단.'''

CELL_C_INIT = r'''# ── Tier C-1~3: 초기화 (Z) + 완료 판정 3중 확인 ────────────────────────────
print("STEP=C-init")

# C-1 기준 채집
st, _ = parse(txn("Q")); check("C-1 Q", st in (0x60, 0x67), f"0x{st:02x}")  # err7(미초기화 래치·B'-4 잔재)은 Z 가 해소
st, v6pre = parse(txn("?6")); obs("C-1 ?6", f"{v6pre!r} err={err(st)}")
VALVE_IS_LETTER = v6pre.strip().lower() in ("i", "o", "b", "e")  # 문자=비분배 계열
obs("C-1 밸브 판별", f"비분배(문자형)={VALVE_IS_LETTER}")

# C-2 Z 초기화 — 건식·0.25mL: Third(2) 먼저, err1 시 Half(1) 1회 승격.
#   비분배 밸브면 힘만 지정(Z{f}R). 폴 0.5s 간격 전량 로그 + 도중 ? 1회(busy 중 리포트 수락 §3.6.1).
def z_init(force):
    body = f"Z{force}R"
    st, _ = parse(txn(body))
    if err(st) not in (0,):
        return ("immediate", st, None)
    t0 = time.monotonic()
    polls = []
    probed_mid = False
    while time.monotonic() - t0 < 30.0:
        time.sleep(0.5)
        stq, _ = parse(txn("Q"))
        polls.append(stq)
        if not probed_mid and stq == 0x40:
            stp, midpos = parse(txn("?"))
            obs("C-2 busy 중 ? 수락", f"err={err(stp)} pos={midpos!r}")
            probed_mid = True
        if stq == 0x60:
            return ("done", stq, time.monotonic() - t0)
        if stq is not None and err(stq) != 0:
            return ("error", stq, time.monotonic() - t0)
    return ("timeout", polls[-1] if polls else None, 30.0)

outcome, stz, took = z_init(2)
if outcome == "error" and err(stz) == 1:
    obs("C-2 err1(힘 부족)", "Third→Half 1회 승격(권장표 상한)")
    outcome, stz, took = z_init(1)
check("C-2 Z 완료", outcome == "done", f"outcome={outcome} status=0x{stz:02x} t={took}")
obs("C-2 초기화 소요", f"{took:.1f}s (HOME_SETTLE 실측 근거)")
RESULTS["⑤ 초기화 판정"] = f"Z 완료 {took:.1f}s·폴 전량 clean"
RESULTS["Q during Z"] = "clean(전 폴 프레임 정상)"

# C-3 3중 확인 — 거짓 성공 금지
st, _ = parse(txn("Q")); check("C-3 Q ready", st == 0x60, f"0x{st:02x}")
st, pos = parse(txn("?")); check("C-3 위치 0", pos.strip() == "0", f"pos={pos!r}")
st, d = parse(txn("?15"))
check("C-3 ?15 +1", int(d) == INIT_COUNT_0 + 1, f"{INIT_COUNT_0}→{d} (미증가=초기화 실제 미발생)")
st, v6post = parse(txn("?6")); obs("C-3 ?6(초기화 후)", repr(v6post))
VALVE_PARK = v6post.strip()
print("VERDICT: TIER_C_INIT_PASS")'''

CELL_C_MOVE = r'''# ── Tier C-4~6: 속도 설정·절대이동 5%·홈 복귀 ──────────────────────────────
print("STEP=C-move")

# C-4 저속 프로파일 + readback (하한 50 준수·단조성 §3.5.4 / 라운딩 α 실측 §3.5.8 Note)
st, _ = parse(txn("v50V200c50L14R"))
check("C-4 속도 설정 err0", err(st) == 0, f"0x{st:02x}" if st is not None else "무응답")
alphas = {}
for n, want in (("?1", 50), ("?2", 200), ("?3", 50)):
    st, d = parse(txn(n))
    check(f"C-4 {n} readback", err(st) == 0 and d.strip().isdigit(), f"{d!r}")
    alphas[n] = int(d) - want
check("C-4 오차 α≤16", all(abs(a) <= 16 for a in alphas.values()), str(alphas))
obs("C-4 라운딩 α 실측", str(alphas))
RESULTS["⑦ readback α"] = str(alphas)

# C-5 A150 — 3000축의 5% 절대이동 + 정확 일치 readback (P0-2 축 실측의 핵심)
st, _ = parse(txn("A150R"))
check("C-5 A150 즉답 err0", err(st) == 0, f"0x{st:02x}" if st is not None else "무응답")
saw_busy = False
t0 = time.monotonic()
while time.monotonic() - t0 < 10.0:
    stq, _ = parse(txn("Q"))
    if stq == 0x40:
        saw_busy = True
    if stq == 0x60:
        break
    time.sleep(0.2)
st, pos = parse(txn("?"))
check("C-5 위치==150 정확", pos.strip() == "150", f"pos={pos!r} — 불일치=N1 잔존/축 문제(P0-2)")
obs("C-5 busy 관측", f"{saw_busy} (False=이동이 폴 주기보다 빨랐음)")
if HAS_ENCODER:
    st, enc = parse(txn("?4")); obs("C-5 엔코더 교차", f"?4={enc!r}")
RESULTS["④ 3000축 A150 readback"] = f"?=={pos.strip()} 정확 일치"

# C-6 A0 홈 복귀
st, _ = parse(txn("A0R"))
check("C-6 A0 즉답", err(st) == 0, "")
t0 = time.monotonic()
while time.monotonic() - t0 < 10.0:
    stq, _ = parse(txn("Q"))
    if stq == 0x60:
        break
    time.sleep(0.2)
st, pos = parse(txn("?"))
check("C-6 위치 0", pos.strip() == "0", f"pos={pos!r}")
print("VERDICT: TIER_C_MOVE_PASS")'''

CELL_C_VALVE = r'''# ── Tier C-7: 밸브 전환 + readback (2포트=비분배 가정 검증 포함) ────────────
print("STEP=C-valve")
if not VALVE_IS_LETTER:
    obs("C-7", f"?6 이 문자형이 아님({VALVE_PARK!r}) — 분배형? 사용자 '2포트' 답변과 불일치 → 밸브 테스트 보류")
    RESULTS["⑥ 밸브 readback"] = f"보류(?6={VALVE_PARK!r} — 타입 교차 불일치)"
else:
    for cmd, want in (("IR", "i"), ("OR", "o")):
        st, _ = parse(txn(cmd))
        check(f"C-7 {cmd} err0", err(st) == 0, f"0x{st:02x}" if st is not None else "무응답")
        t0 = time.monotonic()
        while time.monotonic() - t0 < 8.0:
            stq, _ = parse(txn("Q"))
            if stq == 0x60:
                break
            time.sleep(0.2)
        st, v6 = parse(txn("?6"))
        check(f"C-7 ?6=={want}", v6.strip().lower() == want, f"?6={v6!r}")
    st, d = parse(txn("?17"))
    check("C-7 ?17 증가", int(d) > VALVE_COUNT_0, f"{VALVE_COUNT_0}→{d}")
    RESULTS["⑥ 밸브 readback"] = f"I/O 전환·?6 일치·카운터 {VALVE_COUNT_0}→{d}"
print("VERDICT: TIER_C_VALVE_DONE")'''

CELL_C_END = r'''# ── Tier C-8~9: 초기화 후 A4000 err3 확정 + 마감 주차 + 요약 ────────────────
print("STEP=C-end")

# C-8 이제 err7 변수 제거 상태 — 순수 err3 이어야 한다.
st, _ = parse(txn("A4000R"))
if err(st) == 3:
    st2, pos = parse(txn("?"))
    check("C-8 위치 불변", pos.strip() == "0", f"pos={pos!r}")
    st1, _ = parse(txn("Q")); st2q, _ = parse(txn("Q"))
    obs("C-8 Q 래치(초기화 후)", f"1발=0x{st1:02x} 2발=0x{st2q:02x}")
    check("C-8 복귀 0x60", st2q == 0x60, "")
    RESULTS["⑧ 축밖 A4000(2차)"] = f"err3·무모션·Q 후 복귀(1발 0x{st1:02x})"
else:
    txn("TR")
    check("C-8 축가드", False, f"err={err(st)} — err3 아님")

# C-9 마감 — 주차("밸브는 배출구"·2026-07-21 규칙) + 홈 + 최종 상태
if VALVE_IS_LETTER:
    parse(txn("OR"))
    t0 = time.monotonic()
    while time.monotonic() - t0 < 8.0:
        stq, _ = parse(txn("Q"))
        if stq == 0x60:
            break
        time.sleep(0.2)
parse(txn("A0R"))
t0 = time.monotonic()
while time.monotonic() - t0 < 10.0:
    stq, _ = parse(txn("Q"))
    if stq == 0x60:
        break
    time.sleep(0.2)
st, pos = parse(txn("?"))
stq, _ = parse(txn("Q"))
check("C-9 마감 상태", stq == 0x60 and pos.strip() == "0", f"Q=0x{stq:02x} pos={pos!r}")

print()
print("=" * 62)
print("실측 요약 (검증 목표 ↔ 결과)")
for k, v in RESULTS.items():
    print(f"  {k:26s} {v}")
print(f"  총 왕복 {len(LOG)}회 · 원시 프레임 전량 LOG 에 보존")
ser.close()
print("VERDICT: ALL_TIERS_DONE")'''

MD_HEAD = r'''# Tecan XCalibur 실기기 브링업 — 티어드 실측 (2026-09-03)

**정본**: 매뉴얼 `00_research/Manual Operating Cavro XCalibur 20733085-C.txt` · 명령어 차이표(99_daily 2026-09-01) · 계획 = Plan 에이전트 설계(티어·중단규칙·매뉴얼 절 근거).
**벤치 실측 조건**: RS485 주소 1 · 9600 8N1 · PL2303GC 유저스페이스(pl2303py) · **0.25mL 시린지 · 2포트 밸브 · 건식(튜브 없음)**.

티어: **A** read-only 상태 → **B** 설정 판독 전수 → **B′** 무모션 경계(N0R·의도적 err3·브로드캐스트) → **C** 저부하 모션(Z Third힘·A150 5%·밸브 I/O) → 마감 주차.
⛔ 금지: `U`(NVM)·`N1`·`K/k` 쓰기·`B/E`(bypass)·`?122`·`?18`. 중단: 예상 밖 err∈{1,6,7,9,10,11} 즉시(셀 예외 = 이후 셀 자동 중단).
각 셀 출력 = `CHECK/OBS/VERDICT` 구조 — 출력이 곧 실측 기록.'''

MD_TAIL = r'''## 남긴 것 (이 실측이 확정 못 하는 항목)

- **오버로드(err9/10) 래치의 Q 소거**: 실제 오버로드 유발 없이는 검증 불가 — "검증 불가·보류". 어댑터의 `_health_cmd="?"` 분리 방어는 그대로 유지.
- **Tier D(전원 사이클 N0 휘발성)**: 사용자 수동 전원 off→on 후 Tier A 재실행 + `?76`·`?12`·`?24` 재판독으로 별도 세션에서.
- 결과의 어댑터 반영(미실측 주석 해소·판정식 승격)은 실측 완료 후 별도 커밋으로.'''

cells = [
    md(MD_HEAD),
    code(CELL_SETUP_A),
    code(CELL_B),
    code(CELL_BP),
    md(MD_C_GATE),
    code(CELL_C_INIT),
    code(CELL_C_MOVE),
    code(CELL_C_VALVE),
    code(CELL_C_END),
    md(MD_TAIL),
]
nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
with open("tecan_bringup_full.ipynb", "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print("built tecan_bringup_full.ipynb —", len(cells), "cells")
