import dearpygui.dearpygui as dpg
import threading
import time
import re
import os
from datetime import datetime
from enum import IntEnum
import inspect

class LoggerTool:
    def __init__(self, tag):
        self.scroll_timer = None
        self.scroll_delay = 0.032
        self.tag = tag
        self.log_count = 0
        self.raw_log_content = ""
        # ANSI 颜色映射
        self.ansi_colors = {
            '30': [0, 0, 0, 255],           # 黑色
            '31': [255, 0, 0, 255],         # 红色
            '32': [0, 255, 0, 255],         # 绿色
            '33': [255, 255, 0, 255],       # 黄色
            '34': [0, 0, 255, 255],         # 蓝色
            '35': [255, 0, 255, 255],       # 紫色
            '36': [0, 255, 255, 255],       # 青色
            '37': [255, 255, 255, 255],     # 白色
            '90': [128, 128, 128, 255],     # 亮黑（灰色）
            '91': [255, 85, 85, 255],       # 亮红
            '92': [85, 255, 85, 255],       # 亮绿
            '93': [255, 255, 85, 255],      # 亮黄
            '94': [85, 85, 255, 255],       # 亮蓝
            '95': [255, 85, 255, 255],      # 亮紫
            '96': [85, 255, 255, 255],      # 亮青
            '97': [255, 255, 255, 255],     # 亮白
        }

    def create_context(self, hight_lim=250, width_lim=780):
        # 日志控制按钮组
        with dpg.group(horizontal=False):
            with dpg.group(horizontal=True):
                dpg.add_checkbox(label="自动滚动", tag=f"auto_scroll_{self.tag}", default_value=True)
                dpg.add_checkbox(label="解析颜色", tag=f"parse_colors_{self.tag}", default_value=True)
                dpg.add_button(label="滚动到底部", callback=lambda: self.scroll_to_bottom())
                dpg.add_button(label="清空日志", callback=lambda: self.clear_log())
                # dpg.add_button(label="保存日志", callback=lambda: self.save_log())
                # dpg.add_button(label="导出详细日志", callback=lambda: self.export_log_with_metadata())
                # dpg.add_button(label="在Finder中打开", callback=lambda: self.open_log_folder())

            # 日志输出
            with dpg.child_window(tag=f"log_child_window_{self.tag}", height=hight_lim, width=width_lim, 
                        horizontal_scrollbar=True, menubar=False):
                # 减少组件间距
                with dpg.theme(tag=f"log_theme_{self.tag}"):
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 2)  # 减少垂直间距
                
                dpg.add_group(tag=f"log_content_{self.tag}")
                dpg.bind_item_theme(f"log_content_{self.tag}", f"log_theme_{self.tag}")

    def parse_ansi_string(self, text):
        """解析 ANSI 颜色代码"""
        ansi_pattern = r'\x1b\[([0-9;]*)m'
        
        parts = []
        current_pos = 0
        current_color = [255, 255, 255, 255]  # 默认白色
        
        for match in re.finditer(ansi_pattern, text):
            # 添加颜色代码前的文本
            if match.start() > current_pos:
                plain_text = text[current_pos:match.start()]
                if plain_text:
                    parts.append((plain_text, current_color.copy()))
            
            # 解析颜色代码
            codes = match.group(1).split(';') if match.group(1) else ['0']
            for code in codes:
                if code == '0' or code == '':  # 重置
                    current_color = [255, 255, 255, 255]
                elif code in self.ansi_colors:
                    current_color = self.ansi_colors[code].copy()
            
            current_pos = match.end()
        
        # 添加剩余文本
        if current_pos < len(text):
            remaining_text = text[current_pos:]
            if remaining_text:
                parts.append((remaining_text, current_color))
        
        return parts

    def log(self, message, is_serial_data=False):
        """添加日志 - 支持颜色解析，每行作为独立组件"""
        timestamp = time.strftime('%H:%M:%S')
        full_message = f"[{timestamp}] {message}"
        self.raw_log_content += full_message+"\n"
        try:
            parse_colors = dpg.get_value(f"parse_colors_{self.tag}")
        except:
            parse_colors = True
        
        if parse_colors:
            # 按行分割消息
            lines = full_message.split('\n')
            
            for line in lines:
                self.log_count += 1
                
                if line.strip():  # 非空行
                    # 解析ANSI颜色
                    color_parts = self.parse_ansi_string(line)
                    
                    if color_parts:
                        # 创建水平组来保持同一行的不同颜色部分在一起
                        with dpg.group(parent=f"log_content_{self.tag}", horizontal=True,
                                     tag=f"log_line_{self.tag}_{self.log_count}"):
                            
                            for part_index, (text_part, color) in enumerate(color_parts):
                                if text_part:  # 非空文本
                                    text_tag = f"log_text_{self.tag}_{self.log_count}_{part_index}"
                                    dpg.add_text(text_part, tag=text_tag, color=color)
                    else:
                        # 没有颜色信息的行
                        dpg.add_text(line, parent=f"log_content_{self.tag}",
                                   tag=f"log_line_{self.tag}_{self.log_count}")
                else:
                    # 空行：创建一个包含单个空格的文本，高度更小
                    dpg.add_text(" ", parent=f"log_content_{self.tag}",
                               tag=f"log_line_{self.tag}_{self.log_count}")
        else:
            # 不解析颜色的情况
            clean_message = re.sub(r'\x1b\[[0-9;]*m', '', full_message)
            lines = clean_message.split('\n')
            
            for line in lines:
                self.log_count += 1
                # 空行也显示为包含空格的文本
                display_text = line if line.strip() else " "
                dpg.add_text(display_text, parent=f"log_content_{self.tag}",
                           tag=f"log_line_{self.tag}_{self.log_count}")
        
        # 限制日志条目数量
        self.limit_log_entries()
        
        # 防抖滚动
        try:
            if dpg.get_value(f"auto_scroll_{self.tag}"):
                self.debounce_scroll()
        except:
            pass

    # ---- 彩色日志便捷方法 ----
    def _colorize(self, msg: str, sgr: str) -> str:
        return f"\x1b[{sgr}m{msg}\x1b[0m"

    def log_debug(self, msg: str):
        self.log(self._colorize(msg, '36'))  # 青色

    def log_info(self, msg: str):
        self.log(self._colorize(msg, '32'))  # 绿色

    def log_warning(self, msg: str):
        self.log(self._colorize(msg, '33'))  # 黄色

    def log_error(self, msg: str):
        self.log(self._colorize(msg, '31'))  # 红色

    def log_critical(self, msg: str):
        self.log(self._colorize(msg, '91'))  # 亮红

    def log_success(self, msg: str):
        self.log(self._colorize(msg, '92'))  # 亮绿


    def limit_log_entries(self, max_entries=500):
        """限制日志条目数量"""
        if self.log_count > max_entries:
            entries_to_remove = self.log_count - max_entries
            for i in range(1, entries_to_remove + 1):
                try:
                    dpg.delete_item(f"log_line_{self.tag}_{i}")
                except:
                    pass

    def debounce_scroll(self):
        """防抖滚动"""
        if self.scroll_timer is not None:
            self.scroll_timer.cancel()
        
        self.scroll_timer = threading.Timer(self.scroll_delay, self.scroll_to_bottom)
        self.scroll_timer.start()
    
    def scroll_to_bottom(self):
        """滚动到底部"""
        try:
            window_y_max = dpg.get_y_scroll_max(f"log_child_window_{self.tag}")
            dpg.set_y_scroll(f"log_child_window_{self.tag}", window_y_max)
        except Exception as e:
            print(f"滚动失败: {e}")
        finally:
            self.scroll_timer = None

    def clear_log(self):
        """清空日志"""
        try:
            dpg.delete_item(f"log_content_{self.tag}", children_only=True)
            dpg.add_group(tag=f"log_content_{self.tag}", parent=f"log_child_window_{self.tag}")
            dpg.bind_item_theme(f"log_content_{self.tag}", f"log_theme_{self.tag}")
            self.log_count = 0
        except:
            pass

    def save_log(self):
        """保存标准格式的日志文件"""
        if self.raw_log_content.strip():
            def file_selected_callback(sender, app_data, user_data):
                if 'file_path_name' in app_data:
                    file_path = app_data['file_path_name']
                    if file_path:
                        try:
                            # 确保文件有.log扩展名
                            if not file_path.endswith('.log'):
                                file_path += '.log'
                            
                            # 清理内容：移除ANSI代码和规范化换行符
                            clean_content = re.sub(r'\x1b\[[0-9;]*m', '', self.raw_log_content)
                            clean_content = clean_content.replace('\r\n', '\n').replace('\r', '\n')
                            
                            # 移除多余的空行
                            lines = clean_content.split('\n')
                            cleaned_lines = []
                            for line in lines:
                                # 移除行尾空格
                                line = line.rstrip()
                                cleaned_lines.append(line)
                            
                            # 重新组合，确保文件以换行符结尾
                            final_content = '\n'.join(cleaned_lines)
                            if final_content and not final_content.endswith('\n'):
                                final_content += '\n'
                            
                            # 使用UTF-8编码保存
                            with open(file_path, 'w', encoding='utf-8', newline='') as f:
                                f.write(final_content)
                            
                            # 在Mac上设置正确的文件类型
                            if os.name == 'posix':  # Unix/Linux/macOS
                                try:
                                    os.system(f'touch "{file_path}"')
                                except:
                                    pass
                            
                            print(f"日志已保存到: {file_path}")
                            
                        except Exception as e:
                            print(f"保存日志失败: {e}")
                
                dpg.delete_item("file_dialog_id")
        
            def cancel_callback(sender, app_data, user_data):
                dpg.delete_item("file_dialog_id")
        
            # 获取当前时间作为默认文件名
            default_filename = f"log_{time.strftime('%Y%m%d_%H%M%S')}.log"
            
            # 获取用户桌面路径作为默认位置
            home_dir = os.path.expanduser("~")
            desktop_dir = os.path.join(home_dir, "Downloads")
            with dpg.file_dialog(
                tag="file_dialog_id",
                label="保存日志文件",
                default_path=desktop_dir,
                modal=True,
                callback=file_selected_callback,
                cancel_callback=cancel_callback,
                default_filename=default_filename,
                width=600,
                height=400
            ):
                dpg.add_file_extension(".log", color=(150, 255, 150, 255), custom_text="[Log]")
                dpg.add_file_extension(".txt", color=(255, 255, 255, 255), custom_text="[Text]")

    def export_log_with_metadata(self):
        """导出带有元数据的标准日志文件"""
        if self.raw_log_content.strip():
            def file_selected_callback(sender, app_data, user_data):
                if 'file_path_name' in app_data:
                    file_path = app_data['file_path_name']
                    if file_path:
                        try:
                            # 创建标准的日志文件头
                            header = \
                                        f"# Log File Generated by GDASTool Logger, tag:{self.tag}\n" + \
                                        f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n" + \
                                        "# Format: [HH:MM:SS] Message\n" + \
                                        "# Encoding: UTF-8\n" + \
                                        "# =====================================\n" + \
                                        "\n"
                            
                            # 清理内容
                            clean_content = re.sub(r'\x1b\[[0-9;]*m', '', self.raw_log_content)
                            clean_content = clean_content.replace('\r\n', '\n').replace('\r', '\n')
                            
                            # 组合最终内容
                            final_content = header + clean_content
                            
                            # 确保以换行符结尾
                            if not final_content.endswith('\n'):
                                final_content += '\n'
                            
                            with open(file_path, 'w', encoding='utf-8', newline='') as f:
                                f.write(final_content)
                            
                            print(f"带元数据的日志已保存到: {file_path}")
                            
                        except Exception as e:
                            print(f"保存失败: {e}")
                
                dpg.delete_item("export_dialog_id")
        
            def cancel_callback(sender, app_data, user_data):
                dpg.delete_item("export_dialog_id")
        
            default_filename = f"detailed_log_{time.strftime('%Y%m%d_%H%M%S')}.log"
            
            with dpg.file_dialog(
                tag="export_dialog_id",
                label="导出详细日志",
                modal=True,
                callback=file_selected_callback,
                cancel_callback=cancel_callback,
                default_filename=default_filename,
                width=600,
                height=400
            ):
                dpg.add_file_extension(".log", color=(150, 255, 150, 255))

    def open_log_folder(self):
        """在Finder中打开日志文件夹"""
        try:
            import subprocess
            # 获取用户桌面路径作为默认位置
            home_dir = os.path.expanduser("~")
            desktop_dir = os.path.join(home_dir, "Downloads")
            
            if os.name == 'posix':  # macOS/Linux
                subprocess.run(['open', desktop_dir])
            elif os.name == 'nt':  # Windows
                subprocess.run(['explorer', desktop_dir])
                
        except Exception as e:
            print(f"无法打开文件夹: {e}")

# 全局调试器
class LogLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

class GlobalLogger:
    # ANSI颜色代码
    COLORS = {
        LogLevel.DEBUG: '\033[36m',
        LogLevel.INFO: '\033[32m',
        LogLevel.WARNING: '\033[33m',
        LogLevel.ERROR: '\033[31m',
        LogLevel.CRITICAL: '\033[91m',
    }
    RESET = '\033[0m'
    
    def __init__(self, level=LogLevel.INFO, enable_color=True):
        self.level = level
        self.enable_color = enable_color
    
    # def _get_caller_info(self):
    #     # 获取调用栈，跳过当前函数和_log函数
    #     frame = inspect.currentframe().f_back.f_back
    #     filename = os.path.basename(frame.f_code.co_filename)
    #     function_name = frame.f_code.co_name
    #     line_number = frame.f_lineno
    #     return f"{filename}:{function_name}:{line_number}"
    
    # def _get_caller_info(self):
    #     # 调用栈：_get_caller_info -> _log -> debug/info/etc -> 用户代码
    #     frame = inspect.currentframe().f_back.f_back.f_back
    #     filename = os.path.basename(frame.f_code.co_filename)
    #     function_name = frame.f_code.co_name
    #     line_number = frame.f_lineno
    #     return f"{filename}:{function_name}:{line_number}"
    
    def _get_caller_info(self):
        # 获取调用栈，找到第一个不是当前文件的调用者
        stack = inspect.stack()
        current_file = __file__
        
        for frame_info in stack[1:]:  # 跳过当前函数
            if frame_info.filename != current_file:
                filename = os.path.basename(frame_info.filename)
                function_name = frame_info.function
                line_number = frame_info.lineno
                return f"{filename}:{function_name}:{line_number}"
    
        return "unknown:unknown:0"
    
    def _log(self, level, message):
        if level >= self.level:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            level_name = level.name
            caller_info = self._get_caller_info()
            
            if self.enable_color:
                color = self.COLORS.get(level, '')
                print(f"{color}[{level_name}] {timestamp} [{caller_info}] - {message}{self.RESET}")
            else:
                print(f"[{level_name}] {timestamp} [{caller_info}] - {message}")
    
    def debug(self, message): self._log(LogLevel.DEBUG, message)
    def info(self, message): self._log(LogLevel.INFO, message)
    def warning(self, message): self._log(LogLevel.WARNING, message)
    def error(self, message): self._log(LogLevel.ERROR, message)
    def critical(self, message): self._log(LogLevel.CRITICAL, message)
    def set_level(self, level): self.level = level

globalLogger = GlobalLogger(LogLevel.DEBUG)

# 使用示例
def demo():
    dpg.create_context()
    
    with dpg.window(label="彩色日志测试", width=800, height=400):
        logger = LoggerTool("demo_log")
        logger.create_context()
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
        def add_test_logs():
            logger.log("这是普通文本")
            logger.log_error("这是红色（错误）")
            logger.log_success("这是绿色（成功）")
            logger.log_warning("这是黄色（警告）")
            logger.log_debug("这是青色（调试）")
        
        dpg.add_button(label="添加测试日志", callback=lambda: add_test_logs())
    
    dpg.create_viewport(title="彩色日志演示")
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()

if __name__ == "__main__":
    demo()