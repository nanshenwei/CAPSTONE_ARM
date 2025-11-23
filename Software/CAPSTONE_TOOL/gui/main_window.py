import dearpygui.dearpygui as dpg
from .control_page import ControlPage  
from config.settings import APP_CONFIG

import sys
platform = ''
if sys.platform.startswith("win"):     # Windows 平台 (win32 或 win64)
    print("当前运行在 Windows")
    platform = 'windows'
elif sys.platform == "darwin":          # macOS 平台
    print("当前运行在 macOS")
    platform = 'macos'
else:
    platform = 'other'
    print("其他平台：", sys.platform)

class MultiPageGUI:
    def __init__(self, bridge=None, logger=None):
        self.bridge = bridge  # 后端桥接（AppBridge）
        self.logger = logger
        self.setup_gui()
    
    def setup_gui(self):
        dpg.create_context()
        with dpg.font_registry():
            with dpg.font("fonts/PingFang-Medium.ttf", 36) as main_font:
                # 完整的中文字符范围覆盖
                dpg.add_font_range(0x2E80, 0x9FFF)  # 中日韩统一表意文字扩展
                dpg.add_font_range(0xFF00, 0xFFEF)  # 半角全角字符
                dpg.add_font_range(0x3000, 0x303F)  # 中文标点符号
                dpg.add_font_range(0x4E00, 0x9FAF)  # 基本汉字
                # 添加常用拉丁字符
                dpg.add_font_range(0x0020, 0x007F)
                dpg.add_font_range(0x2190, 0x21FF)  # 常用箭头
                dpg.bind_font(main_font)
                
            dpg.set_global_font_scale(0.5)
            


        dpg.create_viewport(
            title=APP_CONFIG['title'], 
            width=APP_CONFIG['width'], 
            height=APP_CONFIG['height']
        )
        

        # 主窗口
        with dpg.window(label=APP_CONFIG['title'], tag="primary_window"):
            # 标签栏
            with dpg.tab_bar():
                # 创建各个页面
                self.control_page = ControlPage(bridge=self.bridge, logger=self.logger)
                # TODO: 在此添加"机械臂"页面，接线到 self.bridge
        dpg.set_primary_window("primary_window", True)
        dpg.setup_dearpygui()
        dpg.show_viewport()
    
    def run(self):
        """运行主循环"""
        # 启动GUI
        dpg.start_dearpygui()
        
        # 清理资源
        self.cleanup()
        dpg.destroy_context()
    
    def cleanup(self):
        """清理资源"""
        pass