import numpy as np
import math
import matplotlib.pyplot as plt
import time
from mpl_toolkits.mplot3d import Axes3D

# 设置学术绘图风格，类似 Origin
try:
    plt.style.use('seaborn-whitegrid')
except OSError:
    plt.style.use('default')
plt.rcParams['font.family'] = 'sans-serif'  # 使用 sans-serif 以支持中文
plt.rcParams['font.sans-serif'] = ['SimHei']  # 支持中文
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
plt.rcParams['font.size'] = 12
plt.rcParams['axes.labelsize'] = 14
plt.rcParams['axes.titlesize'] = 16
plt.rcParams['xtick.labelsize'] = 12
plt.rcParams['ytick.labelsize'] = 12
plt.rcParams['legend.fontsize'] = 12
plt.rcParams['figure.figsize'] = (8, 6)

TILE = 16

def cbrt_real(x: float) -> float:
    # 实数立方根（避免 Python 对负数开 1/3 次方变复数）
    # 使用 copysign 避免分支，提升性能
    return math.copysign(abs(x)**(1/3), x)

def depressed_cubic_real_roots(p: float, q: float, eps: float=1e-12):
    """解 t^3 + p t + q = 0，返回所有实根"""
    # 预计算常量避免重复计算
    q_half = q * 0.5
    p_third = p / 3.0
    Delta = q_half * q_half + p_third * p_third * p_third
    
    if Delta > eps:
        # 一个实根：避免构造临时变量
        sqrt_delta = math.sqrt(Delta)
        return [cbrt_real(-q_half + sqrt_delta) + cbrt_real(-q_half - sqrt_delta)]
    
    if abs(Delta) <= eps:
        # 重根情形
        u = cbrt_real(-q_half)
        return [2*u, -u]
    
    # 三个实根：优化三角函数计算
    r = math.sqrt(-p_third)
    r_cubed = r * r * r
    # 限制 arg 在 [-1, 1] 范围内，避免浮点误差
    arg = max(-1.0, min(1.0, -q_half / r_cubed))
    phi = math.acos(arg)
    
    # 预计算常量，避免重复计算
    two_r = 2.0 * r
    phi_third = phi / 3.0
    two_pi_third = 2.0943951023931953  # 2*pi/3 预计算
    
    # 直接计算三个根，避免列表推导中的重复计算
    return [
        two_r * math.cos(phi_third),
        two_r * math.cos(phi_third + two_pi_third),
        two_r * math.cos(phi_third + two_pi_third * 2)
    ]

def B_on_abS(x, y, z, S, a):
    """连续情形：ab=S => b=S/a"""
    b = S / a
    p = x / a
    l = y / b
    return p*l*z*(2*a*b-(a+b)) + a*(l-1.0)

def stationary_a_roots(x, y, z, S):
    """解驻点方程：2y a^3 - (xyz+S)a^2 + xyz S = 0，返回所有实根"""
    X = x*y*z
    A = - (X + S) / (2*y)   # a^3 + A a^2 + C = 0
    C = (X * S) / (2*y)

    # a = t - A/3 => t^3 + p t + q = 0
    p = - (A*A)/3
    q = 2*(A**3)/27 + C

    t_roots = depressed_cubic_real_roots(p, q)
    a_roots = [t - A/3 for t in t_roots]

    # 去重
    out = []
    for r in a_roots:
        if all(abs(r-u) > 1e-9 for u in out):
            out.append(r)
    return out

def continuous_opt_abS(x, y, z, S):
    """
    连续优化ab=S下的整数解，考虑计算和访存时间，最大化speedup
    返回最佳整数a, b, speedup, mem_speedup, comp_speedup
    
    流程：
    1. 求解连续域的驻点和边界点
    2. 对这些候选点取整，生成整数候选集合
    3. 对每个整数候选计算实际总时间（max(mem_time, comp_time)）
    4. 选择总时间最小（speedup最大）的候选，相同时优先选择 a 更大的
    """
    # 计算基准时间
    B_total = 2.0 * x * y * z
    mem_t0 = mem_time_from_blocks(B_total, TILE)
    comp_t0 = comp_time_base(x, y, z)
    t0 = max(mem_t0, comp_t0)

    # 求解连续域候选点
    a_min = max(1, int(math.ceil(S / y)))
    a_max = min(int(math.ceil(x)), int(S))
    
    # 边界点直接取整
    cand_integer = set()
    if a_min <= a_max:
        for a in [a_min, a_max]:
            b = min(int(math.ceil(y)), S // a)
            if b >= 1 and a * b <= S:
                cand_integer.add((a, b))
    else:
        # 当 a_min > a_max 时，说明约束很紧，尝试 a=a_max 的边界情况
        a = a_max
        if a >= 1:
            b = min(int(math.ceil(y)), S // a)
            if b >= 1 and a * b <= S:
                cand_integer.add((a, b))
    
    cand_continuous = []
    # 驻点
    for r in stationary_a_roots(x, y, z, S):
        if a_min < r < a_max:
            cand_continuous.append(r)

    # 对驻点连续候选点取整，生成整数候选集合
    for a_cont in cand_continuous:
        # 对驻点a取最接近的整数
        a_closest = round(a_cont)
        if a_min <= a_closest <= a_max:
            b = min(int(y), S // a_closest)
            if b >= 1 and a_closest * b <= S:
                cand_integer.add((a_closest, b))
    
    # 如果没有生成任何候选，添加默认值
    if not cand_integer:
        cand_integer.add((1, 1))

    # 评估每个整数候选的实际总时间，选择时间最小的（speedup最大）
    # 相同speedup时，优先选择 a 更大的方案（更鲁棒）
    best_time = float('inf')
    best_speedup = 0
    best_mem_speedup = 0
    best_comp_speedup = 0
    best_a, best_b = 1, 1

    for a, b in cand_integer:
        B_reuse = ia_reuse_blocks(x, y, z, a, b)
        mem_t1 = mem_time_from_blocks(B_total - B_reuse, TILE)
        comp_save = comp_time_ia_saved(x, y, z, a, b)
        comp_t1 = max(0.0, comp_t0 - comp_save)
        t1 = max(mem_t1, comp_t1)

        if t1 <= 0:
            continue
            
        speedup = t0 / t1
        
        # 选择总时间最小的候选
        # 如果时间更小（speedup更大），直接更新
        if t1 < best_time - 1e-9:
            best_time = t1
            best_speedup = speedup
            best_mem_speedup = (mem_t0 / mem_t1) if mem_t1 > 0 else 0
            best_comp_speedup = (comp_t0 / comp_t1) if comp_t1 > 0 else 0
            best_a, best_b = a, b
        # 如果时间相同（speedup相同），选择 a 更大的（更鲁棒，优化更全面）
        elif abs(t1 - best_time) < 1e-9 and a > best_a:
            best_time = t1
            best_speedup = speedup
            best_mem_speedup = (mem_t0 / mem_t1) if mem_t1 > 0 else 0
            best_comp_speedup = (comp_t0 / comp_t1) if comp_t1 > 0 else 0
            best_a, best_b = a, b

    return best_a, best_b, best_speedup, best_mem_speedup, best_comp_speedup

# ---------- 验证：与密集网格最大值一致 ----------
def dense_grid_max(x, y, z, S, a_min, a_max, n=200000):
    best = (-1e300, None)
    for a in np.linspace(a_min, a_max, n):
        val = B_on_abS(x,y,z,S,a)
        if val > best[0]:
            best = (val, a)
    return best

def ceil_div(a, b):
    return (a + b - 1) // b

def tiles_xyz(M, K, N, T=TILE):
    x = float(ceil_div(M, T))
    y = float(ceil_div(N, T))
    z = float(ceil_div(K, T))
    return x, y, z

def mem_time_from_blocks(B, T=TILE):
    return (T * T / 4.0) * float(B)

def comp_time_base(x, y, z):
    xyz = float(x) * float(y) * float(z)
    return 47.0 * xyz

def ia_reuse_blocks(x, y, z, a, b):
    x = float(x); y = float(y); z = float(z)
    a = float(max(1, a)); b = float(max(1, b))
    p = x / a
    l = y / b
    B_reuse = p * l * z * (2.0 * a * b - (a + b)) + a * (l - 1.0)
    return B_reuse

def comp_time_ia_saved(x, y, z, a, b):
    x = float(x); y = float(y); z = float(z)
    a = float(max(1, a)); b = float(max(1, b))
    p = x / a
    l = y / b
    save_common = p * l * z * ((a - 1.0) * (31.0 * b - 15.0)) + 15.0 * (a - 1.0) * (l - 1.0)
    return save_common


# ==========================================
# 1. 遍历遍历法 (Ground Truth)
# ==========================================
def solve_brute_force(M, K, N, Smax):
    """
    全量遍历WS和IS模式，寻找最优整数解，综合考虑计算和访存时间，取max作为实际时间
    """
    best_speedup = 0
    best_mem_speedup = 0
    best_comp_speedup = 0
    best_abc_mode = (1, 1, 'WS')

    for mode in ['WS', 'IS']:
        if mode == 'WS':
            x, y, z = tiles_xyz(M, K, N, T=TILE)
        else:
            x, y, z = tiles_xyz(N, K, M, T=TILE)

        B_total = 2.0 * x * y * z
        mem_t0 = mem_time_from_blocks(B_total, T=TILE)
        comp_t0 = comp_time_base(x, y, z)
        t0 = max(mem_t0, comp_t0)

        # 参考dynamic_choose_param的遍历方式：遍历b，对每个b计算最大可能的a
        for b in range(1, min(int(math.ceil(y)), int(Smax)) + 1):
            a = min(int(math.ceil(x)), Smax // b)
            if a < 1:
                continue

            # 计算复用块数
            B_reuse = ia_reuse_blocks(x, y, z, a, b)
            mem_t1 = mem_time_from_blocks(B_total - B_reuse, T=TILE)

            # 计算节省
            comp_save = comp_time_ia_saved(x, y, z, a, b)
            comp_t1 = max(0.0, comp_t0 - comp_save)

            t1 = max(mem_t1, comp_t1)
            speedup = (t0 / t1) if t1 > 0 else 0
            mem_speedup = (mem_t0 / mem_t1) if mem_t1 > 0 else 0
            comp_speedup = (comp_t0 / comp_t1) if comp_t1 > 0 else 0

            # 优先选择speedup更大的
            if speedup > best_speedup + 1e-9:
                best_speedup = speedup
                best_mem_speedup = mem_speedup
                best_comp_speedup = comp_speedup
                best_abc_mode = (a, b, mode)
            # speedup相同时，优先选择 a 更大的（更鲁棒，计算优化更全面）
            elif abs(speedup - best_speedup) < 1e-9:
                if a > best_abc_mode[0]:
                    best_speedup = speedup
                    best_mem_speedup = mem_speedup
                    best_comp_speedup = comp_speedup
                    best_abc_mode = (a, b, mode)
                # a 也相同时，优先选择 b 更大的
                elif a == best_abc_mode[0] and b > best_abc_mode[1]:
                    best_speedup = speedup
                    best_mem_speedup = mem_speedup
                    best_comp_speedup = comp_speedup
                    best_abc_mode = (a, b, mode)
                # a 和 b 也相同时，优先选择 WS 模式
                elif a == best_abc_mode[0] and b == best_abc_mode[1] and mode == 'WS' and best_abc_mode[2] == 'IS':
                    best_speedup = speedup
                    best_mem_speedup = mem_speedup
                    best_comp_speedup = comp_speedup
                    best_abc_mode = (a, b, mode)

    return best_speedup, best_mem_speedup, best_comp_speedup, best_abc_mode


# ==========================================
# 2. 公式贪心法 (O(1) Approximation)
# ==========================================

def solve_formula_greedy(M, K, N, Smax):
    """
    O(1): 比较WS和IS两种模式，选择最佳的整数解
    优先级：speedup > a的大小 > WS模式
    """
    best_speedup = 0
    best_mem_speedup = 0
    best_comp_speedup = 0
    best_params = (1, 1)
    best_mode = 'WS'

    for mode in ['WS', 'IS']:
        if mode == 'WS':
            x, y, z = tiles_xyz(M, K, N, TILE)
        else:
            x, y, z = tiles_xyz(N, K, M, TILE)

        a, b, speedup, mem_speedup, comp_speedup = continuous_opt_abS(x, y, z, Smax)

        # 优先选择speedup更大的
        if speedup > best_speedup + 1e-9:
            best_speedup = speedup
            best_mem_speedup = mem_speedup
            best_comp_speedup = comp_speedup
            best_params = (a, b)
            best_mode = mode
        # speedup相同时，优先选择 a 更大的（更鲁棒）
        elif abs(speedup - best_speedup) < 1e-9:
            if a > best_params[0]:
                best_speedup = speedup
                best_mem_speedup = mem_speedup
                best_comp_speedup = comp_speedup
                best_params = (a, b)
                best_mode = mode
            # a 也相同时，优先选择 WS 模式
            elif a == best_params[0] and mode == 'WS' and best_mode == 'IS':
                best_speedup = speedup
                best_mem_speedup = mem_speedup
                best_comp_speedup = comp_speedup
                best_params = (a, b)
            best_mode = mode

    return best_speedup, best_mem_speedup, best_comp_speedup, best_params, 'Formula', best_mode

# ==========================================
# 参数设置
# ==========================================
S = 16
size = 8000
step = 50  # 使用步长减少计算量
k_range = np.arange(1, size + 1, step)
m_range = np.arange(1, size + 1, step)
n_range = np.arange(1, size + 1, step)

total_points = len(k_range) * len(m_range) * len(n_range)

print(f"正在计算对比... 总点数: {total_points}")

# 打开日志文件
log_file = open('comparison_log.txt', 'w', encoding='utf-8')
diff_log_file = open('diff_speedup_log.txt', 'w', encoding='utf-8')
# 写入表头（对齐格式）
header = f"{'K':>5} {'M':>5} {'N':>5} | {'SpeedupBF':>10} {'SpeedupFM':>10} {'Diff':>10} | {'MemBF':>10} {'MemFM':>10} {'MemDiff':>10} | {'CompBF':>10} {'CompFM':>10} {'CompDiff':>10} | {'aBF':>4} {'bBF':>4} {'ModeBF':>6} | {'aFM':>4} {'bFM':>4} {'ModeFM':>6}\n"
log_file.write(header)
log_file.write("-" * len(header) + "\n")
# 差异日志表头
diff_header = f"{'K':>5} {'M':>5} {'N':>5} {'SpeedupBF':>10} {'SpeedupFM':>10} {'Diff':>10} {'aBF':>4} {'bBF':>4} {'ModeBF':>6} {'aFM':>4} {'bFM':>4} {'ModeFM':>6}\n"
diff_log_file.write(diff_header)
diff_log_file.write("-" * len(diff_header) + "\n")

# 执行三维空间对比
diffs = []
a_diffs = []
mem_diffs = []
comp_diffs = []
ms = []
ks = []
ns = []
speedups_bf_list = []
mode_match_count = 0  # mode 匹配次数
mem_comp_diff_count = 0  # 总speedup相同但访存/计算speedup不同的点数
total_time_bf = 0.0  # 遍历法总时间
total_time_fm = 0.0  # 公式法总时间

for k in k_range:
    for m in m_range:
        for n in n_range:
            # 1. 运行遍历求解 (M=m, K=k, N=n)
            start_bf = time.time()
            speedup_bf, mem_speedup_bf, comp_speedup_bf, (a_bf, b_bf, mode_bf) = solve_brute_force(m, k, n, S)
            end_bf = time.time()
            time_bf = end_bf - start_bf
            total_time_bf += time_bf

            # 2. 运行公式求解
            start_fm = time.time()
            speedup_fm, mem_speedup_fm, comp_speedup_fm, (a_fm, b_fm), strategy_fm, mode_fm = solve_formula_greedy(m, k, n, S)
            end_fm = time.time()
            time_fm = end_fm - start_fm
            total_time_fm += time_fm

            # 统计 mode 匹配
            if mode_bf == mode_fm:
                mode_match_count += 1

            # 记录差异
            diff = speedup_bf - speedup_fm
            if abs(diff) < 1e-9: diff = 0

            mem_diff = mem_speedup_bf - mem_speedup_fm
            if abs(mem_diff) < 1e-9: mem_diff = 0

            comp_diff = comp_speedup_bf - comp_speedup_fm
            if abs(comp_diff) < 1e-9: comp_diff = 0

            # 如果 speedup 有差异，写入差异日志
            if abs(diff) > 0.01:
                diff_log_file.write(f"{k:>5d} {m:>5d} {n:>5d} {speedup_bf:>10.4f} {speedup_fm:>10.4f} {diff:>10.6f} {a_bf:>4d} {b_bf:>4d} {mode_bf:>6s} {a_fm:>4d} {b_fm:>4d} {mode_fm:>6s}\n")

            diffs.append(diff)
            mem_diffs.append(mem_diff)
            comp_diffs.append(comp_diff)
            a_diffs.append(a_bf - a_fm)
            ms.append(m)
            ks.append(k)
            ns.append(n)
            speedups_bf_list.append(speedup_bf)
            
            # 写入日志文件（所有点，格式化对齐）
            log_line = f"{k:>5d} {m:>5d} {n:>5d} | {speedup_bf:>10.4f} {speedup_fm:>10.4f} {diff:>10.6f} | {mem_speedup_bf:>10.4f} {mem_speedup_fm:>10.4f} {mem_diff:>10.6f} | {comp_speedup_bf:>10.4f} {comp_speedup_fm:>10.4f} {comp_diff:>10.6f} | {a_bf:>4d} {b_bf:>4d} {mode_bf:>6s} | {a_fm:>4d} {b_fm:>4d} {mode_fm:>6s}\n"
            log_file.write(log_line)

# 关闭日志文件
log_file.close()
diff_log_file.close()
print(f"\n所有对比数据已保存到 comparison_log.txt")
print(f"speedup差异点已保存到 diff_speedup_log.txt")

# mode 匹配统计
mode_match_rate = (mode_match_count / total_points) * 100 if total_points > 0 else 0
print(f"\nMode 匹配率: {mode_match_count} / {total_points} ({mode_match_rate:.2f}%)")

# 加速比差异统计
print("\n=== 加速比差异统计 ===")
diffs_array = np.array(diffs)
non_zero_diff = np.count_nonzero(diffs_array)
print(f"总 speedup 有差异的点数: {non_zero_diff} / {total_points} ({100 * non_zero_diff / total_points:.2f}%)")
if non_zero_diff > 0:
    mean_diff = np.mean(np.abs(diffs_array))
    max_diff = np.max(np.abs(diffs_array))
    print(f"平均 |总 speedup 差异|: {mean_diff:.4f}")
    print(f"最大 |总 speedup 差异|: {max_diff:.4f}")

# 计算时间对比统计
print("\n=== 计算时间对比统计 ===")
avg_time_bf = total_time_bf / total_points if total_points > 0 else 0
avg_time_fm = total_time_fm / total_points if total_points > 0 else 0
time_ratio = avg_time_bf / avg_time_fm if avg_time_fm > 0 else float('inf')
print(f"遍历法总时间: {total_time_bf:.4f} 秒")
print(f"公式法总时间: {total_time_fm:.4f} 秒")
print(f"遍历法平均时间: {avg_time_bf:.6f} 秒/点")
print(f"公式法平均时间: {avg_time_fm:.6f} 秒/点")
print(f"时间比 (遍历/公式): {time_ratio:.2f}")

# 绘制差异分布图
print("\n正在绘制差异分布图...")
plt.figure(figsize=(15,5))
plt.subplot(1,3,1)
plt.scatter(ms, diffs, s=0.1, alpha=0.5)
plt.xlabel('M')
plt.ylabel('Diff')
plt.title('Diff vs M')
plt.subplot(1,3,2)
plt.scatter(ks, diffs, s=0.1, alpha=0.5)
plt.xlabel('K')
plt.ylabel('Diff')
plt.title('Diff vs K')
plt.subplot(1,3,3)
plt.scatter(ns, diffs, s=0.1, alpha=0.5)
plt.xlabel('N')
plt.ylabel('Diff')
plt.title('Diff vs N')
plt.tight_layout()
plt.savefig('diff_distribution.png', dpi=150)
plt.show()

# 三维加速比分布图 (仅包含M, N, Speedup)
print("正在绘制三维加速比分布图...")
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
# 采样以减少点数，避免matplotlib崩溃
sample_step = 1000  # 每1000个点取一个
indices = range(0, len(ms), sample_step)
ax.scatter([ms[i] for i in indices], [ns[i] for i in indices], [speedups_bf_list[i] for i in indices], s=1)
ax.set_xlabel('M')
ax.set_ylabel('N')
ax.set_zlabel('Speedup BF')
plt.savefig('3d_speedup_xy.png', dpi=150)
plt.show()