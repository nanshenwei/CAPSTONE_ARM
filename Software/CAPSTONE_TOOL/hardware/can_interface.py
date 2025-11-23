import threading
from utils.log_utils import globalLogger
from typing import Callable, Optional

import can


class CANInterface:
    def __init__(self, interface: str, channel: str, bitrate: int):
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.bus: Optional[can.Bus] = None
        self.rx_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.on_message: Optional[Callable[[can.Message], None]] = None
        self.log = globalLogger

    def start(self):
        if self.bus:
            return
        self.bus = can.Bus(interface=self.interface, channel=self.channel, bitrate=self.bitrate)
        self._stop.clear()
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.rx_thread.start()
        self.log.info(f"CAN started: {self.interface} {self.channel} {self.bitrate}")

    def stop(self):
        self._stop.set()
        if self.rx_thread:
            self.rx_thread.join(timeout=1.0)
        if self.bus:
            self.bus.shutdown()
        self.bus = None
        self.rx_thread = None
        self.log.info("CAN stopped")

    def send(self, arbitration_id: int, data: bytes, extended_id: bool):
        if not self.bus:
            return
        msg = can.Message(arbitration_id=arbitration_id, is_extended_id=extended_id, data=data)
        try:
            self.bus.send(msg, timeout=0.02)
        except can.CanError as e:
            self.log.warning(f"CAN send error: {e}")

    def _rx_loop(self):
        assert self.bus
        while not self._stop.is_set():
            try:
                msg = self.bus.recv(0.05)
            except Exception:
                msg = None
            if msg is None:
                continue
            if self.on_message:
                try:
                    self.on_message(msg)
                except Exception as e:
                    self.log.exception(f"on_message error: {e}")
