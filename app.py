#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시린지펌프 정비 툴 (v1.3.0) — 진입점(조립만). 본체는 `hwtool/` 패키지(헥사고날 구조).

무엇인가
--------
시린지펌프(RS485)가 연결된 컴퓨터에서 켜서, 브라우저로 펌프를 점검·정비하는 도구다.
화면 구성은 admin 콘솔의 **점검·유지보수 페이지(MaintenancePage) 3섹션을 그대로 미러**한다:

  ① 펌프 제어   — 기기 연결 상태 · 시린지 흡입/배출 · [약한 초기화] · [🧼 세척]
  ② 밸브 제어   — 신기주/베이스 기주 솔레노이드(식향 전용·GPIO) — ON/OFF(10s 자동닫힘)·N초 열기·상호배타
  ③ 진단 도구 · 향료 필링 — 단일 포트 속도 진단(흡입/배출 속도·흡입량 조절) · 순차 향료 필링

주문·제조·서버 연동은 없다 — 유지보수 어휘까지만.

구조 (헥사고날 — 의존 방향은 한쪽으로만: core ← adapters ← service ← web ← 여기)
--------------------------------------------------------------------------------
  hwtool/core/      도메인 — admin 미러 상수·센소리움 레지스트리·포트 배치 파생 (순수·테스트 대상)
  hwtool/adapters/  아웃바운드 — 기기모델→EnginePort 구현체 결선(SY-01B/Tecan XCalibur)·GPIO 밸브
  hwtool/service/   유스케이스 — STATE·락·게이트·연결/정비 오케스트레이션 (Flask 무의존)
  hwtool/web/       인바운드 — Flask 라우트(얇게) + UI HTML
  tests/            core·service 를 시리얼/서버 없이 검증

펌프 제어를 재구현하지 않는다 — 운영 pi daemon 패키지 `senlyt_pi`(v1.3.0 커밋 핀,
requirements.txt)의 EnginePort 구현체를 **그대로 실행**한다. 어느 구현체(SY-01B ↔ Tecan
XCalibur)를 쓸지는 **센소리움 버전의 기기 모델(pumpModel)** 이 결정한다(hwtool/adapters/engines).

⚠️ 로컬 전용·인증 없음 — 같은 네트워크 누구나 펌프를 움직일 수 있다. 정비 시에만 켤 것.
"""

from __future__ import annotations

import threading

from hwtool.core.sensorium import AI_STAMP_SOURCE
from hwtool.service.connection import auto_connect_loop
from hwtool.service.logbus import log
from hwtool.web import create_app

app = create_app()

if __name__ == "__main__":
    log("info", "정비 툴 시작", version="1.3.0", aiStampSource=AI_STAMP_SOURCE)
    # 자동 연결 — 켜면 알아서 인식(수동 버튼은 헤더 ⟳ 재인식만).
    threading.Thread(target=auto_connect_loop, daemon=True).start()
    # threaded=True 필수 — 정비 op 가 도는 동안에도 긴급 정지 요청이 처리돼야 한다.
    app.run(host="0.0.0.0", port=8000, threaded=True)
