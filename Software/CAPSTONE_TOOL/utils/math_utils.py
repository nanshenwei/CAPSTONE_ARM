import struct
import time


def be_i16(b: bytes) -> int:
    return struct.unpack(">h", b)[0]


def be_u16(b: bytes) -> int:
    return struct.unpack(">H", b)[0]


def be_i32(b: bytes) -> int:
    return struct.unpack(">i", b)[0]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def now_s() -> float:
    return time.time()


def deg_to_turns(deg: float) -> float:
    return deg / 360.0


def turns_to_deg(turns: float) -> float:
    return turns * 360.0


def wrap_deg_0_360(deg: float) -> float:
    d = deg % 360.0
    return d if d >= 0.0 else d + 360.0
