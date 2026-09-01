#!/usr/bin/env bash
# =============================================================================
# 시린지펌프 테스트 툴 + Cloudflare 임시 터널 — 라즈베리파이 원샷 실행
#
#   chmod +x run_with_tunnel.sh
#   ./run_with_tunnel.sh
#
# run.sh 와 동일하게 venv로 앱을 설치·실행하고, 공개 URL(https://*.trycloudflare.com)
# 을 발급한다. 계정/도메인 불필요. Ctrl+C 로 앱·터널 모두 종료.
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PORT="${1:-8000}"

# 1) venv + 의존성 (run.sh 와 동일 로직)
command -v python3 >/dev/null 2>&1 || { echo "❌ python3 없음: sudo apt-get install -y python3 python3-venv"; exit 1; }
[ -d ".venv" ] || python3 -m venv .venv || { echo "❌ venv 실패: sudo apt-get install -y python3-venv"; exit 1; }
PY="$HERE/.venv/bin/python"
"$PY" -c "import flask, serial, senlyt_pi" >/dev/null 2>&1 || {
  command -v git >/dev/null 2>&1 || { echo "❌ git 필요(senlyt-pi 의존성): sudo apt-get install -y git"; exit 1; }
  echo "▶ 의존성 설치 중 (flask·pyserial·senlyt-pi)..."
  "$HERE/.venv/bin/pip" install --quiet --upgrade pip
  "$HERE/.venv/bin/pip" install --quiet -r "$HERE/requirements.txt"
}

# ⚠️ 터널 = 인증 없는 하드웨어 제어 UI 를 공개 인터넷에 여는 것 — 반드시 명시 동의 후 진행.
echo "⚠️  경고: 발급되는 URL 을 아는 누구나 펌프를 물리적으로 구동할 수 있습니다."
read -r -p "   임시 브링업 테스트 용도로만 열고, 끝나면 즉시 닫겠습니까? [y/N] " ANSWER
[ "${ANSWER:-N}" = "y" ] || { echo "중단합니다."; exit 1; }

# 2) cloudflared 확인
if ! command -v cloudflared >/dev/null 2>&1; then
  cat <<'EOF'
❌ cloudflared 미설치. 라즈베리파이(ARM64)에 설치:
  wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
  sudo dpkg -i cloudflared-linux-arm64.deb
설치 후 다시 실행하세요.
EOF
  exit 1
fi

# 3) 앱 백그라운드 실행
echo "▶ 앱 시작 (localhost:${PORT})"
"$PY" app.py &
APP_PID=$!
cleanup() { echo; echo "■ 종료 중..."; kill "$APP_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
sleep 2

# 4) 임시 터널 (공개 URL 자동 발급)
echo "======================================================================"
echo "▶ Cloudflare 터널 — 아래 https://....trycloudflare.com 이 공개 주소"
echo "======================================================================"
cloudflared tunnel --url "http://localhost:${PORT}"
