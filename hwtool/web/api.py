"""인바운드 HTTP — Flask 라우트(얇게). 판단·상태 변이는 전부 service 계층에 위임한다.

라우트 = ① JSON 파싱 ② service 호출 ③ (payload, status) 를 jsonify 로 감싸기. 그래서
service/core 는 Flask 없이 테스트되고, 이 파일은 배선 실수 외엔 깨질 것이 없다.
"""

from __future__ import annotations

from flask import Flask, jsonify, request

from ..service import connection, maintenance, settings
from ..service.logbus import log, logs_since
from ..service.state import STATE
from .ui import PAGE


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return PAGE

    @app.get("/api/state")
    def api_state():
        return jsonify(settings.state_payload())

    @app.get("/api/tiles")
    def api_tiles():
        return jsonify(settings.tiles_payload())

    @app.post("/api/settings")
    def api_settings():
        payload, status = settings.apply_settings(request.get_json(silent=True) or {})
        return jsonify(payload), status

    @app.post("/api/portmap")
    def api_portmap():
        payload, status = settings.apply_portmap(request.get_json(silent=True) or {})
        return jsonify(payload), status

    @app.post("/api/connect")
    def api_connect():
        """수동 재인식(헤더 ⟳) — USB 교체 직후 등. 평시 연결은 자동 연결 루프가 담당한다.

        연결은 모션이 아니라 OP_LOCK(busy)이 아닌 `_CONNECT_LOCK` 축(검증 FAIL-1) — 단
        정비 작업 중 재인식은 여전히 막는다(모션 중 어댑터 교체 방지·busy 검사만).
        """
        if STATE["busy"]:
            return jsonify({"ok": False, "error": f"다른 작업 진행 중: {STATE['busy']}"}), 409
        body = request.get_json(silent=True) or {}
        payload, status = connection.manual_connect((body.get("port") or "").strip())
        return jsonify(payload), status

    @app.get("/api/health")
    def api_health():
        payload, status = maintenance.health_check()
        return jsonify(payload), status

    @app.post("/api/plunger")
    def api_plunger():
        payload, status = maintenance.run_plunger(request.get_json(silent=True) or {})
        return jsonify(payload), status

    @app.post("/api/weak-init")
    def api_weak_init():
        payload, status = maintenance.weak_init()
        return jsonify(payload), status

    @app.post("/api/clean")
    def api_clean():
        payload, status = maintenance.clean(request.get_json(silent=True) or {})
        return jsonify(payload), status

    @app.post("/api/estop")
    def api_estop():
        """긴급 정지(전체) — daemon 감시 스레드와 동일 호출 + 도달 검증 + 밸브 즉시 닫힘. 락 안 탄다."""
        return jsonify(maintenance.do_estop(list(STATE["pumps"])))

    @app.post("/api/valve")
    def api_valve():
        payload, status = maintenance.valve_action(request.get_json(silent=True) or {})
        return jsonify(payload), status

    @app.post("/api/filling")
    def api_filling():
        payload, status = maintenance.start_filling(request.get_json(silent=True) or {})
        return jsonify(payload), status

    @app.get("/api/logs")
    def api_logs():
        try:
            since = int(request.args.get("since", "0"))
        except ValueError:
            since = 0
        items, last = logs_since(since)
        return jsonify({"logs": items, "last": last})

    @app.errorhandler(Exception)
    def _json_error(e):  # noqa: ANN001
        """예기치 못한 예외도 JSON 으로 — HTML 500 은 UI jfetch 를 조용히 죽인다(검증 P1-8)."""
        from werkzeug.exceptions import HTTPException

        if isinstance(e, HTTPException):
            return e
        log("error", "처리되지 않은 예외", error=str(e)[:200])
        return jsonify({"ok": False, "error": f"내부 오류: {e}"}), 500

    return app
