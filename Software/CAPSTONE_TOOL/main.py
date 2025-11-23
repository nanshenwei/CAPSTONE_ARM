#!/usr/bin/env python3
import logging
import threading
import time
from typing import Optional, Dict

from hardware.can_interface import CANInterface
from hardware.vesc_can import VescCAN, VescCANConfig
from control.arm_controller import ArmController
from config.arm_config import AxisConfig, AppConfig, CANConfig
from gui.main_window import MultiPageGUI
from utils.log_utils import LoggerTool

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class AppBridge:
    """
    连接后端控制（CAN/VESC/ArmController）与模板GUI。
    GUI 事件通过此桥接到控制器；状态通过周期刷新回传到GUI页面（后续可扩展）。
    """
    def __init__(self, logger: LoggerTool):

        self.can_if = CANInterface(CANConfig.interface, CANConfig.channel, CANConfig.bitrate)
        self.vesc = VescCAN(CANConfig)

        # 构造四轴配置，后续可从APP_CONFIG/其他配置源读取
        axes_cfg: Dict[int, AxisConfig] = {
            1: AxisConfig(node_id=1, homing_current_threshold_a=0.55),
            2: AxisConfig(node_id=2, homing_current_threshold_a=0.55),
            3: AxisConfig(node_id=3, reduction_ratio=80.0, homing_current_threshold_a=0.25),
            4: AxisConfig(node_id=4, reduction_ratio=80.0, homing_current_threshold_a=0.25),
        }
        # 将每轴配置注入到 VESC 层，便于状态换算（极对数、减速比）
        try:
            self.vesc.set_axis_configs(axes_cfg)
        except Exception:
            pass
        self.arm = ArmController(axes_cfg, self.vesc, self._send_can,
                                 control_rate_hz=AppConfig.control_rate_hz,
                                 logger=logger)

        # CAN 接收回调
        self.can_if.on_message = self._on_can_message

        # 后台状态刷新线程（如需要对GUI更新状态）
        # self._ui_thread = threading.Thread(target=self._ui_refresh_loop, daemon=True)

    def _send_can(self, arbitration_id: int, payload: bytes, extended: bool):
        self.can_if.send(arbitration_id, payload, extended)

    def _on_can_message(self, msg):
        unpack = self.vesc.unpack_id(msg.arbitration_id, msg.is_extended_id)
        if not unpack:
            return
        packet_id, node_id = unpack
        self.vesc.parse_status(packet_id, node_id, bytes(msg.data))

    def connect(self):
        self.can_if.start()
        # self.arm.start()
        # if not self._ui_thread.is_alive():
        #     self._ui_thread = threading.Thread(target=self._ui_refresh_loop, daemon=True)
        #     self._ui_thread.start()

    def disconnect(self):
        self.arm.stop()
        self.can_if.stop()

    # def _ui_refresh_loop(self):
    #     while True:
    #         time.sleep(0.1)
    #         # 可在此将 self.vesc.get_state(...) 的信息推送到GUI
    #         pass


def main():
    logger = LoggerTool("control_panel")
    bridge = AppBridge(logger)
    gui = MultiPageGUI(bridge=bridge, logger=logger)

    # 暴露给 GUI 页面使用的回调（后续在SerialPage或其他页面中绑定）
    # 由于当前模板页面仅展示串口占位，这里暂不绑定具体控件事件。

    # 启动后端
    # bridge.connect()

    # 运行 GUI
    gui.run()


if __name__ == "__main__":
    main()