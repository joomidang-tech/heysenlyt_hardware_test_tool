#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start.py — 파이썬 단독 "설치 + 실행" 원샷 런처 (라즈베리파이 4B / 64bit)
=====================================================================

    python3 start.py

하는 일 (파이썬만으로):
  1) flask·pyserial·senlyt_pi 가 이미 있으면 → 그냥 app.py 실행
  2) 없으면 → 가상환경(.venv) 만들고 requirements.txt 설치 후 실행
  3) venv 불가(python3-venv 미설치) → pip --break-system-packages 폴백
  4) 그래도 실패 → 정확한 apt 설치 명령 안내

bash 불필요. 최신 Pi OS(Bookworm)의 pip 차단(PEP 668)도 자동 우회한다.
⚠️ senlyt-pi 의존성이 git+https 라 **git 이 필요**하다(미설치 시 안내).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
REQS = os.path.join(HERE, "requirements.txt")
VENV = os.path.join(HERE, ".venv")
IS_WIN = os.name == "nt"
VENV_PY = os.path.join(VENV, "Scripts" if IS_WIN else "bin", "python.exe" if IS_WIN else "python")


def has_deps(py):
    """해당 파이썬에 flask·pyserial·senlyt_pi 가 import 되는지."""
    return subprocess.run(
        [py, "-c", "import flask, serial, senlyt_pi"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def pip_install(py, extra=None):
    subprocess.run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"], check=False)
    cmd = [py, "-m", "pip", "install", "-q", "-r", REQS] + (extra or [])
    return subprocess.run(cmd).returncode == 0


def print_access_info():
    ip = ""
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3)
        ip = (out.stdout or "").split()[0] if out.stdout.strip() else ""
    except Exception:
        pass
    print("\n" + "=" * 54)
    print("  브라우저에서 접속:")
    print("    · 이 Pi 화면:  http://localhost:8000")
    if ip:
        print(f"    · 다른 기기:    http://{ip}:8000")
    print("  종료: Ctrl+C")
    print("=" * 54 + "\n", flush=True)


def check_ui_js():
    """UI 스크립트 문법 게이트(재발 방지) — PAGE 내장 JS 를 추출해 node --check.

    JS SyntaxError 는 스크립트 블록 전체를 죽여 **긴급 정지 버튼까지 무력화**한다(실사고:
    const 재선언). node 가 없으면(순정 Pi) 조용히 건너뛴다 — 개발 머신 게이트.
    """
    import re, shutil, tempfile
    if shutil.which("node") is None:
        return
    src = open(APP, encoding="utf-8").read()
    m = re.search(r"<script>(.*)</script>", src, re.S)
    if not m:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(m.group(1))
        path = f.name
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    os.unlink(path)
    if r.returncode != 0:
        sys.exit(f"❌ UI 스크립트 문법 오류 — 화면 버튼 전체(긴급 정지 포함)가 죽습니다:\n{r.stderr}")


def run(py):
    check_ui_js()
    print_access_info()
    # 프로세스 교체 (Ctrl+C 그대로 전달)
    os.execv(py, [py, APP])


def main():
    if not os.path.exists(APP):
        sys.exit(f"❌ app.py 를 찾을 수 없습니다: {APP}")

    # 1) 현재 파이썬에 이미 있으면 바로 실행
    if has_deps(sys.executable):
        run(sys.executable)

    print("▶ 의존성(flask·pyserial·senlyt_pi)이 없습니다. 설치를 시도합니다...")
    if subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode != 0:
        sys.exit("❌ git 이 필요합니다(senlyt-pi 의존성):  sudo apt-get install -y git")

    # 2) 가상환경(venv) 시도
    try:
        if not os.path.exists(VENV_PY):
            print("▶ 가상환경(.venv) 생성 중...")
            import venv
            venv.EnvBuilder(with_pip=True).create(VENV)
        if pip_install(VENV_PY) and has_deps(VENV_PY):
            print("✅ venv 설치 완료")
            run(VENV_PY)
    except Exception as e:
        print(f"⚠️ venv 경로 실패: {e}")

    # 3) --break-system-packages 폴백 (venv 불가 시)
    print("▶ 시스템 파이썬에 직접 설치 시도 (--break-system-packages)...")
    if pip_install(sys.executable, extra=["--break-system-packages"]) and has_deps(sys.executable):
        print("✅ 설치 완료")
        run(sys.executable)

    # 4) 최종 실패 안내
    sys.exit(
        "\n❌ 자동 설치 실패. 아래를 실행 후 다시 시도하세요:\n"
        "    sudo apt-get update && sudo apt-get install -y python3-venv python3-pip\n"
        "    python3 start.py\n"
    )


if __name__ == "__main__":
    main()
