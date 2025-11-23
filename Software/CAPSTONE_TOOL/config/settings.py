# 应用配置
APP_CONFIG = {
    "title": "CAPSTONE TOOL",
    "width": 1680,
    "height": 1080
}

# 串口配置
SERIAL_CONFIG = {
    "default_baud": 3000000,
    "timeout": 2,
}

# 状态显示配置
STATUS_DISPLAY_CONFIG = {
    # 温度范围 (°C)
    "temperature": {
        "min": 0,
        "max": 100,
        "warning_threshold": 60,
        "critical_threshold": 80
    },
    
    # 电压范围 (V)
    "voltage": {
        "min": 0,
        "max": 450,
        "nominal": 250
    },
    
    # 输入电流范围 (A)
    "current_input": {
        "min": -10,
        "max": 10
    },
    
    # 电机电流范围 (A)
    "current_motor": {
        "min": -50,
        "max": 50
    },
    
    # RPM范围
    "rpm": {
        "min": -30000,
        "max": 30000
    },
    
    # 组件尺寸
    "component_sizes": {
        "progress_bar_width": 200,
        "progress_bar_height": 20,
        "slider_width": 200,
        "slider_height": 25,
        "motor_panel_width": 210,
        "motor_panel_spacing": 10
    }
}

# 找零（Homing）配置
HOMING_CONFIG = {
    # 模式: "rpm" 使用速度模式轻推找限位；"current" 使用电流模式恒流推靠
    "mode": "rpm",
    # 运动方向：+1 或 -1（根据机构装配决定朝哪侧是机械零）
    "move_direction": -1,
    # 速度模式下的目标RPM
    "rpm": 10.0,
    # 电流模式下的目标电流（A）
    "current_a": 0.10,
    # 碰撞判定电流阈值（A），当 |I_motor| >= 阈值 且 持续 dwell 时间，则认为触碰
    "current_threshold_a": 0.12,
    # 阈值持续时间（s），用于去抖
    "collision_dwell_s": 0.08,
    # 整体超时时间（s）
    "timeout_s": 8.0,
    # 碰撞后回退角度（deg），以新零点为基准的反向回退
    "backoff_deg": 5.0,
    # 回退阶段的辅助速度（用于估算等待时间）
    "backoff_rpm": 20.0,
    # 监测采样周期（s）
    "sample_period_s": 0.01,
    "command_period_s": 0.05,    # 控制心跳发送周期（s）
    # 是否为未启用的其他轴发送 rpm=0 心跳
    "send_idle_keepalive": True,
}
