"""인바운드 UI — 단일 페이지 HTML (app.py 시절 원문 그대로 이동 · 내용 불변)."""

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
  .setnav button:disabled { opacity:.4; cursor:not-allowed; }
  .card.locked { opacity:.45; pointer-events:none; }
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
  /* 용도별 판단표 — SPEED_PRESETS 와 같은 값(차이표 문서 §5 미러). 현재 기종 열만 강조. */
  #presetTbl td, #presetTbl th { vertical-align:top; font-size:12.5px; }
  #presetTbl .num { font-family:ui-monospace,monospace; white-space:nowrap; font-size:12px; }
  #presetTbl.m-sy .col-tec, #presetTbl.m-tec .col-sy { opacity:.4; }
  #presetTbl.m-sy .col-sy,  #presetTbl.m-tec .col-tec { background:#faf9f6; }
</style></head><body>
<header>
  <h1>🔧 시린지펌프 정비 툴</h1>
</header>
<div id="estopBanner" style="display:none;background:var(--danger);color:#fff;padding:9px 20px;font-weight:700">
  ⛔ 긴급 정지 래치 상태 — 모션 버튼이 잠겼습니다. 복구는 [초기화].
</div>
<main>
  <div id="msg" style="padding:0 2px"></div>

  <div class="card">
    <h2>설정</h2>
    <div class="row">
      <label>센소리움 버전 <select id="sensorium" onchange="pushSettings()"></select></label>
      <span class="sub" id="verInfo"></span>
    </div>
    <div class="desc" style="margin-top:6px">센소리움 버전 = 기기 정의(펌프 모델·펌프 수·통신 방언) — 연결 방식이 이 선택을 따릅니다. 세부 설정은 각 탭(펌프/밸브)에서.</div>
    <!-- 연결 = 설정을 다 고른 뒤 하는 명시 행위(개편 2026-09-03) — 그래서 버튼이 설정 아래에 있다.
         [연결]/[연결 해제] 두 버튼(오픈-클로즈 대칭) — 연결은 해제 전까지 유지, 자동 재연결 없음.
         발견 프로브는 양 기종 모두 `?`(리포트) — 방언 차이는 어댑터가 소유한다(UI 분기 금지). -->
    <div class="row" style="margin-top:12px;padding-top:12px;border-top:1px solid var(--line,#2a3340);align-items:center">
      <button id="connectBtn" onclick="doConnect()" title="위 설정(센소리움 버전=기기 모델)의 방식으로 펌프를 인식·연결합니다 — 해제 전까지 유지">🔌 연결</button>
      <button id="disconnectBtn" onclick="doDisconnect()" title="연결을 명시적으로 해제합니다">⏏ 연결 해제</button>
      <span id="connInfo" class="sub" style="font-weight:600"></span>
      <span id="busy" class="busy"></span>
    </div>
  </div>

  <nav class="setnav" id="setnav"></nav>
  <div id="workHint" class="desc" style="display:none">🔒 아래 작업 섹션은 <b>연결 후</b> 사용할 수 있습니다 — 위에서 설정을 확인하고 [🔌 연결]을 누르세요.</div>

  <!-- ═══ 탭 A. 펌프 제어 — 위→아래 = 실제 작업 순서 ═══ -->
  <div class="card" id="sec-pump-control">
    <h2>펌프 제어</h2>
    <div class="desc">벤치 전용(배관·액체 없음 전제 — 운영 기기는 admin/데몬). 아래 순서대로: 설정 → ① 초기화 → ② 흡입/배출.</div>

    <h3>펌프 설정</h3>
    <div class="row">
      <label>시린지 용량(mL) <select id="cap" onchange="pushSettings()"></select></label>
      <span class="sub">용량 = 플런저 슬라이더 상한·스텝 파생·초기화 힘의 기준</span>
    </div>

    <h3>기기 연결 상태</h3>
    <table id="connTbl"><tbody></tbody></table>

    <h3>① 홈 기준 잡기 — 초기화 <span class="sub">(연결 후 첫 단계 · 이걸 해야 ②가 열립니다)</span></h3>
    <div class="desc">홈 복귀 = 플런저를 끝(전량 배출 위치)까지 밀어냄 — <b>실린 액체는 밸브가 향한
      포트로 전부 나갑니다</b>. 그래서 배출구를 골라야 하고, 초기화는 그 포트를 향한 채 홈으로
      복귀합니다(끝나면 그 포트에 주차 — "밸브가 쉴 땐 배출구").</div>
    <div class="row">
      <label>배출구 <select id="initPort" style="width:120px"></select></label>
      <button id="initBtn" class="primary" onclick="doInit()">초기화</button>
      <span class="sub">힘-전용 Z(포트 피연산자 없음) — 플런저 홈 복귀 + 위치 기준 확정</span>
    </div>

    <h3 id="plungerTitle">② 흡입 · 배출</h3>
    <div class="desc"><b>포트를 고르고 → 양·속도를 정하고 → [흡입]/[배출]</b>.
      둘 다 정한 양만큼 — 흡입은 그 포트에서 빨아올리고, 배출은 그 포트로 밀어냅니다
      (실린 양보다 많이는 거부). 안 되는 조합은 기기가 err로 거부하고 그대로 표시됩니다.</div>
    <div class="row">
      <label>펌프 <select id="plPump"></select></label>
      <label>포트 <select id="dtIn" style="width:110px"></select> <span class="sub" id="valveInfoLab"></span></label>
      <span class="sliderrow" style="flex:1;min-width:240px">
        <input type="range" id="plVol" min="0" step="1" value="50" oninput="$('plVolV').textContent=this.value+' µL'">
        <span class="sv" id="plVolV">50 µL</span>
      </span>
      <label>용도 프리셋 <select id="spdPreset" onchange="applySpeedPreset()" style="width:150px">
        <option value="">직접 입력</option>
        <option value="careful">조심 — 첫 점검</option>
        <option value="standard">표준 벤치</option>
        <option value="ops">운영 재현</option>
        <option value="viscous">점성 액체</option>
        <option value="limit">한계 탐색 ⚠️</option>
      </select></label>
      <label>흡입 속도(Hz) <input id="dtAsp" type="number" min="50" max="6000" value="200" style="width:84px"><span class="sub" id="aspRange"></span></label>
      <label>배출 속도(Hz) <input id="dtDisp" type="number" min="50" max="6000" value="400" style="width:84px"><span class="sub" id="dispRange"></span></label>
      <label>가속 경사(L) <input id="dtSlope" type="number" min="1" max="20" value="14" style="width:64px"><span class="sub" id="slopeRange"></span></label>
    </div>
    <div class="row" style="margin-top:6px">
      <button id="aspBtn" class="primary" onclick="doPumpIo('aspirate')">▼ 이 포트에서 흡입</button>
      <button id="dispBtn" onclick="doPumpIo('dispense')">▲ 이 포트로 배출</button>
      <span class="sub">현재 위치: <b id="plPos">—</b> steps</span>
      <span id="dtResult" class="sub"></span>
    </div>

    <details style="margin-top:10px">
      <summary style="cursor:pointer;font-size:12.5px;color:var(--sub)">📋 용도별 판단표 — 예시 상황별 속도·경사 설정 근거 (위 프리셋과 동일 값)</summary>
      <div class="desc" style="margin:8px 0 6px">숫자 = 흡입/배출 속도(Hz) / 가속 경사(L). <b>같은 Hz ≠ 같은 유량</b> —
        Runze 축 12000 vs Tecan 축 3000 스텝이라 스텝 굵기가 4배 달라, 같은 판단이라도 기종별 Hz 가 다릅니다.
        연결된 기종의 열이 강조됩니다. [적용]을 누르면 위 입력칸에 그대로 들어갑니다.</div>
      <table id="presetTbl">
        <thead><tr><th style="width:110px">예시 상황</th><th>판단</th>
          <th class="col-sy" style="width:130px">Runze(12000축)</th>
          <th class="col-tec" style="width:130px">Tecan(3000축)</th><th style="width:56px"></th></tr></thead>
        <tbody>
          <tr><td><b>첫 점검</b><br><span class="sub">처음 보는 기기·수리 직후</span></td>
              <td>탈조 위험을 0에 수렴시키고 소리·움직임 관찰이 목적. 유량 최소·완만한 가속.</td>
              <td class="col-sy num">1600 / 1600 / L7</td><td class="col-tec num">400 / 400 / L7</td>
              <td><button onclick="usePreset('careful')">적용</button></td></tr>
          <tr><td><b>표준 벤치</b><br><span class="sub">일상 동작 확인</span></td>
              <td>공장 기본 유량대. 실기기 실측으로 검증한 구간(2026-09-03).</td>
              <td class="col-sy num">2000 / 6000 / L14</td><td class="col-tec num">800 / 1400 / L14</td>
              <td><button onclick="usePreset('standard')">적용</button></td></tr>
          <tr><td><b>운영 재현</b><br><span class="sub">admin과 같은 조건</span></td>
              <td>운영 기본값의 유량을 그대로 재현(현장 검증값). 정비 후 "운영 조건에서 되나" 확인용.</td>
              <td class="col-sy num">5000 / 6000 / L14</td><td class="col-tec num">1250 / 1500 / L14</td>
              <td><button onclick="usePreset('ops')">적용</button></td></tr>
          <tr><td><b>점성 액체</b><br><span class="sub">오일·시럽류</span></td>
              <td>흡입을 확 낮춰 기포·미충전 방지 — 액이 플런저를 못 따라오는 게 문제라 흡입이 급소.</td>
              <td class="col-sy num">1000 / 3000 / L7</td><td class="col-tec num">300 / 700 / L7</td>
              <td><button onclick="usePreset('viscous')">적용</button></td></tr>
          <tr><td><b>한계 탐색 ⚠️</b><br><span class="sub">탈조 경계 실측</span></td>
              <td>상한 풀개방. 탈조가 나면 위치 기준이 어긋나니 <b>끝나면 반드시 [초기화]</b>.</td>
              <td class="col-sy num">6000 / 6000 / L20</td><td class="col-tec num">6000 / 6000 / L20 ⚠️<br><span class="sub">(유량은 Runze의 4배)</span></td>
              <td><button onclick="usePreset('limit')">적용</button></td></tr>
        </tbody>
      </table>
    </details>

    <div class="row" style="margin-top:14px;border-top:1px solid var(--line);padding-top:12px">
      <button class="danger" onclick="doEstop()">⛔ 긴급 정지</button>
      <span class="sub">언제든 — 전 펌프 TR + 래치(복구는 [초기화])</span>
    </div>
  </div>

  <!-- ═══ 탭 B. 밸브 제어 = 기주 솔레노이드(우리가 "밸브"라 부르는 것 · 2026-09-03 정의 확정).
       펌프 헤드의 회전 밸브는 펌프의 일부 → 펌프 제어 ③. ═══ -->
  <div class="card" id="sec-valve-control" style="display:none">
    <h2>밸브 제어</h2>

    <h3>기주 솔레노이드 <span class="sub">(라즈베리파이 GPIO 전용 · 최대 2개)</span></h3>
    <div id="gpioValveWrap">
    <div class="desc">한 번에 1개만 열립니다(상호배타) · 최대 10초 뒤 자동 닫힘 · 긴급 정지 시 즉시 닫힘.</div>
    <div id="valveUnavail" class="desc" style="display:none;color:var(--warn)"></div>
    <table id="valveTbl"><tbody>
      <tr><td style="width:110px"><b>기주 1</b></td><td>
        <span class="row">
          <span id="vstate-sour" class="sub" style="min-width:88px">닫힘</span>
          <button onclick="valveLatch('sour')">스위치 ON (10초)</button>
          <button onclick="valveOff('sour')">OFF</button>
          <label style="flex-direction:row;align-items:center;gap:6px">
            <input id="vsec-sour" type="number" min="1" max="10" value="3" style="width:64px">초
          </label>
          <button onclick="valveOpenFor('sour')">🚰 열었다 닫기</button>
        </span></td></tr>
      <tr><td><b>기주 2</b></td><td>
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
  </div>

  <div class="card"><h2>로그 <span class="sub">(pi daemon 구조화 로그 그대로)</span>
    <label style="flex-direction:row;display:inline-flex;gap:4px;margin-left:10px;font-size:12px">
      <input type="checkbox" id="showDebug"> 시리얼 왕복(DEBUG)도 표시</label>
    <span style="float:right;display:flex;gap:6px">
      <button class="sm" style="padding:3px 10px;font-size:12px" onclick="copyLog()" title="화면의 로그 전체를 클립보드로">📋 복사</button>
      <button class="sm" style="padding:3px 10px;font-size:12px" onclick="clearLog()" title="화면의 로그를 비웁니다(이후 로그는 계속 쌓임)">🗑 지우기</button>
    </span></h2>
    <div id="log"></div></div>
</main>
<script>
let S = {pumps:[], busy:null, connected:false, estop:false, mode:'fragrance'};
let lastLog = 0, lastHealth = {}, lastState = null;
const SECTIONS = [
  {id:'sec-pump-control', label:'펌프 제어'},
  {id:'sec-valve-control', label:'밸브 제어'},
];
// 액체 카탈로그(선택지) — 서버 시드와 동일 소스. 역할 4종 + 계열별 액체 한글 라벨.
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
    const b=document.createElement('button');
    b.textContent=s.label; b.className=(curSection===s.id)?'on':'';
    // 단계 일관성 — 작업 탭(모션·진단)은 연결 후에만 진입 가능. 포트 매핑은 설정 영역이라 항상.
    b.disabled = !S.connected;
    b.title = b.disabled ? '연결 후 사용할 수 있습니다' : '';
    b.onclick=()=>{ curSection=s.id; renderNav(); renderSections(); };
    nav.appendChild(b);
  }
}
function renderSections(){
  for (const s of SECTIONS) $(s.id).style.display=(curSection===s.id)?'block':'none';
}

function renderState(s) {
  lastState = s;
  if (s._net) return;
  const modeChanged = s.mode!==S.mode;
  onConnectChange(s);
  S = s;
  $('busy').textContent = s.busy ? ('⏳ '+s.busy+' 진행 중…') : '';
  $('estopBanner').style.display = s.estop ? 'block' : 'none';
  $('connInfo').textContent = s.connected
    ? `🟢 연결됨: ${s.port} · 펌프 ${s.pumps.join(', ')}`
    : (s.connecting ? '🔄 연결 중… (아래 로그에서 진행 확인)' : '⚪ 미연결');
  // 오픈-클로즈 두 버튼(2026-09-03) — 연결 중이면 [연결] 잠금, 미연결이면 [해제] 잠금. busy 는 둘 다.
  $('connectBtn').disabled = !!s.busy || s.connected || !!s.connecting;
  $('disconnectBtn').disabled = !!s.busy || !s.connected;
  // 단계 일관성(2026-09-03) — 화면 = ①설정 → ②연결 → ③작업. 미연결이면 작업 섹션(모션·진단)을
  //   잠가 "연결 전 = 설정만"을 시각으로 못박는다. 포트 매핑은 설정 영역이라 항상 열림(FAIL-1).
  for (const id of ['sec-pump-control','sec-valve-control']) {
    const el = $(id); if (el) el.classList.toggle('locked', !s.connected);
  }
  $('workHint').style.display = s.connected ? 'none' : 'block';
  const sv=$('sensorium');
  if (sv.options.length===0 && s.versions)
    s.versions.forEach(v=>{const o=document.createElement('option');o.value=v.id;o.textContent=v.label;sv.appendChild(o);});
  if (document.activeElement!==sv) sv.value = s.sensorium;   // 드롭다운 조작 중 덮어쓰기 방지
  sv.disabled = !!s.busy;                                     // 작업 중 버전 전환 잠금(서버 409와 짝)
  const ver = (s.versions||[]).find(v=>v.id===s.sensorium);
  const verPumpsOk = !s.connected || !ver || JSON.stringify(ver.pumps)===JSON.stringify(s.pumps);
  $('verInfo').textContent = (ver ? `펌프 ${ver.pumps.join(',')} · 기기 ${s.pumpModelLabel||ver.pumpModel} · AI 도장 ${ver.aiModel}` : '')
    + (s.pumpModelAvailable===false ? ' ⚠️ 이 기기 구현체 미설치(senlyt-pi 핀 갱신 필요) — 연결 거부됨' : '')

    + (verPumpsOk ? '' : ` — ⚠️ 버전 펌프(${ver.pumps.join(',')})와 발견 펌프(${s.pumps.join(',')})가 다릅니다`);
  const cap=$('cap');
  if (cap.options.length===0) s.capacities.forEach(c=>{const o=document.createElement('option');o.value=c;o.textContent=c;cap.appendChild(o);});
  if (document.activeElement!==cap) cap.value = s.capacityMl;
  cap.disabled = !!s.busy;                                    // 작업 중 용량 변경 잠금(P1-1 서버 409와 짝)
  // ② 플런저 슬라이더 — 상한 = 시린지 용량(µL). 절대 위치라 반복해도 축적 없음.
  const capUl = Math.round(s.capacityMl*1000);
  const pv=$('plVol');
  if (+pv.max !== capUl) { pv.max=capUl; if(+pv.value>capUl){pv.value=capUl;} $('plVolV').textContent=pv.value+' µL'; }
  // 속도·경사 유효 범위 — 서버 클램프 SoT(state.speedRanges)를 입력 min/max + 라벨로 반영.
  if (s.speedRanges) {
    const rr = {aspirate:['dtAsp','aspRange'], dispense:['dtDisp','dispRange'], slope:['dtSlope','slopeRange']};
    for (const k in rr) {
      const [lo,hi]=s.speedRanges[k]||[]; const inp=$(rr[k][0]), lab=$(rr[k][1]);
      if (lo!==undefined && inp) { inp.min=lo; inp.max=hi; if(lab) lab.textContent=` ${lo}~${hi}`; }
    }
  }
  renderNav(); renderSections();
  fillPumpSelect('plPump', s);
  fillPortSelects(s);
  // 밸브 상태(낙관 표시)
  $('gpioValveWrap').style.display = s.mode==='flavor' ? '' : 'none';
  if (s.mode==='flavor') {
    $('valveUnavail').style.display = s.valveError ? 'block' : 'none';
    if (s.valveError) $('valveUnavail').textContent = '밸브(GPIO) 사용 불가: '+s.valveError;
    for (const b of ['sour','normal']) {
      const remain = (s.valveOpen||{})[b]||0;
      $('vstate-'+b).textContent = remain>0 ? `열림 · ${remain}초` : '닫힘';
      $('vstate-'+b).style.color = remain>0 ? 'var(--ok)' : 'var(--sub)';
    }
  }
  const motionLocked = !!s.busy || !s.connected;  // 용량 확인 게이트 제거(2026-09-03) — 연결이 관문.
  // 기기 연결 상태 표
  const ct=$('connTbl').querySelector('tbody'); ct.innerHTML='';
  for (const p of s.pumps) {
    const tr=document.createElement('tr');
    tr.innerHTML=`<td style="width:140px"><b>${s.pumpLabels[p]||('펌프 '+p)}</b> <span class="sub">(주소 ${p})</span></td>
      <td><span class="pill unknown" id="hp${p}">?</span></td>`;
    ct.appendChild(tr); paintHealth(p, lastHealth[p]);
  }
  // ②③·회전 공통 모션 게이트 — 연결 + ①초기화 완료가 전제(위→아래 순서를 코드로도 강제).
  const needInit = s.connected && !s.initializedAfterConnect;
  $('plungerTitle').innerHTML = '② 흡입 · 배출'
    + (needInit ? ' <span class="sub">— 🔒 ① 초기화 후 열립니다</span>' : '');
  const motionDis = motionLocked || s.estop || needInit;
  // ⚠️ 버튼까지 전부 잠근다(2026-09-03 버그 픽스 — 입력칸만 잠가 estop 중에도 버튼이 활성으로
  //   보였다). 초기화만 예외: estop 복구 경로라 연결돼 있으면 항상 살아있다.
  for (const id of ['plVol','dtIn','dtAsp','dtDisp','dtSlope','spdPreset','aspBtn','dispBtn','plPump'])
    { const el=$(id); if(el) el.disabled=motionDis; }
  $('initBtn').disabled = !s.connected || !!s.busy;
  if ($('initPort')) $('initPort').disabled = !s.connected || !!s.busy;
  // 판단표 — 현재 기종 열 강조(SPEED_PRESETS 선택 로직과 같은 키)
  const pt=$('presetTbl');
  if (pt) pt.className = s.pumpModel==='tecan_xcalibur' ? 'm-tec' : (s.pumpModel ? 'm-sy' : '');
  // 지문 불일치 무시 체크박스는 UI 에서 제거(2026-09-04 사용자 — '뭔지 모르겠음').
  //   서버 탈출구(allowFpMismatch)는 유지 — 클론 오탐 시 API 로만 켠다(평상시 노출 불필요).
}

// 용도별 속도 프리셋(2026-09-03) — 같은 "판단"을 기종 축(12000/3000 스텝)에 맞는 Hz 로 번역.
//   같은 Hz ≠ 같은 유량(스텝 굵기 4배 차) — 그래서 기종별 값이 다르다. [asp, disp, slope].
const SPEED_PRESETS = {
  careful:  { sy01b:[1600,1600,7],  tecan_xcalibur:[400,400,7]   },  // 첫 점검·수리 직후 — 관찰 목적
  standard: { sy01b:[2000,6000,14], tecan_xcalibur:[800,1400,14] },  // 일상 벤치(실측 검증 구간)
  ops:      { sy01b:[5000,6000,14], tecan_xcalibur:[1250,1500,14]},  // admin 운영 기본의 유량 재현
  viscous:  { sy01b:[1000,3000,7],  tecan_xcalibur:[300,700,7]   },  // 점성 — 흡입 기포·미충전 방지
  limit:    { sy01b:[6000,6000,20], tecan_xcalibur:[6000,6000,20]},  // 탈조 경계 실측 — 끝나면 ①초기화
};
function usePreset(k){ $('spdPreset').value=k; applySpeedPreset(); }  // 판단표 [적용] 버튼
function applySpeedPreset(){
  const k=$('spdPreset').value; if(!k) return;
  const model=(lastState&&lastState.pumpModel)||'sy01b';
  const p=(SPEED_PRESETS[k]||{})[model];
  if(!p){ $('dtResult').textContent='이 기종의 프리셋 값이 없습니다 — 직접 입력하세요'; $('spdPreset').value=''; return; }
  $('dtAsp').value=p[0]; $('dtDisp').value=p[1]; $('dtSlope').value=p[2];
  $('dtResult').textContent = k==='limit'
    ? '⚠️ 한계 탐색 — 탈조(위치 어긋남) 가능. 시험 후 [초기화]로 홈 기준 재확정'
    : '';
}
document.addEventListener('input', e=>{
  if(e.target && ['dtAsp','dtDisp','dtSlope'].includes(e.target.id)) $('spdPreset').value='';
});

async function doPumpIo(op){
  const body={ op, pump: parseInt($('plPump').value), port: $('dtIn').value,
    volumeUl: parseFloat($('plVol').value),
    aspHz: parseInt($('dtAsp').value), dispHz: parseInt($('dtDisp').value),
    slope: parseInt($('dtSlope').value) };
  $('dtResult').textContent='실행 중…';
  const r = await jfetch('/api/plunger', body);
  if (r.position!==undefined && r.position!==null) $('plPos').textContent = r.position;
  $('dtResult').textContent = r.ok ? '✅ '+(r.label||'정상') : '❌ '+(r.label||r.error||'실패');
  refreshState();
}
function fillPortSelects(s){
  // 밸브 구성 판독(?76) "활용-아니면-무시"(2026-09-03) — 기기가 자기 밸브를 보고하면 콤보를
  //   그에 맞춰(방향형=IR/OR 만 · N-port 분배=PN 까지), 못 알아보면 정적 폴백(양 매뉴얼 공통
  //   최대 12포트 + 방향). 어느 쪽이든 판정은 기기 — 안 맞는 선택은 err3 로 정직하게 거부된다.
  const vi = s.valveInfo || null;
  const max = vi && vi.ports ? vi.ports : 12;
  const directionalOnly = !!(vi && vi.kind==='directional');
  for (const id of ['dtIn']) {
    const sel=$(id); if(!sel) return;
    const cur=sel.value;
    const want = vi ? (vi.kind+':'+(vi.ports||'')) : ('static'+max);
    if (sel.dataset.built===want) continue;
    sel.dataset.built=want;
    sel.innerHTML='';
    // 암묵적 "현 방향 유지" 없음(2026-09-03 사용자 확정) — 모든 동작은 포트/방향을 **명시 선택**.
    //   밸브가 어쩌다 향해 있던 방향에 의존하는 비결정성을 제거한다(서버도 미선택=400).
    // 표기는 프로토콜 그대로(2026-09-03 사용자 확정 — 인위적 P번호 통일 금지): 방향형은
    //   IR/OR 두 명령이 전부고, 분배형만 번호(I{n}/O{n})가 실존한다. UI = 명령 계열의 거울.
    for (const [v,t] of [['i','입력측(IR)'],['o','배출측(OR)']]) {
      const o=document.createElement('option'); o.value=v; o.textContent=t; sel.appendChild(o); }
    if (!directionalOnly)
      for (let i=1;i<=max;i++){ const o=document.createElement('option'); o.value=i; o.textContent='P'+i; sel.appendChild(o); }
    if ([...sel.options].some(o=>o.value===cur)) sel.value=cur;
  }
  const lab=$('valveInfoLab');
  if (lab) lab.textContent = vi ? `기기 보고: ${vi.label}` : (s.connected ? '밸브 미판독 — P1~12 폴백' : '');
  // ① 배출구 콤보(2026-09-03 사용자 확정 — "홈 복귀는 배출구를 향하고") — 방향형이면 배출측
  //   하나뿐이라 자동 선택, 분배형/미판독은 명시 선택 요구(placeholder·서버도 미선택=400).
  const ip=$('initPort');
  if (ip) {
    const want='init:'+(vi ? (vi.kind+':'+(vi.ports||'')) : ('static'+max));
    if (ip.dataset.built!==want) {
      ip.dataset.built=want; const cur=ip.value; ip.innerHTML='';
      if (directionalOnly) {
        const o=document.createElement('option'); o.value='o'; o.textContent='배출측(OR)'; ip.appendChild(o);
      } else {
        const ph=document.createElement('option'); ph.value=''; ph.textContent='배출구 선택…'; ip.appendChild(ph);
        if (!vi) { const o=document.createElement('option'); o.value='o'; o.textContent='배출측(OR·3-way)'; ip.appendChild(o); }
        for (let i=1;i<=max;i++){ const o=document.createElement('option'); o.value=i; o.textContent='P'+i; ip.appendChild(o); }
      }
      if ([...ip.options].some(o=>o.value===cur)) ip.value=cur;
    }
  }
}
function fillPumpSelect(id, s){
  const sel=$(id); if(!sel) return;
  const cur=sel.value;
  sel.innerHTML='';
  for (const p of s.pumps){ const o=document.createElement('option'); o.value=p; o.textContent=(s.pumpLabels&&s.pumpLabels[p])||('펌프 '+p); sel.appendChild(o); }
  if ([...sel.options].some(o=>o.value===cur)) sel.value=cur;
}
async function doDisconnect(){
  const r = await jfetch('/api/disconnect', {});
  msg(r.error || '연결 해제 — 재연결은 [🔌 연결] 버튼으로', !r.error);
  await refreshState();
}
async function doConnect(){
  msg(`연결 중 — 설정된 기기 방식으로 인식합니다… (펌프 24V 전원 확인)`, true);
  const r = await jfetch('/api/connect', {});
  // 성공 피드백은 설정 줄의 🟢 연결됨 한 곳(상태 SoT 일원화·2026-09-03) — 상단 메시지는 오류만.
  if (r.ok) { msg('', true); await refreshState(); refreshHealth(); }
  else msg(r.error||'연결 실패', false);
}
let wasConnected=false;
function onConnectChange(s){ // 자동 연결이 붙으면 타일·상태를 갱신(연결 카드 없이도 반응).
  if (s.connected && !wasConnected) { refreshHealth(); }
  wasConnected = s.connected;
}

async function pushSettings(){
  const r = await jfetch('/api/settings', {sensorium:$('sensorium').value, capacityMl:parseFloat($('cap').value)});
  if (r.error) { msg(r.error,false); refreshState(); } else { renderState(r); }
}

async function refreshState(){ renderState(await jfetch('/api/state')); }

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

async function doInit(){
  const drain=$('initPort').value;
  if(!drain){ msg('배출구를 먼저 선택하세요 — 홈 복귀는 실린 액체를 그 포트로 밀어냅니다.', false); return; }
  const drainLabel = drain==='o' ? '배출측(OR)' : ('P'+drain);
  if (!confirm(`모든 펌프(${S.pumps.join(',')})를 ${drainLabel} 를 향한 채 홈으로 복귀시킵니다(실린 액체는 그쪽으로 배출). 진행 중 작업은 중단됩니다. 계속할까요?`)) return;
  msg('초기화 중… (홈 확인 즉시 완료 — 최대 30초)', true);
  const r = await jfetch('/api/init', {port: drain});
  if (r.error && !r.results) { msg(r.error,false); return; }
  for (const [p,res] of Object.entries(r.results||{})) setRes(p,res);
  msg(r.ok ? `초기화 완료 (${r.elapsedS}s)` : '일부 펌프 초기화 실패 — 결과 확인', r.ok);
  refreshState(); refreshHealth();
}

async function doEstop(){
  const r = await jfetch('/api/estop', {});
  for (const [p,st] of Object.entries(r.pumps||{})) paintHealth(p, st);
  msg(r.ok ? '⛔ 긴급 정지 발동 — 복구는 [초기화]' : (r.note||r.error||'정지 검증 실패 — 24V 전원을 차단하세요'), r.ok);
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

function clearLog(){
  $('log').innerHTML='';
  msg('로그 화면을 비웠습니다 — 이후 로그는 계속 쌓입니다.', true);
}
async function copyLog(){
  const text = [...$('log').childNodes].map(n=>n.textContent).join('\\n');
  if (!text) { msg('복사할 로그가 없습니다.', false); return; }
  try {
    await navigator.clipboard.writeText(text);
    msg(`로그 ${$('log').childNodes.length}줄을 클립보드로 복사했습니다.`, true);
  } catch (e) {  // http(비보안 컨텍스트) 폴백 — execCommand 경로.
    const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta);
    ta.select(); const ok=document.execCommand('copy'); ta.remove();
    msg(ok ? `로그 ${$('log').childNodes.length}줄을 클립보드로 복사했습니다.` : '복사 실패 — 브라우저 권한을 확인하세요.', ok);
  }
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
setInterval(refreshState, 2500);
setInterval(pollLogs, 1200);
</script>
</body></html>"""
