"""PL2303 HXN(G 계열) 순수 파이썬 유저스페이스 드라이버 — 커널 드라이버 없이 pyusb 로 직접 구동.

왜 존재하나(2026-09-03): 벤치 맥북에 Prolific PL2303GC(0x067b:0x23c3) USB-RS485 어댑터가
물렸는데 macOS 드라이버가 없어 /dev/cu.* 노드가 안 생겼다. 목표가 "파이썬만으로 해결"이라,
커널 드라이버를 건너뛰고 libusb 유저스페이스에서 칩을 직접 초기화·송수신한다.
(macOS 는 커널 드라이버가 안 붙은 장치만 libusb 로 claim 가능 — 드라이버를 설치하면
오히려 이 경로가 막히고, 그땐 pyserial 정석 경로를 쓰면 된다. 둘은 상호배타.)

설치(파이썬만): pip install pyusb libusb-package
  - libusb-package 가 libusb 바이너리를 pip 로 동봉한다(brew 불필요).

프로토콜 정본 = 리눅스 커널 drivers/usb/serial/pl2303.c 의 TYPE_HXN 분기(2026-09-03 대조):
  - HXN 판별: PID 0x23c3(GC) 등 G 계열. 레거시(HX)의 0x8484/0x0404 init 춤은 **생략**.
  - 벤더 레지스터: read 요청 0x81 / write 요청 0x80 (reqtype 0xC0/0x40) — 레거시는 둘 다 0x01.
  - open 시 리셋: reg 0x07(HXN_RESET) ← 0x03(up|down 파이프 둘 다).
  - 라인 코딩: 클래스 요청 0x20(reqtype 0x21), 7바이트 = baud(LE32)+stop+parity+databits.
    HXN 은 divisor 없이 직접 인코딩(no_divisors) — 9600 이면 그냥 9600 을 싣는다.
  - 흐름제어: reg 0x0a, mask 0x1c, NONE=0x1c (read-modify-write).
  - 엔드포인트: bulk OUT 0x02 · bulk IN 0x83 · (interrupt 0x81 은 모뎀 상태 — 미사용).

⚠️ 미실측: 이 파일은 커널 소스 대조로 작성됐고 실 어댑터로는 아직 안 돌았다 — 첫 실행이
곧 실측이다. 브링업 노트북(tecan_probe_bringup.ipynb) 경로 B가 그 자리.

인터페이스는 pyserial.Serial 의 부분집합(write/read/reset_input_buffer/close/name)만 —
브링업 노트북의 raw_probe 가 pyserial 과 동일 코드로 양쪽을 다 돌 수 있게.
"""

from __future__ import annotations

import struct
import time

PROLIFIC_VID = 0x067B
PL2303GC_PID = 0x23C3  # HXN(G 계열). 다른 G 계열 PID 도 같은 프로토콜.

_REQTYPE_VENDOR_OUT = 0x40
_REQTYPE_VENDOR_IN = 0xC0
_REQTYPE_CLASS_OUT = 0x21
_VENDOR_WRITE_NREQUEST = 0x80  # HXN 전용(레거시 0x01 아님)
_VENDOR_READ_NREQUEST = 0x81
_SET_LINE_REQUEST = 0x20
_SET_CONTROL_REQUEST = 0x22
_CONTROL_DTR = 0x01
_CONTROL_RTS = 0x02
_HXN_RESET_REG = 0x07
_HXN_RESET_BOTH_PIPES = 0x03  # upstream(0x02) | downstream(0x01)
_HXN_FLOWCTRL_REG = 0x0A
_HXN_FLOWCTRL_MASK = 0x1C
_HXN_FLOWCTRL_NONE = 0x1C
_EP_BULK_OUT = 0x02
_EP_BULK_IN = 0x83

_PARITY = {"N": 0, "O": 1, "E": 2, "M": 3, "S": 4}
_STOPBITS = {1: 0, 1.5: 1, 2: 2}


class Pl2303HxnSerial:
    """pyserial.Serial 흉내(부분집합) — PL2303 HXN 을 libusb 로 직접 구동."""

    def __init__(
        self,
        vid: int = PROLIFIC_VID,
        pid: int = PL2303GC_PID,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
        timeout: float = 0.5,
    ) -> None:
        import usb.core  # pip install pyusb

        backend = _libusb_backend()
        dev = usb.core.find(idVendor=vid, idProduct=pid, backend=backend)
        if dev is None:
            raise IOError(
                f"PL2303({vid:04x}:{pid:04x}) 을 USB 에서 못 찾음 — 케이블/허브 확인. "
                "(커널 드라이버가 이미 붙어 있으면 macOS 에선 claim 실패 — 그땐 pyserial 경로로)"
            )
        try:
            dev.set_configuration()
        except Exception:  # noqa: BLE001 — 이미 configured 면 무시(재실행 안전).
            pass
        import usb.util

        # 리눅스(라즈베리파이): 커널 pl2303 드라이버가 이미 붙어 있으면 claim 이 실패한다 —
        #   분리(detach) 후 잡는다. macOS 는 이 API 미지원(NotImplementedError)이지만 애초에
        #   드라이버가 안 붙은 상황에서만 이 클래스를 쓰므로 무시가 정답.
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except Exception:  # noqa: BLE001 — macOS=NotImplementedError·권한 문제 등 전부 "그냥 진행".
            pass
        usb.util.claim_interface(dev, 0)
        self._dev = dev
        self._timeout_ms = int(timeout * 1000)
        self._rxbuf = bytearray()  # in_waiting 근사용 내부 수신 버퍼(SerialLike 계약).
        self.name = f"pyusb:{vid:04x}:{pid:04x}"

        # ── open 시퀀스(pl2303.c HXN 미러): 파이프 리셋 → 라인코딩 → 흐름제어 NONE → DTR/RTS ──
        self._vendor_write(_HXN_RESET_REG, _HXN_RESET_BOTH_PIPES)
        coding = struct.pack(
            "<IBBB", baudrate, _STOPBITS[stopbits], _PARITY[parity], bytesize
        )
        dev.ctrl_transfer(_REQTYPE_CLASS_OUT, _SET_LINE_REQUEST, 0, 0, coding)
        # 흐름제어 NONE — read-modify-write(다른 비트 보존).
        cur = self._vendor_read(_HXN_FLOWCTRL_REG)
        self._vendor_write(
            _HXN_FLOWCTRL_REG, (cur & ~_HXN_FLOWCTRL_MASK) | _HXN_FLOWCTRL_NONE
        )
        dev.ctrl_transfer(
            _REQTYPE_CLASS_OUT, _SET_CONTROL_REQUEST, _CONTROL_DTR | _CONTROL_RTS, 0
        )

    # ── 벤더 레지스터(HXN NREQUEST) ─────────────────────────────────────────
    def _vendor_write(self, reg: int, value: int) -> None:
        self._dev.ctrl_transfer(_REQTYPE_VENDOR_OUT, _VENDOR_WRITE_NREQUEST, reg, value)

    def _vendor_read(self, reg: int) -> int:
        buf = self._dev.ctrl_transfer(_REQTYPE_VENDOR_IN, _VENDOR_READ_NREQUEST, reg, 0, 1)
        return int(buf[0]) if len(buf) else 0

    # ── pyserial 부분집합 ───────────────────────────────────────────────────
    def write(self, data: bytes) -> int:
        return self._dev.write(_EP_BULK_OUT, data, timeout=self._timeout_ms)

    def _usb_read(self, size: int, timeout_ms: int) -> bytes:
        import usb.core

        try:
            got = self._dev.read(_EP_BULK_IN, size, timeout=timeout_ms)
            return bytes(got)
        except usb.core.USBTimeoutError:
            return b""
        except usb.core.USBError as e:  # 일부 백엔드는 timeout 을 일반 USBError 로 낸다.
            if e.errno in (60, 110, None):
                return b""
            raise

    def read(self, size: int = 1) -> bytes:
        """최대 size 바이트 — 내부 버퍼 우선, 부족분은 타임아웃까지 USB 에서. pyserial 미러."""
        if self._rxbuf:
            out = bytes(self._rxbuf[:size])
            del self._rxbuf[:size]
            return out
        return self._usb_read(size, self._timeout_ms)

    @property
    def in_waiting(self) -> int:
        """수신 대기 바이트 수 근사 — 커널 버퍼가 없으므로 짧은(5ms) USB 폴로 내부 버퍼에
        끌어온 뒤 그 길이를 보고한다. 어댑터의 `n=in_waiting; read(n)` 루프(sy01b:480)와 정합."""
        chunk = self._usb_read(64, 5)
        if chunk:
            self._rxbuf.extend(chunk)
        return len(self._rxbuf)

    def reset_input_buffer(self) -> None:
        """수신 잔여 배출 — 내부 버퍼 비움 + 짧은 드레인(리셋 레지스터보다 보수적)."""
        self._rxbuf.clear()
        for _ in range(32):
            if not self._usb_read(64, 30):
                break

    def close(self) -> None:
        import usb.util

        try:
            usb.util.release_interface(self._dev, 0)
            usb.util.dispose_resources(self._dev)
        except Exception:  # noqa: BLE001 — 정리 실패가 재실행을 막지 않게.
            pass


def _libusb_backend():
    """libusb 백엔드 — pip 동봉(libusb-package) 우선, 시스템 libusb 폴백."""
    try:
        import libusb_package

        return libusb_package.get_libusb1_backend()
    except ImportError:
        import usb.backend.libusb1 as libusb1

        be = libusb1.get_backend()
        if be is None:
            raise IOError(
                "libusb 백엔드 없음 — `pip install libusb-package` (파이썬만) 또는 brew install libusb"
            )
        return be


def open_pump_serial(baudrate: int = 9600, timeout: float = 0.5, port: str | None = None):
    """맥/리눅스 공통 진입점 — **같은 코드가 어디서든 열리게** 두 경로를 자동 선택한다.

    ① 커널 경로(pyserial): /dev 노드가 있으면 그걸 연다 — 라즈베리파이 기본(드라이버 내장),
       드라이버 설치된 맥도 이쪽. 프로덕션(senlyt_pi 어댑터)과 동일 경로라 교차검증 가능.
    ② 유저스페이스(pyusb): 노드가 없으면 PL2303 HXN 을 libusb 로 직접 — 드라이버 없는 맥용.
       리눅스에서도 동작(커널 드라이버 자동 detach).

    반환 객체는 두 경로 모두 write/read/reset_input_buffer/close/name 을 제공한다.
    `port` 명시 시 그 /dev 노드만 시도(자동 선택 생략).
    """
    import serial as _pyserial
    import serial.tools.list_ports as _lp

    _EXCLUDE = ("bluetooth", "debug-console", "wlan", "buds")
    if port:
        return _pyserial.Serial(port, baudrate, timeout=timeout)
    cands = [
        p.device
        for p in _lp.comports()
        if not any(h in p.device.lower() for h in _EXCLUDE)
    ]
    # 알려진 시리얼 VID 를 앞으로(프로덕션 KNOWN_ADAPTER 미러 — 힌트일 뿐).
    known_first = sorted(
        cands,
        key=lambda d: 0 if any(t in d.lower() for t in ("usbserial", "ttyusb", "pl2303", "wchusb")) else 1,
    )
    for dev in known_first:
        try:
            s = _pyserial.Serial(dev, baudrate, timeout=timeout)
            print(f"[open_pump_serial] 커널 경로: {dev}")
            return s
        except Exception:  # noqa: BLE001 — 다음 후보.
            continue
    print("[open_pump_serial] /dev 노드 없음 → 유저스페이스(pyusb) 경로")
    return Pl2303HxnSerial(baudrate=baudrate, timeout=timeout)


if __name__ == "__main__":
    # 스모크: 장치 존재 + open 시퀀스만(송수신은 노트북에서). read-only 수준의 안전한 확인.
    s = Pl2303HxnSerial()
    print("✅ PL2303 HXN open 성공:", s.name)
    s.close()
