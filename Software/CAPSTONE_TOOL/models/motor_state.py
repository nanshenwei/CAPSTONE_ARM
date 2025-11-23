from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class MotorState:
    node_id: int
    temp_mos: Optional[float] = None
    temp_motor: Optional[float] = None
    voltage_in: Optional[float] = None
    current_motor: Optional[float] = None
    current_in: Optional[float] = None
    rpm: Optional[float] = None              # 关节输出RPM（已按极对数与减速比换算）
    deg_per_s: Optional[float] = None        # 关节输出角速度（度/秒）
    duty: Optional[float] = None
    # 直接使用固件返回的机械单圈角度（度）
    pos_deg: Optional[float] = None
    # 旧：单圈位置（0..1），保留以兼容
    pos_mod_turns: Optional[float] = None
    pos_unwrapped_turns: float = 0.0
    last_update_s: float = field(default_factory=time.time)
    offline: bool = False
    _last_pos_mod: Optional[float] = None
    _last_time_s: float = field(default_factory=time.time)
    _last_pos_deg: Optional[float] = None

    def update_pos_unwrapped_from_mod(self, pos_mod_turns: float):
        now = time.time()
        if self._last_pos_mod is None:
            self.pos_unwrapped_turns = pos_mod_turns
        else:
            diff = pos_mod_turns - self._last_pos_mod
            while diff <= -0.5:
                diff += 1.0
            while diff > 0.5:
                diff -= 1.0
            self.pos_unwrapped_turns += diff
        self._last_pos_mod = pos_mod_turns
        self.last_update_s = now
        self._last_time_s = now

    def update_pos_unwrapped_from_rpm(self, rpm: float):
        now = time.time()
        dt = now - self._last_time_s
        self._last_time_s = now
        self.pos_unwrapped_turns += (rpm / 60.0) * dt
        self.last_update_s = now

    def update_pos_unwrapped_from_deg(self, pos_deg: float):
        """基于度数(通常0..360包络)更新展开圈数，避免再做mod/归一化。"""
        now = time.time()
        if self._last_pos_deg is None:
            self.pos_unwrapped_turns = (pos_deg / 360.0)
        else:
            diff_deg = pos_deg - self._last_pos_deg
            while diff_deg <= -180.0:
                diff_deg += 360.0
            while diff_deg > 180.0:
                diff_deg -= 360.0
            self.pos_unwrapped_turns += (diff_deg / 360.0)
        self._last_pos_deg = pos_deg
        self.last_update_s = now
        self._last_time_s = now
