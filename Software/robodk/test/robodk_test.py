from robodk import robolink, robomath
import csv

RDK = robolink.Robolink()

# 获取程序对象（请替换为你的程序名称）
program = RDK.Item('程序1', robolink.ITEM_TYPE_PROGRAM)

# 生成程序的关节轨迹（包含速度信息）
# 参数说明：
#   step_mm: 轨迹采样步长（线性运动时的每步距离，越小越密）
#   step_deg: 关节运动的角度步长
#   time_step: 时间步长，可设为0让 RoboDK 自计算
# InstructionListJoints 返回: (message, joint_list, status)
# joint_list 是一个 robomath.Mat，其中每列对应一个采样点（columns = samples）
# status < 0 表示错误，否则返回可执行的指令数量
msg, joint_matrix, status = program.InstructionListJoints(mm_step=10, save_to_file="/Users/lub/Downloads/test/joint_path_with_speed.csv", deg_step=1, time_step=0.01, flags=4)

if status < 0:
    print(f"⚠️ 无法生成轨迹：{msg}")
else:
    # RoboDK 的 Mat 每列是一个采样点，转换为行列表以便写入 CSV
    # 将 robomath.Mat 转为标准的二维列表（行 = 样本）
    try:
        mat_list = list(joint_matrix)
    except Exception:
        # 如果 joint_matrix 为空或无法迭代
        mat_list = []

    # mat_list is a list of columns; transpose to rows
    # rows = []
    # if mat_list:
    #     # each element in mat_list is a column (list-like), with length = number of rows per column
    #     num_rows = len(mat_list)
    #     num_cols = len(mat_list[0])
    #     for r in range(num_rows):
    #         row = [mat_list[c][r] for c in range(num_cols)]
    #         rows.append(row)

    # # 导出CSV
    # with open("joint_path_with_speed.csv", "w", newline="") as f:
    #     writer = csv.writer(f)
    #     if rows:
    #         # 根据你的机械臂自由度自动调整列数
    #         # 假设最后两列为 LinearSpeed 和 JointSpeed（如果 flags 参数包含它们）
    #         num_joints = len(rows[0]) - 2 if len(rows[0]) >= 2 else len(rows[0])
    #         header = [f"J{i+1}" for i in range(num_joints)] + ["timings(mm/s)", "LinearSpeed(mm/s)", "LinearSpeed(mm/s)", "JointSpeed(deg/s)"]
    #         writer.writerow(header)
    #         writer.writerows(rows)
    #     else:
    #         print("⚠️ 未从 RoboDK 返回任何轨迹数据，CSV 未生成。")

    print("✅ 关节角度与速度已导出到 joint_path_with_speed.csv")
