import math
import numpy as np
from datetime import datetime

from mem_opt_dynamic_size3 import dynamic_choose_param

# ============================================================
# 复用率分析：固定矩阵尺寸下的详细分析
# ============================================================

LOG_PATH = "reuse_analysis_log.txt"

# 从示例行提取的参数
# 6  ConvMLP       16384    1024     256  1024   16   64    4   4   4   16     1.2%   1.000    1.012x
M = 16384
K = 1024
N = 256
x = 1024  # tiles in M direction
y = 16    # tiles in N direction
z = 64    # tiles in K direction

TILE = 16  # 分块尺寸

# 固定 S_max = 16 (从 s=16 推断)
S_max = 16

# 通过遍历求解最优 a, b, c
a, b, c, s = dynamic_choose_param(x, y, S_max)

# 计算 p 和 l
p = x / a  # p = x / a
l = y / b  # l = y / b

now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

with open(LOG_PATH, "w", encoding="utf-8") as f:
    f.write("============================================================\n")
    f.write("复用率分析：固定矩阵尺寸下的详细分析\n")
    f.write(f"生成时间: {now}\n")
    f.write("============================================================\n\n")

    f.write("=== 固定矩阵尺寸复用率详细分析 ===\n")
    f.write(f"层参数: M={M}, K={K}, N={N}\n")
    f.write(f"分块参数: x={x}, y={y}, z={z}, a={a}, b={b}, c={c}, s={s}\n")
    f.write(f"p = x/a = {x}/{a} = {p}\n")
    f.write(f"l = y/b = {y}/{b} = {l}\n")
    f.write("\n")

    f.write("在一次OA二级分块的计算过程中：\n")
    f.write(f"1. IA分块能被复用的次数为 a(b-1) = {a}*({b}-1) = {a*(b-1)} 次\n")
    f.write(f"2. W分块能被复用的次数为 b(a-1) = {b}*({a}-1) = {b*(a-1)} 次\n")
    f.write(f"3. 折返时额外可复用的次数 a*c*(l-1) = {a}*{c}*({l}-1) = {a*c*(l-1)} 次\n")
    f.write(f"4. OA二级分块的个数 p*l = {p}*{l} = {p*l} 个\n")
    f.write("\n")

    # 总复用块数公式
    B_reuse = p * l * (a * b * (c + 1) - (a * c + b)) + a * c * (l - 1.0)
    f.write(f"总复用块数 B_reuse = p * l * (a * b * (c + 1) - (a * c + b)) + a * c * (l - 1.0)\n")
    f.write(f"             = {p} * {l} * (2.0 * {a} * {b} - ({a} + {b})) + {a} * {c} * ({l} - 1.0)\n")
    f.write(f"             = {p*l} * (2.0 * {a*b} - {a+b}) + {a*c} * {l-1}\n")
    f.write(f"             = {p*l} * {2.0*a*b - (a+b)} + {a*c*(l-1)}\n")
    f.write(f"             = {p*l * (2.0*a*b - (a+b))} + {a*c*(l-1)}\n")
    f.write(f"             = {B_reuse}\n")
    f.write("\n")

    # 原本的总访存次数
    original_mem_access = 2 * M * K * N
    f.write(f"原本的总访存次数 2*M*K*N = 2*{M}*{K}*{N} = {original_mem_access} 次\n")
    f.write("\n")

    # 总块数
    B_total = 2.0 * x * y * z
    f.write(f"总块数 B_total = 2.0 * x * y * z = 2.0 * {x} * {y} * {z} = {B_total}\n")
    f.write("\n")

    # 复用率
    reuse_ratio = B_reuse / B_total if B_total > 0 else 0
    f.write(f"复用率 = B_reuse / B_total = {B_reuse} / {B_total} = {reuse_ratio:.4f} ({reuse_ratio*100:.2f}%)\n")
    f.write("\n")

    # 访存时间节省
    mem_time_saved = (TILE * TILE / 4.0) * B_reuse
    mem_time_total = (TILE * TILE / 4.0) * B_total
    f.write(f"单块访存耗时 = T^2/4 = {TILE}^2/4 = {TILE*TILE/4} clk\n")
    f.write(f"复用节省的访存时间 = 单块耗时 * B_reuse = {TILE*TILE/4} * {B_reuse} = {mem_time_saved} clk\n")
    f.write(f"总访存时间 = 单块耗时 * B_total = {TILE*TILE/4} * {B_total} = {mem_time_total} clk\n")
    f.write("\n")

    f.write("=== 总结 ===\n")
    f.write(f"通过IA复用，访存块数从 {B_total} 减少到 {B_total - B_reuse}，节省了 {B_reuse} 个块的访存。\n")
    speedup_mem = (B_total / (B_total - B_reuse)) if (B_total - B_reuse) > 0 else float('inf')
    f.write(f"复用率达到 {reuse_ratio*100:.2f}%，加速比为 {speedup_mem:.3f}x（仅考虑访存）。\n")

print(f"[OK] log written to: {LOG_PATH}")