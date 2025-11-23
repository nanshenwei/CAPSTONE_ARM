from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CANConfig:
    interface: str = "pcan"
    channel: str = "PCAN_USBBUS1"
    bitrate: int = 500000
    id_format: str = "extended_29bit"
    offline_timeout_s: float = 0.5   # 新增：状态帧超时判定离线阈值


@dataclass
class AxisConfig:
    node_id: int
    soft_min_deg: float = 0.0
    soft_max_deg: float = 359.999
    # 位置控制默认限速（每轴可覆盖）
    max_vel_dps: float = 90.0          # 度/秒
    max_accel_dps2: float = 180.0      # 度/秒^2

    reduction_ratio: float = 100.0
    motor_poles_pairs: float = 3.0
    
    # —— 每轴独立找零参数（None 表示使用全局默认 HOMING_CONFIG） ——
    homing_mode: Optional[str] = None                 # "rpm" 或 "current"
    homing_move_direction: Optional[float] = None     # +1 或 -1
    homing_rpm: Optional[float] = None
    homing_current_a: Optional[float] = None
    homing_current_threshold_a: Optional[float] = None
    homing_collision_dwell_s: Optional[float] = None
    homing_timeout_s: Optional[float] = None
    homing_backoff_deg: Optional[float] = None
    homing_backoff_rpm: Optional[float] = None
    homing_sample_period_s: Optional[float] = None
    homing_command_period_s: Optional[float] = None
    homing_send_idle_keepalive: Optional[bool] = None


@dataclass
class AppConfig:
    can: CANConfig = field(default_factory=CANConfig)
    control_rate_hz: float = 200.0
    # 全局默认限速（若轴未覆盖则使用）
    default_max_vel_dps: float = 90.0
    default_max_accel_dps2: float = 180.0
