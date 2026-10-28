"""
arm_bridge.py - host side of the arm's serial protocol, plus a software model of the firmware.

    frame:  0xA5 | LEN | CMD | payload (LEN bytes) | CRC8        CRC-8, poly 0x07, over LEN, CMD, payload

    host -> arm   0x01 SET_ANGLES    5 x uint16 little-endian, servo angles in 0.1 degree
                                     order: yaw, shoulder, elbow, wrist, gripper
                  0x02 HEARTBEAT     (empty)
                  0x03 ESTOP         freeze at the current pose until CLEAR_ESTOP
                  0x04 CLEAR_ESTOP
                  0x05 GET_STATUS
    arm -> host   0x85 STATUS        state (0 ok, 1 link lost / no link yet, 2 estop) + 5 x uint16 current angles

Safety is layered so that no single mistake moves the arm somewhere unsafe:
  1. the host refuses angles outside the limits,
  2. the firmware clamps to its own limits again (it does not trust the host),
  3. the firmware limits how fast any joint moves,
  4. if no valid frame arrives for WATCHDOG_S the firmware holds position,
  5. ESTOP freezes the arm and ignores motion commands until cleared.
A held pose is still powered: ESTOP and the watchdog stop MOTION, they do not cut power. A hard stop
is a physical switch on the servo supply.

STATUS: FirmwareSim below is a Python model of arduino/arm_controller/arm_controller.ino, and
tests/test_arm_bridge.py checks that the two agree on every protocol constant. The sketch itself has
NOT been compiled or run on a board by the author, and SerialTransport has never opened a real port.
Treat both as untested on hardware: bring-up steps are in the README.
"""
import math
import time
from typing import Callable, List, Optional, Sequence, Tuple

SOF = 0xA5
MAX_PAYLOAD = 16
CMD_SET_ANGLES, CMD_HEARTBEAT, CMD_ESTOP, CMD_CLEAR_ESTOP, CMD_GET_STATUS = 0x01, 0x02, 0x03, 0x04, 0x05
RSP_STATUS = 0x85
STATE_OK, STATE_LINK_LOST, STATE_ESTOP = 0, 1, 2
NUM_JOINTS = 5
CRC_POLY = 0x07
WATCHDOG_S = 0.5
MAX_SLEW_DPS = 90.0
LIMITS_DEG: Tuple[Tuple[float, float], ...] = ((0, 180), (0, 180), (0, 180), (0, 180), (10, 100))   # yaw, shoulder, elbow, wrist, gripper
REST_DEG: Tuple[float, ...] = (90, 90, 90, 90, 40)       # set to the pose the arm really rests in: servos jump to it at power-up


def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ CRC_POLY) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def encode_frame(cmd: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload too long")
    body = bytes([len(payload), cmd]) + payload
    return bytes([SOF]) + body + bytes([crc8(body)])


def encode_angles(angles_deg: Sequence[float]) -> bytes:
    if len(angles_deg) != NUM_JOINTS:
        raise ValueError(f"expected {NUM_JOINTS} servo angles")
    out = bytearray()
    for v in angles_deg:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("angles must be finite numbers")
        tenths = round(v * 10)
        if not 0 <= tenths <= 65535:
            raise ValueError("angle out of encodable range")
        out += tenths.to_bytes(2, "little")
    return bytes(out)


def decode_angles(payload: bytes) -> Tuple[float, ...]:
    return tuple(int.from_bytes(payload[i * 2:i * 2 + 2], "little") / 10.0 for i in range(len(payload) // 2))


class FrameParser:
    """Byte-stream parser. Garbage, truncated frames and bad checksums are skipped and counted; it
    resynchronises on the next start byte instead of getting stuck."""

    def __init__(self):
        self.buf = bytearray()
        self.bad_crc = 0
        self.dropped_bytes = 0

    def feed(self, data: bytes) -> List[Tuple[int, bytes]]:
        self.buf += data
        frames: List[Tuple[int, bytes]] = []
        while True:
            i = self.buf.find(SOF)
            if i < 0:
                self.dropped_bytes += len(self.buf)
                self.buf.clear()
                break
            if i > 0:
                self.dropped_bytes += i
                del self.buf[:i]
            if len(self.buf) < 2:
                break
            ln = self.buf[1]
            if ln > MAX_PAYLOAD:
                self.dropped_bytes += 1
                del self.buf[:1]
                continue
            if len(self.buf) < ln + 4:
                break
            if crc8(bytes(self.buf[1:ln + 3])) == self.buf[ln + 3]:
                frames.append((self.buf[2], bytes(self.buf[3:ln + 3])))
                del self.buf[:ln + 4]
            else:
                self.bad_crc += 1
                del self.buf[:1]
        return frames


def clamp_to_limits(angles: Sequence[float], limits=LIMITS_DEG) -> Tuple[Tuple[float, ...], int]:
    out, clamped = [], 0
    for v, (lo, hi) in zip(angles, limits):
        c = min(max(v, lo), hi)
        clamped += c != v
        out.append(c)
    return tuple(out), clamped


class FirmwareSim:
    """Python model of the Arduino firmware's behaviour (same rules, same constants)."""

    def __init__(self, now: float = 0.0, limits=LIMITS_DEG, rest=REST_DEG, slew_dps: float = MAX_SLEW_DPS, watchdog_s: float = WATCHDOG_S):
        self.limits, self.slew, self.watchdog = limits, slew_dps, watchdog_s
        self.parser = FrameParser()
        self.current = list(rest)
        self.target = list(rest)
        self.state = STATE_LINK_LOST              # no link yet: hold the rest pose
        self.last_valid = now
        self.last_tick = now
        self.out = bytearray()
        self.clamped_commands = 0
        self.rejected_commands = 0

    def feed(self, data: bytes, now: float) -> None:
        self.tick(now)
        for cmd, payload in self.parser.feed(data):
            self.last_valid = now
            if self.state == STATE_LINK_LOST:
                self.state = STATE_OK
            if cmd == CMD_SET_ANGLES:
                if len(payload) != NUM_JOINTS * 2:
                    self.rejected_commands += 1
                elif self.state == STATE_ESTOP:
                    self.rejected_commands += 1
                else:
                    self.target, clamped = clamp_to_limits(decode_angles(payload), self.limits)
                    self.target = list(self.target)
                    self.clamped_commands += bool(clamped)
            elif cmd == CMD_ESTOP:
                self.state = STATE_ESTOP
                self.target = list(self.current)
            elif cmd == CMD_CLEAR_ESTOP:
                if self.state == STATE_ESTOP:
                    self.state = STATE_OK
                    self.target = list(self.current)
            elif cmd == CMD_GET_STATUS:
                self.out += encode_frame(RSP_STATUS, bytes([self.state]) + encode_angles(self.current))
            elif cmd != CMD_HEARTBEAT:
                self.rejected_commands += 1

    def tick(self, now: float) -> None:
        dt = max(0.0, now - self.last_tick)
        self.last_tick = now
        if self.state == STATE_OK and now - self.last_valid > self.watchdog:
            self.state = STATE_LINK_LOST
            self.target = list(self.current)
        step = self.slew * dt
        for i in range(NUM_JOINTS):
            delta = self.target[i] - self.current[i]
            self.current[i] += max(-step, min(step, delta))

    def read(self) -> bytes:
        data, self.out = bytes(self.out), bytearray()
        return data


# ------------------------------------------------------------------------------ transports
class SimTransport:
    """In-process link to a FirmwareSim on a virtual clock (no sleeping, fully deterministic)."""

    def __init__(self, firmware: Optional[FirmwareSim] = None):
        self.now = 0.0
        self.firmware = firmware or FirmwareSim(now=0.0)
        self.drop_next_writes = 0
        self.corrupt_next_writes = 0

    def write(self, data: bytes) -> None:
        if self.drop_next_writes:
            self.drop_next_writes -= 1
            return
        if self.corrupt_next_writes:
            self.corrupt_next_writes -= 1
            data = data[:-1] + bytes([data[-1] ^ 0xFF])
        self.firmware.feed(data, self.now)

    def read(self) -> bytes:
        return self.firmware.read()

    def advance(self, seconds: float, step: float = 0.01) -> None:
        end = self.now + seconds
        while self.now < end - 1e-12:
            self.now = min(end, self.now + step)
            self.firmware.tick(self.now)

    def close(self) -> None:
        pass


class SerialTransport:
    """Real serial port via pyserial. NEVER RUN AGAINST HARDWARE BY THE AUTHOR: bring it up with the
    servo supply off, then follow the README checklist."""

    def __init__(self, port: str, baud: int = 115200):
        import serial  # imported lazily: only needed with real hardware
        self._ser = serial.Serial(port, baud, timeout=0)

    def write(self, data: bytes) -> None:
        self._ser.write(data)

    def read(self) -> bytes:
        return self._ser.read(256)

    def close(self) -> None:
        self._ser.close()


# ------------------------------------------------------------------------------ host
class ArmBridge:
    def __init__(self, transport, limits=LIMITS_DEG):
        self.transport = transport
        self.limits = limits
        self.parser = FrameParser()
        self.last_status: Optional[dict] = None

    def send_angles(self, servo_angles: Sequence[float]) -> None:
        """Refuses (ValueError) angles outside the limits instead of silently clamping them."""
        payload = encode_angles(servo_angles)                       # validates length / finiteness
        for name, v, (lo, hi) in zip(("yaw", "shoulder", "elbow", "wrist", "gripper"), servo_angles, self.limits):
            if not lo <= v <= hi:
                raise ValueError(f"{name} {v} deg is outside the allowed {lo}..{hi}")
        self.transport.write(encode_frame(CMD_SET_ANGLES, payload))

    def heartbeat(self) -> None:
        self.transport.write(encode_frame(CMD_HEARTBEAT))

    def estop(self) -> None:
        self.transport.write(encode_frame(CMD_ESTOP))

    def clear_estop(self) -> None:
        self.transport.write(encode_frame(CMD_CLEAR_ESTOP))

    def poll(self) -> Optional[dict]:
        for cmd, payload in self.parser.feed(self.transport.read()):
            if cmd == RSP_STATUS and len(payload) == 1 + NUM_JOINTS * 2:
                self.last_status = {"state": payload[0], "angles_deg": decode_angles(payload[1:])}
        return self.last_status

    def request_status(self) -> Optional[dict]:
        self.transport.write(encode_frame(CMD_GET_STATUS))
        return self.poll()
