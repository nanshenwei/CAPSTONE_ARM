from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import logging
import time

from config.arm_config import AxisConfig
from models.motor_state import MotorState
from utils.math_utils import be_i16, be_i32
from config.arm_config import CANConfig as AppCANConfig


@dataclass
class VescCANConfig:
    id_format: str = "extended_29bit"


class VescCAN:
    # 基本命令（参见 comm_can.md）
    CAN_PACKET_SET_DUTY = 0
    CAN_PACKET_SET_CURRENT = 1
    CAN_PACKET_SET_CURRENT_BRAKE = 2
    CAN_PACKET_SET_RPM = 3
    CAN_PACKET_SET_POS = 4  # 单帧，参数单位为“度”，缩放 1e6，范围 0..360；扩展为 [pos, max_vel, max_accel]
    CAN_PACKET_UPDATE_PID_POS_OFFSET = 55  # 单帧，参数单位为“度”，缩放 1e6，范围 0..360
    CAN_PACKET_SET_POS_LIM = 63
    # 状态帧
    CAN_PACKET_STATUS = 9       # ERPM, Current (motor), Duty
    CAN_PACKET_STATUS_2 = 14    # Ah / Ah Charged
    CAN_PACKET_STATUS_3 = 15    # Wh / Wh Charged
    CAN_PACKET_STATUS_4 = 16    # Temp FET, Temp Motor, Current In, PID Pos (deg)
    CAN_PACKET_STATUS_5 = 27    # Tachometer, Voltage In
    CAN_PACKET_STATUS_6 = 28    # ADC1/2/3, PPM

    def __init__(self, config: VescCANConfig):
        self.cfg = config
        self.states: Dict[int, MotorState] = {}
        self.aixs_cfg: Dict[int, AxisConfig] = {}
        self.log = logging.getLogger("VescCAN")
        self._offline_timeout_s = getattr(AppCANConfig, 'offline_timeout_s', 0.5)

    def set_axis_configs(self, axes_cfg: Dict[int, AxisConfig]):
        """由上层（ArmController/AppBridge）注入每轴配置，用于状态换算。"""
        try:
            self.aixs_cfg = dict(axes_cfg or {})
            self.log.info(f"Axis configs loaded: {list(self.aixs_cfg.keys())}")
        except Exception:
            self.log.warning("Failed to load axis configs")

    # ---------------- ID 打包/解包 ----------------

    def pack_id(self, packet_id: int, node_id: int) -> Tuple[int, bool]:
        if self.cfg.id_format == "extended_29bit":
            arb_id = (packet_id << 8) | (node_id & 0xFF)
            return arb_id, True
        elif self.cfg.id_format == "standard_11bit":
            arb_id = ((packet_id & 0x1F) << 5) | (node_id & 0x1F)
            return arb_id, False
        else:
            raise ValueError("Unknown id_format")

    def unpack_id(self, arbitration_id: int, is_extended: bool) -> Optional[Tuple[int, int]]:
        if self.cfg.id_format == "extended_29bit" and is_extended:
            packet_id = (arbitration_id >> 8) & 0xFF
            node_id = arbitration_id & 0xFF
            return packet_id, node_id
        elif self.cfg.id_format == "standard_11bit" and not is_extended:
            packet_id = (arbitration_id >> 5) & 0x1F
            node_id = arbitration_id & 0x1F
            return packet_id, node_id
        return None

    # ---------------- 发送控制 ----------------

    def _encode_float16(self, value: float, scale: float) -> bytes:
        v = int(round(value * scale))
        # int16 范围保护
        v = max(-32768, min(32767, v))
        return v.to_bytes(2, byteorder="big", signed=True)

    def encode_set_pos(self, degrees: float) -> bytes:
        """
        VESC 单帧位置命令：参数为“度”，范围 0..360，缩放 1e6，BE int32。
        这里对度数进行 wrap 并 clamp 到 [0, 360)。
        """
        # 规范化到 [0, 360)
        d = degrees % 360.0
        if d < 0:
            d += 360.0
        # VESC 文档写 0..360，此处避免编码 360（等价 0）
        if d >= 360.0:
            d = 0.0
        v = int(round(d * 1_000_000.0))
        return v.to_bytes(4, byteorder="big", signed=True)
    
    def encode_set_pos_offset(self, degrees: float) -> bytes:
        """
        VESC 单帧位置命令：参数为“度”，范围 0..360，缩放 1e6，BE int32。
        这里对度数进行 wrap 并 clamp 到 [0, 360)。
        """
        # 规范化到 [0, 360)
        d = degrees % 360.0
        if d < 0:
            d += 360.0
        # VESC 文档写 0..360，此处避免编码 360（等价 0）
        if d >= 360.0:
            d = 0.0
        v = int(round(d * 1e4))
        return v.to_bytes(4, byteorder="big", signed=True)
    
    def encode_set_pos_with_limits(self, degrees: float, max_vel_dps: float, max_accel_dps2: float) -> bytes:
        """
        新固件格式：
        [ pos (float32, deg * 1e6) | max_vel (int16, deg/s * 100) | max_accel (int16, deg/s^2 * 10) ]
        共 8 字节。
        """
        # 位置编码（与旧一致）
        pos_bytes = self.encode_set_pos(degrees)
        # 最大速度 / 加速度编码
        vel_bytes = self._encode_float16(max_vel_dps, 100.0)
        acc_bytes = self._encode_float16(max_accel_dps2, 10.0)
        return pos_bytes + vel_bytes + acc_bytes

    def encode_update_pid_pos_offset(self, degrees: float) -> bytes:
        """
        更新PID位置偏置所用的角度编码，缩放（度 × 1e4）。
        传入“当前机械角度（度）”，由固件将angle_now作为当前角度。
        """
        return self.encode_set_pos_offset(degrees) + bytes(0x00) # angle_now + store(bool)

    def encode_set_erpm(self, erpm: float) -> bytes:
        v = int(round(erpm))
        return v.to_bytes(4, byteorder="big", signed=True)

    def encode_set_current(self, current_a: float) -> bytes:
        # 文档：电流（A）缩放 1000（某些固件为 10/100，视固件而定）。
        v = int(round(current_a * 1000.0))
        return v.to_bytes(4, byteorder="big", signed=True)

    def build_frame(self, packet_id: int, node_id: int, data: bytes) -> Tuple[int, bytes, bool]:
        arb_id, extended = self.pack_id(packet_id, node_id)
        return arb_id, data, extended

    # ---------------- 状态管理 ----------------
    def reset_state(self, node_id: int):
        st = self.states.get(node_id)
        if not st:
            return
        if st.offline:
            return  # 已经离线，无需重复重置
        st.temp_mos = None
        st.temp_motor = None
        st.voltage_in = None
        st.current_motor = None
        st.current_in = None
        st.rpm = None
        st.deg_per_s = None
        st.duty = None
        st.pos_deg = None
        st.pos_mod_turns = None
        st.offline = True
        self.log.warning(f"Node {node_id} offline: reset state")

    def _mark_update(self, node_id: int):
        st = self._get_state(node_id)
        st.last_update_s = time.time()
        if st.offline:
            st.offline = False
            self.log.info(f"Node {node_id} online")
        return st

    def check_offline_and_cleanup(self):
        now = time.time()
        for nid, st in list(self.states.items()):
            if st and (now - st.last_update_s) > self._offline_timeout_s:
                self.reset_state(nid)

    # ---------------- 状态解析（按 comm_can.md） ----------------

    def _get_state(self, node_id: int) -> MotorState:
        st = self.states.get(node_id)
        if st is None:
            st = MotorState(node_id=node_id)
            self.states[node_id] = st
        return st
    
    def _get_cfg(self, node_id: int) -> Optional[AxisConfig]:
        """返回该轴已注入的配置；若不存在则返回 None，不做默认构造。"""
        return self.aixs_cfg.get(node_id)

    def parse_status(self, packet_id: int, node_id: int, data: bytes):
        # 在解析前后更新 last_update 并检查离线
        st = self._get_state(node_id)
        try:
            if packet_id == self.CAN_PACKET_STATUS and len(data) >= 8:
                # ERPM (int32), Current_motor (A*1000 int16), Duty (%/1000)
                erpm = int.from_bytes(data[0:4], byteorder="big", signed=True)
                current_x1000 = be_i16(data[4:6])
                duty_x1000 = be_i16(data[6:8])

                st.current_motor = current_x1000 / 1000.0
                st.duty = duty_x1000 / 1000.0

                # 依据已注入的轴配置换算到关节输出RPM与角速度（度/秒）
                acf = self._get_cfg(node_id)
                if acf is not None:
                    pole_pairs = max(1.0, float(getattr(acf, 'motor_poles_pairs', 3.0)))
                    ratio = max(1e-9, float(getattr(acf, 'reduction_ratio', 1.0)))
                    mech_rpm_motor = float(erpm) / pole_pairs          # 电机机械RPM
                    joint_rpm = mech_rpm_motor / ratio                  # 关节输出RPM
                    st.rpm = joint_rpm
                    st.deg_per_s = joint_rpm * 6.0                      # RPM*360/60
                else:
                    # 无配置则跳过换算，保留为 None
                    self.log.debug(f"No AxisConfig for node {node_id}, skip rpm conversion")

                self._mark_update(node_id)

            elif packet_id == self.CAN_PACKET_STATUS_4 and len(data) >= 8:
                # Temp FET (0.1C i16), Temp Motor (0.1C i16), Current In (A*1000 i16), PID Pos (deg, scale 50, i16)
                temp_fet_x10 = be_i16(data[0:2])
                temp_m_x10 = be_i16(data[2:4])
                i_in_x1000 = be_i16(data[4:6])
                pid_pos_deg_x50 = be_i16(data[6:8])
                st.temp_mos = temp_fet_x10 / 10.0
                st.temp_motor = temp_m_x10 / 10.0
                st.current_in = i_in_x1000 / 1000.0
                # 位置（度）直接保存为机械单圈角度
                pid_pos_deg = pid_pos_deg_x50 / 50.0
                st.pos_deg = pid_pos_deg
                self._mark_update(node_id)

            elif packet_id == self.CAN_PACKET_STATUS_5 and len(data) >= 6:
                # Tachometer (erev, scale 6, int32) + Voltage In (0.1V u16)
                # 这里只解析电压
                v_in_x10 = ((data[4] << 8) | data[5])
                st.voltage_in = v_in_x10 / 10.0
                self._mark_update(node_id)

            elif packet_id == self.CAN_PACKET_STATUS_6:
                # ADC1/2/3, PPM （此处不解析）
                self._mark_update(node_id)
        except Exception as e:
            self.log.debug(f"parse error node {node_id} pid {packet_id}: {e}")
        finally:
            # 解析完成后检查离线
            self.check_offline_and_cleanup()

    def get_state(self, node_id: int) -> Optional[MotorState]:
        # 调用时也进行一次离线检查
        self.check_offline_and_cleanup()
        return self.states.get(node_id)

    def with_state(self, node_id: int) -> Optional[MotorState]:
        """获取状态并在离线时返回 None（便于上层直接判空终止动作）。"""
        st = self.get_state(node_id)
        if st is None or st.offline:
            return None
        return st
