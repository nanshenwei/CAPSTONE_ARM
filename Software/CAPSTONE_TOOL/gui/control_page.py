from ast import Try
import time
from datetime import datetime
import struct
import dearpygui.dearpygui as dpg
from typing import Dict, TYPE_CHECKING
import threading
from utils.log_utils import LoggerTool
from utils.log_utils import globalLogger
from config.settings import STATUS_DISPLAY_CONFIG, HOMING_CONFIG

# 仅在类型检查时导入，避免运行时循环依赖
if TYPE_CHECKING:
    from main import AppBridge

class ControlPage:
    def __init__(self, bridge: 'AppBridge' = None, logger: LoggerTool = None):
        self.logger = logger or LoggerTool("control_panel")
        self.bridge = bridge  # AppBridge，用于后续接线
        # 自动刷新线程
        self._status_thread = None
        self._stop_event = threading.Event()
        self.status_update_interval_s = 0.05
        # 曲线数据缓存
        self.plot_history_size = 1000
        self.plot_data = {}  # {nid: {"time": [], "temp_fet": [], "temp_motor": [], ...}}
        self.plot_start_time = time.time()

        self.create_page()
        self._start_status_loop()

    def create_page(self):
        """创建控制面板页面，包含日志显示与轴控制控件。"""
        with dpg.tab(label="控制面板"):
            # 连接与控制 + 状态监视并排布局
            with dpg.group(horizontal=True):
                # 左侧：连接与控制
                with dpg.group(horizontal=False):
                    with dpg.group(horizontal=True):
                        with dpg.group():
                            # 连接状态显示
                            dpg.add_text(default_value="状态: 未连接", tag="connection_status_txt")
                            if self.bridge is not None and self.bridge.can_if is not None:
                                dpg.add_text(default_value=f"Interface: {self.bridge.can_if.interface}, "
                                                        f"Channel: {self.bridge.can_if.channel}, "
                                                        f"Bitrate: {self.bridge.can_if.bitrate}")
                            with dpg.group(horizontal=True):
                                dpg.add_button(label="连接", callback=self._on_connect)
                                dpg.add_button(label="断开", callback=self._on_disconnect)
                                dpg.add_button(label="使能全部", callback=self._on_enable_all)
                                dpg.add_button(label="失能全部", callback=self._on_disable_all)
                            with dpg.group(horizontal=True):
                                dpg.add_button(label="开始控制循环", callback=self._on_start_control)
                                dpg.add_button(label="停止控制循环", callback=self._on_stop_control)
                                dpg.add_button(label="开始所有轴找零", callback=self._find_zero)
                                dpg.add_button(label="终止找零", callback=self._on_cancel_homing)

                        # 日志区域
                        self.logger.create_context(90, 470)

                    # 轴控制
                    with dpg.child_window(height=420, width=840):
                        if self.bridge and hasattr(self.bridge, "arm") and self.bridge.arm:
                            for nid in sorted(self.bridge.arm.axes.keys()):
                                with dpg.collapsing_header(label=f"Axis Node {nid}", default_open=True):
                                    target_tag = f"axis_{nid}_target_in"
                                    enable_tag = f"axis_{nid}_enable_chk"

                                    # 目标角度（滑动条）
                                    axis_cfg = self.bridge.arm.axes[nid].cfg
                                    with dpg.group(horizontal=True, indent=15):
                                        dpg.add_slider_float(
                                            label="目标角度",
                                            tag=target_tag,
                                            min_value=axis_cfg.soft_min_deg,
                                            max_value=axis_cfg.soft_max_deg,
                                            default_value=0.0,
                                            width=200,
                                            format="%.1f°",
                                            callback=self._on_target_change,
                                            user_data=nid,
                                        )
                                        # 启用
                                        dpg.add_checkbox(
                                            label="启用", default_value=False,
                                            tag=enable_tag,
                                            callback=self._on_enable_toggle,
                                            user_data=nid
                                        )
                                        # 单轴找零按钮
                                        dpg.add_button(label="找零该轴", callback=self._on_home_axis, user_data=nid)
                                    
                                        # 位置控制参数（限速）
                                        with dpg.group(horizontal=True):
                                            vel_tag = f"axis_{nid}_max_vel"
                                            acc_tag = f"axis_{nid}_max_acc"
                                            dpg.add_text("Lim:")
                                            dpg.add_input_float(label="°/s", tag=vel_tag, width=60, step=0, default_value=float(axis_cfg.max_vel_dps))
                                            dpg.add_input_float(label="°/s^2", tag=acc_tag, width=60, step=0, default_value=float(axis_cfg.max_accel_dps2))
                                            dpg.add_button(label="应用限速", callback=self._on_apply_speed_limits, user_data={"nid": nid, "vel_tag": vel_tag, "acc_tag": acc_tag})

                                    # 找零参数（每轴独立）
                                    with dpg.collapsing_header(label="找零参数", default_open=False, indent=20):
                                        def_val = HOMING_CONFIG
                                        # 生成控件 tag
                                        tag_prefix = f"axis_{nid}_homing_"
                                        inputs = {
                                            "mode": dpg.add_combo(items=["rpm", "current"], default_value=str(axis_cfg.homing_mode or def_val.get("mode","rpm")), label="模式"),
                                            "move_direction": dpg.add_combo(items=["-1", "+1"], default_value=str(int(axis_cfg.homing_move_direction) if axis_cfg.homing_move_direction is not None else int(def_val.get("move_direction", -1))), label="方向"),
                                            "rpm": dpg.add_input_float(default_value=float(axis_cfg.homing_rpm or def_val.get("rpm", 300.0)), label="目标RPM", width=150),
                                            "current_a": dpg.add_input_float(default_value=float(axis_cfg.homing_current_a or def_val.get("current_a", 2.0)), label="目标电流(A)", width=150),
                                            "current_threshold_a": dpg.add_input_float(default_value=float(axis_cfg.homing_current_threshold_a or def_val.get("current_threshold_a", 6.0)), label="碰撞阈值(A)", width=150),
                                            "collision_dwell_s": dpg.add_input_float(default_value=float(axis_cfg.homing_collision_dwell_s or def_val.get("collision_dwell_s", 0.08)), label="去抖时间(s)", width=150),
                                            "timeout_s": dpg.add_input_float(default_value=float(axis_cfg.homing_timeout_s or def_val.get("timeout_s", 8.0)), label="超时(s)", width=150),
                                            "backoff_deg": dpg.add_input_float(default_value=float(axis_cfg.homing_backoff_deg or def_val.get("backoff_deg", 5.0)), label="回退角(deg)", width=150),
                                            "backoff_rpm": dpg.add_input_float(default_value=float(axis_cfg.homing_backoff_rpm or def_val.get("backoff_rpm", 200.0)), label="回退RPM", width=150),
                                            "sample_period_s": dpg.add_input_float(default_value=float(axis_cfg.homing_sample_period_s or def_val.get("sample_period_s", 0.01)), label="采样周期(s)", width=150),
                                            "command_period_s": dpg.add_input_float(default_value=float(axis_cfg.homing_command_period_s or def_val.get("command_period_s", 0.05)), label="心跳周期(s)", width=150),
                                            "send_idle_keepalive": dpg.add_checkbox(label="空闲轴心跳(rpm=0)", default_value=bool(def_val.get("send_idle_keepalive", True)) if axis_cfg.homing_send_idle_keepalive is None else bool(axis_cfg.homing_send_idle_keepalive)),
                                        }

                                        dpg.add_button(label="应用参数", callback=self._on_apply_homing_params, user_data={"nid": nid, "tags": inputs})
                            
                        else:
                            dpg.add_text("后端未就绪，无法显示轴控制。")

                    # 状态监视区域（垂直排布）
                    with dpg.group():
                        dpg.add_text("电机状态监视")
                        self._build_status_display()

                with dpg.group(horizontal=False):
                    # 曲线图区域
                    with dpg.child_window(height=1035, width=800):
                        # 历史点数控制
                        with dpg.group(horizontal=True):
                            dpg.add_text("实时曲线监视  ")
                            dpg.add_text("历史点数:")
                            dpg.add_input_int(tag="plot_history_size", default_value=1000, width=100, min_value=100, max_value=50000, min_clamped=True, max_clamped=True)
                            dpg.add_button(label="应用", callback=self._on_apply_plot_history)
                        
                        # 统一曲线图（所有电机合并显示）
                        if self.bridge and hasattr(self.bridge, "arm") and self.bridge.arm:
                            # 温度曲线（所有电机）
                            with dpg.plot(label="所有电机温度", height=327, width=780, no_title=True):
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="", tag="plot_temp_x", auto_fit=True)
                                dpg.add_plot_axis(dpg.mvYAxis, label="温度(°C)", tag="plot_temp_y", lock_min=True, lock_max=True)
                                dpg.set_axis_limits("plot_temp_y", ymin=10, ymax=80)
                                for nid in sorted(self.bridge.arm.axes.keys()):
                                    dpg.add_line_series([], [], label=f"电机{nid} FET", parent="plot_temp_y", tag=f"plot_{nid}_temp_fet")
                                    dpg.add_line_series([], [], label=f"电机{nid} 电机", parent="plot_temp_y", tag=f"plot_{nid}_temp_motor")
                            
                            # 电流曲线（所有电机）
                            with dpg.plot(label="所有电机电流", height=327, width=780, no_title=True):
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="", tag="plot_current_x", auto_fit=True)
                                dpg.add_plot_axis(dpg.mvYAxis, label="电机电流(A)", tag="plot_current_y1", auto_fit=True)
                                dpg.add_plot_axis(dpg.mvYAxis, label="输入电流(A)", tag="plot_current_y2", auto_fit=True)
                                for nid in sorted(self.bridge.arm.axes.keys()):
                                    dpg.add_line_series([], [], label=f"电机{nid} 电机电流", parent="plot_current_y1", tag=f"plot_{nid}_i_motor")
                                    dpg.add_line_series([], [], label=f"电机{nid} 输入电流", parent="plot_current_y2", tag=f"plot_{nid}_i_in", show=False)
                            
                            # 位置与转速曲线（双Y轴）
                            with dpg.plot(label="位置与转速", height=327, width=780, no_title=True):
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="", tag="plot_motion_x", auto_fit=True)
                                dpg.add_plot_axis(dpg.mvYAxis, label="角度(°)", tag="plot_motion_y1", auto_fit=True)
                                dpg.add_plot_axis(dpg.mvYAxis, label="角速度(°/s)", tag="plot_motion_y2", auto_fit=True)
                                for nid in sorted(self.bridge.arm.axes.keys()):
                                    dpg.add_line_series([], [], label=f"电机{nid} 位置", parent="plot_motion_y1", tag=f"plot_{nid}_pos")
                                    dpg.add_line_series([], [], label=f"电机{nid} 转速", parent="plot_motion_y2", tag=f"plot_{nid}_deg_per_s")


    def _build_status_display(self):
        """构建状态显示区域，每个电机垂直排布"""
        cfg = STATUS_DISPLAY_CONFIG
        
        with dpg.child_window(height=460, width=cfg["component_sizes"]["motor_panel_width"] * 4):
            if self.bridge and hasattr(self.bridge, "arm") and self.bridge.arm:
                with dpg.group(horizontal=True):
                    for nid in sorted(self.bridge.arm.axes.keys()):
                        axis_cfg = self.bridge.arm.axes[nid].cfg
                        
                        # 每个电机一个面板
                        with dpg.group(horizontal=False):
                            dpg.add_text(f"电机 {nid}", color=(255, 255, 255))
                            dpg.add_separator()
                            
                            dpg.add_text(f"状态:离线", tag=f"axis_{nid}_status_txt")
                            # 位置显示 - 滑块
                            dpg.add_text("位置:")
                            dpg.add_slider_float(
                                tag=f"axis_{nid}_pos_slider",
                                min_value=axis_cfg.soft_min_deg,
                                max_value=axis_cfg.soft_max_deg,
                                default_value=0.0,
                                width=cfg["component_sizes"]["slider_width"],
                                height=cfg["component_sizes"]["slider_height"],
                                format="%.1f°",
                                enabled=False,
                                no_input=True
                            )
                            
                            # FET温度 - 进度条
                            dpg.add_text("FET温度:")
                            dpg.add_progress_bar(
                                tag=f"axis_{nid}_temp_fet_bar",
                                default_value=0.0,
                                width=cfg["component_sizes"]["progress_bar_width"],
                                height=cfg["component_sizes"]["progress_bar_height"],
                                overlay="0°C"
                            )
                            
                            # 电机温度 - 进度条
                            dpg.add_text("电机温度:")
                            dpg.add_progress_bar(
                                tag=f"axis_{nid}_temp_motor_bar",
                                default_value=0.0,
                                width=cfg["component_sizes"]["progress_bar_width"],
                                height=cfg["component_sizes"]["progress_bar_height"],
                                overlay="0°C"
                            )
                            
                            # 输入电压 - 文本
                            dpg.add_text("输入电压:")
                            dpg.add_text("-", tag=f"axis_{nid}_voltage_text")
                            
                            # 输入电流 - 进度条
                            dpg.add_text("输入电流:")
                            dpg.add_progress_bar(
                                tag=f"axis_{nid}_i_in_bar",
                                default_value=0.5,  # 中间位置表示0A
                                width=cfg["component_sizes"]["progress_bar_width"],
                                height=cfg["component_sizes"]["progress_bar_height"],
                                overlay="0A"
                            )
                            
                            # 电机电流 - 进度条
                            dpg.add_text("电机电流:")
                            dpg.add_progress_bar(
                                tag=f"axis_{nid}_i_motor_bar",
                                default_value=0.5,  # 中间位置表示0A
                                width=cfg["component_sizes"]["progress_bar_width"],
                                height=cfg["component_sizes"]["progress_bar_height"],
                                overlay="0A"
                            )
                            
                            # RPM - 进度条
                            dpg.add_text("转速:")
                            dpg.add_progress_bar(
                                tag=f"axis_{nid}_rpm_bar",
                                default_value=0.5,  # 中间位置表示0RPM
                                width=cfg["component_sizes"]["progress_bar_width"],
                                height=cfg["component_sizes"]["progress_bar_height"],
                                overlay="0 RPM"
                            )
                            
                            # 添加间距
                            dpg.add_spacer(height=cfg["component_sizes"]["motor_panel_spacing"])
            else:
                dpg.add_text("后端未就绪，无法显示电机状态。")

    def _start_status_loop(self):
        if self._status_thread and self._status_thread.is_alive():
            return
        self._stop_event.clear()
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()

    def _status_loop(self):
        cfg = STATUS_DISPLAY_CONFIG
        
        while not self._stop_event.is_set():
            try:
                # 更新连接状态
                connected = False
                if self.bridge and hasattr(self.bridge, "can_if") and self.bridge.can_if:
                    connected = (self.bridge.can_if.bus is not None)
                dpg.set_value("connection_status_txt", f"状态: {'已连接' if connected else '未连接'}")

                # 更新各轴状态
                if self.bridge and hasattr(self.bridge, "arm") and self.bridge.arm:
                    for nid in sorted(self.bridge.arm.axes.keys()):
                        st = self.bridge.vesc.get_state(nid) if hasattr(self.bridge, "vesc") else None
                        
                        # 初始化该轴的曲线数据缓存
                        if nid not in self.plot_data:
                            self.plot_data[nid] = {
                                "time": [], "temp_fet": [], "temp_motor": [],
                                "i_motor": [], "i_in": [], "pos": [], "deg_per_s": []
                            }
                        
                        if st and not st.offline:
                            dpg.set_value(f"axis_{nid}_status_txt", "状态: 在线")
                            # 位置滑块显示
                            if st.pos_deg is not None:
                                dpg.set_value(f"axis_{nid}_pos_slider", float(st.pos_deg))
                            elif st.pos_mod_turns is not None:
                                dpg.set_value(f"axis_{nid}_pos_slider", float(st.pos_mod_turns * 360.0))
                            else:
                                dpg.set_value(f"axis_{nid}_pos_slider", float(st.pos_unwrapped_turns * 360.0))
                            
                            # FET温度进度条
                            if st.temp_mos is not None:
                                temp_range = cfg["temperature"]["max"] - cfg["temperature"]["min"]
                                temp_val = (st.temp_mos - cfg["temperature"]["min"]) / temp_range
                                temp_val = max(0, min(1, temp_val))
                                dpg.set_value(f"axis_{nid}_temp_fet_bar", temp_val)
                                dpg.configure_item(f"axis_{nid}_temp_fet_bar", overlay=f"{st.temp_mos:.1f}°C")
                            
                            # 电机温度进度条
                            if st.temp_motor is not None:
                                temp_range = cfg["temperature"]["max"] - cfg["temperature"]["min"]
                                temp_val = (st.temp_motor - cfg["temperature"]["min"]) / temp_range
                                temp_val = max(0, min(1, temp_val))
                                dpg.set_value(f"axis_{nid}_temp_motor_bar", temp_val)
                                dpg.configure_item(f"axis_{nid}_temp_motor_bar", overlay=f"{st.temp_motor:.1f}°C")
                            
                            # 输入电压文本显示
                            if st.voltage_in is not None:
                                dpg.set_value(f"axis_{nid}_voltage_text", f"{st.voltage_in:.1f}V")
                            else:
                                dpg.set_value(f"axis_{nid}_voltage_text", "-")
                            
                            # 输入电流进度条 (双向，中心为0)
                            if st.current_in is not None:
                                i_in_range = cfg["current_input"]["max"] - cfg["current_input"]["min"]
                                i_in_val = (st.current_in) - cfg["current_input"]["min"] / i_in_range
                                i_in_val = max(0, min(1, i_in_val))
                                dpg.set_value(f"axis_{nid}_i_in_bar", i_in_val)
                                dpg.configure_item(f"axis_{nid}_i_in_bar", overlay=f"{st.current_in:.3f}A")
                            
                            # 电机电流进度条 (双向，中心为0)
                            if st.current_motor is not None:
                                i_motor_range = cfg["current_motor"]["max"] - cfg["current_motor"]["min"]
                                i_motor_val = (st.current_motor - cfg["current_motor"]["min"]) / i_motor_range
                                i_motor_val = max(0, min(1, i_motor_val))
                                dpg.set_value(f"axis_{nid}_i_motor_bar", i_motor_val)
                                dpg.configure_item(f"axis_{nid}_i_motor_bar", overlay=f"{st.current_motor:.3f}A")
                            
                            # RPM进度条 (双向，中心为0)
                            if st.rpm is not None:
                                rpm_range = cfg["rpm"]["max"] - cfg["rpm"]["min"]
                                rpm_val = (st.rpm - cfg["rpm"]["min"]) / rpm_range
                                rpm_val = max(0, min(1, rpm_val))
                                dpg.set_value(f"axis_{nid}_rpm_bar", rpm_val)
                                dpg.configure_item(f"axis_{nid}_rpm_bar", overlay=f"{st.rpm:.0f} RPM")
                            
                            # 更新曲线数据
                            current_time = time.time() - self.plot_start_time
                            plot_d = self.plot_data[nid]
                            plot_d["time"].append(current_time)
                            plot_d["temp_fet"].append(st.temp_mos if st.temp_mos is not None else 0.0)
                            plot_d["temp_motor"].append(st.temp_motor if st.temp_motor is not None else 0.0)
                            plot_d["i_motor"].append(st.current_motor if st.current_motor is not None else 0.0)
                            plot_d["i_in"].append(st.current_in if st.current_in is not None else 0.0)
                            plot_d["pos"].append(st.pos_deg if st.pos_deg is not None else 0.0)
                            plot_d["deg_per_s"].append(st.deg_per_s if st.deg_per_s is not None else 0.0)
                            
                            # 限制历史点数
                            max_pts = self.plot_history_size
                            if len(plot_d["time"]) > max_pts:
                                for k in plot_d.keys():
                                    plot_d[k] = plot_d[k][-max_pts:]
                            
                            # 更新曲线图
                            try:
                                dpg.set_value(f"plot_{nid}_temp_fet", [plot_d["time"], plot_d["temp_fet"]])
                                dpg.set_value(f"plot_{nid}_temp_motor", [plot_d["time"], plot_d["temp_motor"]])
                                dpg.set_value(f"plot_{nid}_i_motor", [plot_d["time"], plot_d["i_motor"]])
                                dpg.set_value(f"plot_{nid}_i_in", [plot_d["time"], plot_d["i_in"]])
                                dpg.set_value(f"plot_{nid}_pos", [plot_d["time"], plot_d["pos"]])
                                dpg.set_value(f"plot_{nid}_deg_per_s", [plot_d["time"], plot_d["deg_per_s"]])
                            except Exception:
                                pass
                        else:
                            # 无数据时重置所有组件
                            dpg.set_value(f"axis_{nid}_status_txt", "状态: 离线")
                            dpg.set_value(f"axis_{nid}_pos_slider", 0.0)
                            dpg.set_value(f"axis_{nid}_temp_fet_bar", 0.0)
                            dpg.configure_item(f"axis_{nid}_temp_fet_bar", overlay="-")
                            dpg.set_value(f"axis_{nid}_temp_motor_bar", 0.0)
                            dpg.configure_item(f"axis_{nid}_temp_motor_bar", overlay="-")
                            dpg.set_value(f"axis_{nid}_voltage_text", "-")
                            dpg.set_value(f"axis_{nid}_i_in_bar", 0.0)
                            dpg.configure_item(f"axis_{nid}_i_in_bar", overlay="-")
                            dpg.set_value(f"axis_{nid}_i_motor_bar", 0.5)
                            dpg.configure_item(f"axis_{nid}_i_motor_bar", overlay="-")
                            dpg.set_value(f"axis_{nid}_rpm_bar", 0.5)
                            dpg.configure_item(f"axis_{nid}_rpm_bar", overlay="-")
            except Exception as e:
                # 避免线程中断
                pass
            time.sleep(self.status_update_interval_s)

    # ---------------- 事件处理 ----------------
    def _on_connect(self):
        try:
            if self.bridge:
                self.bridge.connect()
                dpg.set_value("connection_status_txt", "状态: 已连接")
                self.logger.log_success("已连接 CAN 与控制线程")
        except Exception as e:
            self.logger.log_error(f"连接失败: {e}")

    def _on_disconnect(self):
        try:
            if self.bridge:
                self.bridge.disconnect()
                dpg.set_value("connection_status_txt", "状态: 未连接")
                self.logger.log_info("已断开连接")
        except Exception as e:
            self.logger.log_error(f"断开失败: {e}")

    def _on_enable_all(self):
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法使能")
                return
            for nid in sorted(self.bridge.arm.axes.keys()):
                self.bridge.arm.set_axis_enabled(nid, True)
                # 同步更新每轴启用复选框
                try:
                    dpg.set_value(f"axis_{nid}_enable_chk", True)
                except Exception:
                    pass
            self.logger.log_success("已使能全部轴")
        except Exception as e:
            self.logger.log_error(f"使能全部失败: {e}")

    def _on_start_control(self):
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法启动控制循环")
                return
            self.bridge.arm.start()
            self.logger.log_success("已启动控制循环")
        except Exception as e:
            self.logger.log_error(f"启动控制循环失败: {e}")

    def _on_stop_control(self):
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法停止控制循环")
                return
            self.bridge.arm.stop()
            self.logger.log_success("已停止控制循环")
        except Exception as e:
            self.logger.log_error(f"停止控制循环失败: {e}")

    def _on_disable_all(self):
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法失能")
                return
            for nid in sorted(self.bridge.arm.axes.keys()):
                self.bridge.arm.set_axis_enabled(nid, False)
                try:
                    dpg.set_value(f"axis_{nid}_enable_chk", False)
                except Exception:
                    pass
            self.logger.log_success("已失能全部轴")
        except Exception as e:
            self.logger.log_error(f"失能全部失败: {e}")

    def _on_cancel_homing(self):
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法终止找零")
                return
            self.bridge.arm.cancel_homing()
            self.logger.log_info("已请求终止找零")
        except Exception as e:
            self.logger.log_error(f"终止找零失败: {e}")

    def _find_zero(self):
        """对所有轴执行找零（根据 settings.HOMING_CONFIG）。"""
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法找零")
                return
            self.logger.log_info("开始全轴找零...")
            # 在后台线程执行，避免阻塞 GUI
            threading.Thread(target=self.bridge.arm.home_all, daemon=True).start()
        except Exception as e:
            self.logger.log_error(f"找零失败: {e}")

    def _on_target_change(self, sender, app_data, user_data):
        node_id = user_data
        try:
            if self.bridge and hasattr(self.bridge, "arm"):
                val = float(app_data)
                self.bridge.arm.set_axis_target(node_id, val)
                self.logger.log_info(f"设置轴 {node_id} 目标角度为 {val:.2f} 度")
        except Exception as e:
            self.logger.log_error(f"设置目标角失败: {e}")

    def _on_enable_toggle(self, sender, app_data, user_data):
        node_id = user_data
        try:
            if self.bridge and hasattr(self.bridge, "arm"):
                val = dpg.get_value(f"axis_{node_id}_enable_chk")
                self.bridge.arm.set_axis_enabled(node_id, bool(val))
                self.logger.log_info(("启用" if val else "禁用") + f" 轴 {node_id}")
        except Exception as e:
            self.logger.log_error(f"切换启用失败: {e}")

    def _on_direction_change(self, sender, app_data, user_data):
        node_id = user_data
        try:
            if self.bridge and hasattr(self.bridge, "arm"):
                val = dpg.get_value(f"axis_{node_id}_dir_combo")
                self.bridge.arm.set_axis_direction_lock(node_id, str(val))
                self.logger.log_info(f"设置轴 {node_id} 方向锁为 {val}")
        except Exception as e:
            self.logger.log_error(f"设置方向失败: {e}")

    def _on_home_axis(self, sender, app_data, user_data):
        nid = int(user_data)
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法找零")
                return
            self.logger.log_info(f"开始轴 {nid} 找零...")
            threading.Thread(target=lambda: self.bridge.arm.home_axis(nid), daemon=True).start()
        except Exception as e:
            self.logger.log_error(f"轴 {nid} 找零失败: {e}")

    def _on_apply_homing_params(self, sender, app_data, user_data):
        """应用找零参数设置（每轴独立）"""
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法应用参数")
                return
            
            nid = user_data["nid"]
            tags = user_data["tags"]
            
            # 读取并更新配置
            axis_cfg = self.bridge.arm.axes[nid].cfg
            def_val = HOMING_CONFIG
            
            # 更新找零模式
            mode = dpg.get_value(tags["mode"])
            axis_cfg.homing_mode = mode if mode in ["rpm", "current"] else def_val.get("mode","rpm")
            
            # 更新各项参数
            axis_cfg.homing_move_direction = int(dpg.get_value(tags["move_direction"]))
            axis_cfg.homing_rpm = float(dpg.get_value(tags["rpm"]))
            axis_cfg.homing_current_a = float(dpg.get_value(tags["current_a"]))
            axis_cfg.homing_current_threshold_a = float(dpg.get_value(tags["current_threshold_a"]))
            axis_cfg.homing_collision_dwell_s = float(dpg.get_value(tags["collision_dwell_s"]))
            axis_cfg.homing_timeout_s = float(dpg.get_value(tags["timeout_s"]))
            axis_cfg.homing_backoff_deg = float(dpg.get_value(tags["backoff_deg"]))
            axis_cfg.homing_backoff_rpm = float(dpg.get_value(tags["backoff_rpm"]))
            axis_cfg.homing_sample_period_s = float(dpg.get_value(tags["sample_period_s"]))
            axis_cfg.homing_command_period_s = float(dpg.get_value(tags["command_period_s"]))
            axis_cfg.homing_send_idle_keepalive = bool(dpg.get_value(tags["send_idle_keepalive"]))
            
            # 应用配置更改（当前无需通知控制线程，home时读取即时生效）
            self.logger.log_success(f"轴 {nid} 找零参数已应用")
        except Exception as e:
            self.logger.log_error(f"应用找零参数失败: {e}")

    def _on_apply_speed_limits(self, sender, app_data, user_data):
        try:
            if not self.bridge or not hasattr(self.bridge, "arm") or self.bridge.arm is None:
                self.logger.log_error("后端未就绪，无法应用限速")
                return
            nid = int(user_data["nid"])
            vel_tag = user_data["vel_tag"]
            acc_tag = user_data["acc_tag"]
            vel = float(dpg.get_value(vel_tag))
            acc = float(dpg.get_value(acc_tag))
            axis_cfg = self.bridge.arm.axes[nid].cfg
            axis_cfg.max_vel_dps = vel
            axis_cfg.max_accel_dps2 = acc
            self.logger.log_success(f"轴 {nid} 限速已应用: vel={vel:.1f}°/s, acc={acc:.1f}°/s^2")
        except Exception as e:
            self.logger.log_error(f"应用限速失败: {e}")

    def _on_apply_plot_history(self):
        try:
            new_size = dpg.get_value("plot_history_size")
            if new_size and new_size > 0:
                self.plot_history_size = int(new_size)
                self.logger.log_success(f"曲线历史点数已设置为 {self.plot_history_size}")
        except Exception as e:
            self.logger.log_error(f"应用历史点数失败: {e}")
