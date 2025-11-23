import threading
import time
from typing import Dict, Callable, Optional
from utils.log_utils import globalLogger
from utils.log_utils import LoggerTool

from models.motor_state import MotorState
from utils.math_utils import clamp
from hardware.vesc_can import VescCAN
from config.arm_config import AxisConfig
from config.settings import HOMING_CONFIG


class AxisController:
    def __init__(self, axis_cfg: AxisConfig, vesc: VescCAN):
        self.cfg = axis_cfg
        self.vesc = vesc
        self.target_deg_ui = 0.0
        self.enabled = False
        # 找零相关：记录“机械零点”对应的VESC绝对角度（0..360）
        self.zero_abs_deg: float = 0.0
        self.homed: bool = False

    def _apply_zero_offset(self, target_deg: float) -> float:
        # 绝对角 = 零点绝对角 + 目标机械角（取模360）
        d = (self.zero_abs_deg + target_deg) % 360.0
        return d

    def set_zero_here(self, current_pos_deg: float):
        # 记录当前VESC绝对角为“机械零点”的绝对角
        self.zero_abs_deg = float(current_pos_deg) % 360.0
        self.homed = True

    def send_joint_deg(self, target_deg: float,
                       send_frame: Callable[[int, bytes, bool], None]):
        """
        发送位置控制：位置(度) + 最大速度(°/s) + 最大加速度(°/s^2)。
        固件侧将基于此做梯形速度规划。
        """
        # 选择该轴限速，若未设置则使用全局默认
        max_vel = self.cfg.max_vel_dps if self.cfg.max_vel_dps is not None else 90.0
        max_acc = self.cfg.max_accel_dps2 if self.cfg.max_accel_dps2 is not None else 180.0
        data = self.vesc.encode_set_pos_with_limits(target_deg, max_vel, max_acc)
        arb_id, payload, ext = self.vesc.build_frame(self.vesc.CAN_PACKET_SET_POS_LIM, self.cfg.node_id, data)
        send_frame(arb_id, payload, ext)

    def update(self, send_frame: Callable[[int, bytes, bool], None]):
        if not self.enabled:
            return
        # 目标角限制到软限位（默认 0..360）
        tgt_deg = clamp(self.target_deg_ui, self.cfg.soft_min_deg, self.cfg.soft_max_deg)
        self.send_joint_deg(tgt_deg, lambda arb, data, ext: send_frame(arb, data, ext))


class ArmController:
    def __init__(self, axes_cfg: Dict[int, AxisConfig], vesc: VescCAN, can_send: Callable[[int, bytes, bool], None], control_rate_hz: float = 50.0, logger: LoggerTool = None):
        self.axes_cfg = axes_cfg
        self.vesc = vesc
        self.can_send = can_send
        self.axes: Dict[int, AxisController] = {nid: AxisController(cfg, vesc) for nid, cfg in axes_cfg.items()}
        self.log = logger
        self.terminal_log = globalLogger
        self._stop = threading.Event()
        self._thread = None
        self.control_rate_hz = control_rate_hz
        # 找零互斥
        self._homing_lock = threading.Lock()
        # 心跳时间戳
        self._last_idle_keepalive_ts: float = 0.0
        # 终止找零事件
        self._homing_cancel = threading.Event()

    # ---------------- 运行与轴控制接口（恢复） ----------------
    def set_axis_target(self, node_id: int, deg: float):
        axis = self.axes.get(node_id)
        if axis is not None:
            axis.target_deg_ui = float(deg)

    def set_axis_enabled(self, node_id: int, enabled: bool):
        axis = self.axes.get(node_id)
        if axis is not None:
            axis.enabled = bool(enabled)

    def set_axis_direction_lock(self, node_id: int, direction: str):
        # 方向锁由固件侧处理，这里保留占位以兼容 GUI
        return

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log.log_info("控制发送循环开始..")
        self.terminal_log.info("ArmController loop started")

    def stop(self):
        self._stop.set()
        if self._thread:
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
        self._thread = None
        self.log.log_info("控制发送循环停止")
        self.terminal_log.info("ArmController loop stopped")

    def _loop(self):
        period = 1.0 / max(1e-3, self.control_rate_hz)
        while not self._stop.is_set():
            t0 = time.time()
            # 周期下发已启用轴的位置命令
            for axis in self.axes.values():
                try:
                    axis.update(self.can_send)
                except Exception as e:
                    self.log.log_error(f"轴控制更新错误: {e}")
                    self.terminal_log.error(f"Axis update error: {e}")
            # 控制循环节拍
            dt = time.time() - t0
            sleep_t = max(0.0, period - dt)
            time.sleep(sleep_t)

    # ---------------- 实用方法 ----------------
    def _resolve_axis_cfg(self, node_id: int, cfg: Optional[dict]) -> dict:
        """优先使用 AxisConfig 的每轴独立字段；字段为 None 时回退到全局默认 HOMING_CONFIG 或调用者传入 cfg。"""
        axis = self.axes.get(node_id)
        base = dict(HOMING_CONFIG)
        if cfg:
            base.update(cfg)
        if not axis:
            return base
        ac = axis.cfg
        def set_if(name, value):
            if value is not None:
                base[name] = value
        set_if("mode", ac.homing_mode)
        set_if("move_direction", ac.homing_move_direction)
        set_if("rpm", ac.homing_rpm)
        set_if("current_a", ac.homing_current_a)
        set_if("current_threshold_a", ac.homing_current_threshold_a)
        set_if("collision_dwell_s", ac.homing_collision_dwell_s)
        set_if("timeout_s", ac.homing_timeout_s)
        set_if("backoff_deg", ac.homing_backoff_deg)
        set_if("backoff_rpm", ac.homing_backoff_rpm)
        set_if("sample_period_s", ac.homing_sample_period_s)
        set_if("command_period_s", ac.homing_command_period_s)
        set_if("send_idle_keepalive", ac.homing_send_idle_keepalive)
        return base

    def _keepalive_idle_axes(self, exclude_id: int, cmd_period: float, force: bool = False):
        """为未启用的其它轴发送 rpm=0 作为心跳，避免VESC超时。不会干扰已启用轴的正常位置控制。"""
        now = time.time()
        if not force and (now - self._last_idle_keepalive_ts) < cmd_period:
            return
        for nid, axis in self.axes.items():
            if nid == exclude_id:
                continue
            if not axis.enabled:
                try:
                    self._send_rpm(nid, 0.0)
                except Exception:
                    pass
        self._last_idle_keepalive_ts = now

    # ---------------- 低层发送 ----------------
    def _send_current(self, node_id: int, current_a: float):
        data = self.vesc.encode_set_current(current_a)
        arb_id, payload, ext = self.vesc.build_frame(self.vesc.CAN_PACKET_SET_CURRENT, node_id, data)
        self.can_send(arb_id, payload, ext)

    def _send_rpm(self, node_id: int, rpm: float):
        """
        发送速度模式：rpm 为关节最终机械转速（RPM）。
        与 VESC 通信时自动换算为 ERPM：ERPM = joint_rpm * reduction_ratio * pole_pairs。
        """
        cfg = self.axes[node_id].cfg
        erpm = rpm * cfg.reduction_ratio * cfg.motor_poles_pairs
        data = self.vesc.encode_set_erpm(erpm)
        arb_id, payload, ext = self.vesc.build_frame(self.vesc.CAN_PACKET_SET_RPM, node_id, data)
        self.can_send(arb_id, payload, ext)

    def _stop_axis_motion(self, node_id: int):
        # 通过设置0转速（或0电流）停止
        try:
            # self._send_rpm(node_id, 0.0)
            self._send_current(node_id, 0.0)
        except Exception:
            pass

    # ---------------- 找零（Homing） ----------------
    def home_axis(self, node_id: int, cfg: Optional[dict] = None):
        """
        基于电流/转速的机械限位碰撞检测找零。
        找零期间持续发送控制心跳；支持每轴独立配置（方向/模式等）。
        启动找零时禁用所有轴，结束后恢复原使能状态；支持外部取消。
        """
        cfg = self._resolve_axis_cfg(node_id, cfg or HOMING_CONFIG)
        mode = cfg.get("mode", "rpm")  # "rpm" / "current"
        move_dir = float(cfg.get("move_direction", -1))  # -1或+1
        rpm_val = float(cfg.get("rpm", 300.0))
        cur_cmd = float(cfg.get("current_a", 2.0))
        cur_th = float(cfg.get("current_threshold_a", 6.0))
        dwell_s = float(cfg.get("collision_dwell_s", 0.08))
        timeout_s = float(cfg.get("timeout_s", 8.0))
        backoff_deg = float(cfg.get("backoff_deg", 5.0))
        backoff_rpm = float(cfg.get("backoff_rpm", 200.0))
        sample_dt = float(cfg.get("sample_period_s", 0.01))
        cmd_period = float(cfg.get("command_period_s", 0.05))  # 心跳周期
        send_idle_keepalive = bool(cfg.get("send_idle_keepalive", True))

        if node_id not in self.axes:
            self.log.log_error("错误：未知轴ID")
            self.terminal_log.error(f"Unknown axis {node_id}")
            return
        axis = self.axes[node_id]

        with self._homing_lock:
            # 清除取消标志
            self._homing_cancel.clear()
            # 记录并禁用所有轴
            prev_enabled_map = {nid: ax.enabled for nid, ax in self.axes.items()}
            for nid, ax in self.axes.items():
                ax.enabled = False
                self._stop_axis_motion(nid)
            time.sleep(0.02)

            try:
                # 若收到取消，直接退出
                if self._homing_cancel.is_set():
                    self.log.log_info("找零取消于启动前")
                    self.terminal_log.info("Homing canceled before start")
                    return

                # 起动 + 初次发送
                if mode == "rpm":
                    self._send_rpm(node_id, move_dir * rpm_val)
                elif mode == "current":
                    self._send_current(node_id, move_dir * cur_cmd)
                else:
                    self.log.log_error("找零模式必须为 'rpm' 或 'current'")
                    self.terminal_log.error("Homing mode must be 'rpm' or 'current'")
                    return
                last_cmd_ts = 0.0

                # 监测碰撞（期间保持心跳）
                t0 = time.time()
                over_ts: Optional[float] = None
                collided = False
                while True:
                    # 取消检查
                    if self._homing_cancel.is_set():
                        self.log.log_warning(f"轴 {node_id} 找零取消，停止中")
                        self.terminal_log.warning(f"Axis {node_id} homing canceled, stopping")
                        return
                    # 主轴心跳
                    now = time.time()
                    if now - last_cmd_ts >= cmd_period:
                        if mode == "rpm":
                            self._send_rpm(node_id, move_dir * rpm_val)
                        else:
                            self._send_current(node_id, move_dir * cur_cmd)
                        last_cmd_ts = now
                    # 空闲轴心跳（rpm=0，仅对未启用轴）
                    if send_idle_keepalive:
                        self._keepalive_idle_axes(exclude_id=node_id, cmd_period=cmd_period)

                    if now - t0 > timeout_s:
                        # 超时：不抛异常，安全停止并返回
                        self.log.log_error(f"轴 {node_id} 找零超时，停止轴并退出找零")
                        self.terminal_log.error(f"Axis {node_id} homing timeout, stop axis and exit homing")
                        return

                    st = self._wait_state(
                        node_id,
                        timeout_s=0.1,
                        require_fields=["current_motor"],
                        keepalive=(
                            (lambda: self._send_rpm(node_id, move_dir * rpm_val))
                            if mode == "rpm"
                            else (lambda: self._send_current(node_id, move_dir * cur_cmd))
                        ),
                        keepalive_period_s=cmd_period,
                    )
                    # 离线直接退出
                    # if self.vesc.with_state(node_id) is None:
                    #     self.log and self.log.log_warning(f"轴 {node_id} 离线，终止找零")
                    #     self._stop_axis_motion(node_id)
                    #     return
                    if not st or st.current_motor is None:
                        time.sleep(min(sample_dt, cmd_period))
                        continue

                    if abs(st.current_motor) >= cur_th:
                        if over_ts is None:
                            over_ts = time.time()
                        elif time.time() - over_ts >= dwell_s:
                            # 确认碰撞
                            collided = True
                            break
                    else:
                        over_ts = None
                    time.sleep(min(sample_dt, cmd_period))

                # 若未检测到碰撞（例如手动停或未达阈值），或取消，直接退出并停轴
                if not collided or self._homing_cancel.is_set():
                    self._stop_axis_motion(node_id)
                    return

                # 停止并记录零点（仅在已碰撞时执行）
                # self._stop_axis_motion(node_id)
                self._send_rpm(node_id, 0.0)
                # 读取当前角度，通知VESC将其应用为零点（由固件更新PID位置偏置）
                st = self.vesc.get_state(node_id)
                if st and st.pos_deg is not None:
                    pos_deg_now = st.pos_deg
                else:
                    pos_deg_now = 0.0
                try:
                    data = self.vesc.encode_update_pid_pos_offset(0.0)
                    time.sleep(0.01)
                    arb, payload, ext = self.vesc.build_frame(self.vesc.CAN_PACKET_UPDATE_PID_POS_OFFSET, node_id, data)
                    self.can_send(arb, payload, ext)
                    self.log and self.log.log_info(f"轴 {node_id} 已将当前角度 {pos_deg_now:.2f}° 应用为零点(固件侧)")
                    self.terminal_log.info(f"Axis {node_id} apply current angle as zero via PID offset")
                except Exception as e:
                    self.log and self.log.log_error(f"轴 {node_id} 应用零点失败: {e}")
                    self.terminal_log.error(f"Apply zero via PID offset failed: {e}")
                self._stop_axis_motion(node_id)
                # 应用层不再维护零点偏移，置标记即可
                axis.homed = True

                # 取消检查
                if self._homing_cancel.is_set():
                    return

                # 回退阶段：持续发送位置命令（心跳）
                target_deg = -move_dir * backoff_deg
                # 估算到位时间：deg/s = RPM * 6
                deg_per_s_est = max(1e-6, self.axes[node_id].cfg.max_vel_dps if self.axes[node_id].cfg.max_vel_dps is not None else 90.0)
                end_ts = time.time() + max(0.2, (backoff_deg / deg_per_s_est)) + 1.0
                last_pos_ts = 0.0
                self.log.log_info(f"轴 {node_id} 开始回退")
                while time.time() < end_ts:
                    if self._homing_cancel.is_set():
                        self.log.log_warning(f"轴 {node_id} 找零取消于回退阶段")
                        self.terminal_log.warning(f"Axis {node_id} homing canceled during backoff")
                        return
                    now2 = time.time()
                    if now2 - last_pos_ts >= cmd_period:
                        axis.send_joint_deg(target_deg, self.can_send)
                        last_pos_ts = now2
                    if send_idle_keepalive:
                        self._keepalive_idle_axes(exclude_id=node_id, cmd_period=cmd_period)
                    time.sleep(0.005)

            finally:
                # 停止一切力矩/速度输出
                for nid in self.axes.keys():
                    self._stop_axis_motion(nid)
                # 恢复之前各轴的使能状态
                for nid, was_enabled in prev_enabled_map.items():
                    ax = self.axes.get(nid)
                    if ax is not None:
                        ax.enabled = was_enabled

            self.log.log_success(f"轴 {node_id} 找零成功")
            self.terminal_log.info(f"Axis {node_id} homed. offset={axis.zero_abs_deg:.2f}deg")

    def home_all(self, cfg: Optional[dict] = None):
        if cfg is None:
            cfg = HOMING_CONFIG
        for nid in sorted(self.axes.keys()):
            if self._homing_cancel.is_set():
                self.log.log_warning("找零取消，停止批量找零")
                self.terminal_log.warning("Homing canceled; stop batch")
                break
            try:
                self.home_axis(nid, cfg)
            except Exception as e:
                self.log.log_error(f"轴 {nid} 找零失败: {e}")
                self.terminal_log.error(f"Homing failed on axis {nid}: {e}")
                continue

    def cancel_homing(self):
        """外部终止找零：置位取消标志并立刻发送停止指令。"""
        self._homing_cancel.set()
        for nid in self.axes.keys():
            try:
                self._stop_axis_motion(nid)
            except Exception:
                pass
        self.terminal_log.info("Homing cancel requested")

    # ---------------- 等待状态 ----------------
    def _wait_state(
        self,
        node_id: int,
        timeout_s: float,
        require_fields: Optional[list[str]] = None,
        keepalive: Optional[Callable[[], None]] = None,
        keepalive_period_s: float = 0.05,
    ) -> Optional[MotorState]:
        """
        轮询等待指定轴的状态更新。
        - require_fields: 需要非 None 的字段名列表（如 ["current_motor", "pos_deg"]），满足任一即可返回；
          若为 None 则只要拿到状态对象即可返回。
        - keepalive: 等待期间周期调用的心跳回调，确保控制指令不断流（如 rpm/current 或 pos 指令）。
        - keepalive_period_s: 心跳调用周期。
        """
        t0 = time.time()
        last_k = 0.0
        while time.time() - t0 < timeout_s:
            st = self.vesc.get_state(node_id)
            if st is not None:
                if not require_fields:
                    return st
                for f in require_fields:
                    if getattr(st, f, None) is not None:
                        return st
            
            # 心跳维持
            if keepalive is not None:
                now = time.time()
                if now - last_k >= keepalive_period_s:
                    try:
                        keepalive()
                    except Exception:
                        pass
                    last_k = now
            time.sleep(0.005)
        return self.vesc.get_state(node_id)
