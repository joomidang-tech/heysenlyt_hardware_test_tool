"""hwtool — 시린지펌프 정비 툴 (헥사고날 구조).

의존 방향(한쪽으로만): core ← adapters ← service ← web ← app.py(조립)

  core/      도메인 — 순수 상수·레지스트리·파생 (Flask·시리얼·전역 STATE 무의존 → 단위테스트 대상)
  adapters/  아웃바운드 — 기기모델→EnginePort 구현체 결선·GPIO 밸브 (실물 경계)
  service/   유스케이스 — 전역 STATE·락·게이트·연결/정비 오케스트레이션 (Flask 무의존 → 테스트 가능)
  web/       인바운드 — Flask 라우트(얇게) + UI HTML

포트(인터페이스)는 이 툴이 새로 정의하지 않는다 — **운영 pi daemon 의 `senlyt_pi.ports.EnginePort`
가 그 포트**이고, 이 툴은 그 계약의 소비자다(재구현 금지 원칙 그대로).
"""
