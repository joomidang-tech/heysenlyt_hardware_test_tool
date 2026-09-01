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
  <label class="sub" style="display:flex;flex-direction:row;align-items:center;gap:4px" title="끄면 주기 자동 인식이 멈춥니다 — 수동 ⟳만 동작">
    <input type="checkbox" id="autoConn" checked onchange="toggleAutoConnect()"> 자동 연결
  </label>
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
    : (s.autoConnect===false ? '⚪ 미연결 (자동 연결 꺼짐 — ⟳로 수동 인식)'
                             : '⚪ 자동 인식 중… (USB-RS485·펌프 24V 전원 확인)');
  if (document.activeElement!==$('autoConn')) $('autoConn').checked = s.autoConnect!==false;
  const sv=$('sensorium');
  if (sv.options.length===0 && s.versions)
    s.versions.forEach(v=>{const o=document.createElement('option');o.value=v.id;o.textContent=v.label;sv.appendChild(o);});
  if (document.activeElement!==sv) sv.value = s.sensorium;   // 드롭다운 조작 중 덮어쓰기 방지
  sv.disabled = !!s.busy;                                     // 작업 중 버전 전환 잠금(서버 409와 짝)
  const ver = (s.versions||[]).find(v=>v.id===s.sensorium);
  const verPumpsOk = !s.connected || !ver || JSON.stringify(ver.pumps)===JSON.stringify(s.pumps);
  $('verInfo').textContent = (ver ? `펌프 ${ver.pumps.join(',')} · 기기 ${s.pumpModelLabel||ver.pumpModel} · AI 도장 ${ver.aiModel}` : '')
    + (s.pumpModelAvailable===false ? ' ⚠️ 이 기기 구현체 미설치(senlyt-pi 핀 갱신 필요) — 연결 거부됨' : '')
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

async function toggleAutoConnect(){
  const on = $('autoConn').checked;
  const r = await jfetch('/api/settings', {autoConnect: on});
  msg(r.error || (on ? '자동 연결 켬 — 미연결이면 3초 주기로 재인식합니다'
                     : '자동 연결 끔 — 수동 [⟳ 다시 인식]만 동작합니다'), !r.error);
  refreshState();
}

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
