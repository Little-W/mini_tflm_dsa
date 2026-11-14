import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from multiprocessing import Pool

import mem_opt_dynamic_size4 as m

# 中文字体设置
preferred = [
    "Microsoft YaHei", "SimHei", "SimSun",
    "Noto Sans CJK SC", "Noto Sans CJK", "Noto Sans SC",
    "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
    "PingFang SC", "Heiti SC", "Hiragino Sans GB",
    "Source Han Sans SC", "Source Han Sans CN",
    "Arial Unicode MS",
]
available = {f.name for f in fm.fontManager.ttflist}
for name in preferred:
    if name in available:
        plt.rcParams["font.sans-serif"] = [name] + list(plt.rcParams.get("font.sans-serif", []))
        plt.rcParams["axes.unicode_minus"] = False
        break
else:
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

plt.rcParams["font.size"] = 13
plt.rcParams["axes.titlesize"] = 14
plt.rcParams["axes.labelsize"] = 13
plt.rcParams["legend.fontsize"] = 12
plt.rcParams["xtick.labelsize"] = 12
plt.rcParams["ytick.labelsize"] = 12

# Origin风格设置
plt.rcParams['axes.facecolor'] = 'white'
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.edgecolor'] = 'black'
plt.rcParams['axes.linewidth'] = 1.0
plt.rcParams['grid.color'] = 'gray'
plt.rcParams['grid.linestyle'] = '--'
plt.rcParams['grid.linewidth'] = 0.5
plt.rcParams['grid.alpha'] = 0.7

def find_sweet_point_kneedle(T_list, time_list, enforce_monotone=True):
    T = np.array(T_list, dtype=np.float64)
    time = np.array(time_list, dtype=np.float64)

    order = np.argsort(T)
    T, time = T[order], time[order]
    if enforce_monotone:
        time = np.minimum.accumulate(time)

    if T[-1] == T[0]:
        return int(T[0]), 0

    x = (T - T[0]) / (T[-1] - T[0])

    time_min, time_max = float(np.min(time)), float(np.max(time))
    if time_max == time_min:
        return int(T[0]), 0

    y = (time_max - time) / (time_max - time_min)

    g = y - x
    k = int(np.argmax(g))
    return int(T[k]), k

# 固定的 RAM 容量（字节）
RAM_SIZE = 16**2 * 4 * 16

# 扫描的 T 列表（更细步长）
T_LIST = list(range(4, 33, 2))  # 4,6,8,...,32


def mean_total_time(instances, smax):
    total_list = []
    for inst in instances:
        rows, _, _, _, _ = m.simulate_instance(inst, smax)
        for r in rows:
            total_list.append(r["t1"])
    return float(np.mean(total_list)) if total_list else 0.0


def compute_for_T(args):
    T, instances = args
    m.TILE = T
    S_max = RAM_SIZE // ( (T**2) * 4 )
    mc = mean_total_time(instances, S_max)
    return T, S_max, mc


if __name__ == "__main__":
    instances = m.build_instances(seed=m.SEED)

    # 使用多进程并行计算
    with Pool() as pool:
        args_list = [(T, instances) for T in T_LIST]
        results = pool.map(compute_for_T, args_list)

    # 提取结果
    mean_total = [r[2] for r in results]
    S_max_list = [r[1] for r in results]

    # 打印结果
    for T, S_max, mc in results:
        print(f"T={T:>2d} | S_max={S_max:>4d} | mean_t1={mc:.2f} clk")

    # 求膝点
    sweet_T, sweet_idx = find_sweet_point_kneedle(T_LIST, mean_total, enforce_monotone=True)
    sweet_S_max = S_max_list[sweet_idx]
    print(f"\n[SWEET POINT] T={sweet_T} | S_max={sweet_S_max} | idx={sweet_idx} | mean_t1={mean_total[sweet_idx]:.2f} clk")

    # 绘图
    plt.figure(figsize=(8.6, 5.2))
    plt.plot(T_LIST, mean_total, marker="o", color='black', markerfacecolor='white', markersize=6, linewidth=1.5, label='平均优化后时间')
    plt.axvline(sweet_T, linestyle="--", color='red', linewidth=1.5, label='膝点')
    ymin, ymax = min(mean_total), max(mean_total)
    plt.text(
        sweet_T + 1,
        ymin + 0.10 * (ymax - ymin),
        f"膝点 T={sweet_T}\nS_max={sweet_S_max}\n平均时间={mean_total[sweet_idx]:.2f} clk",
        fontsize=11, bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="black", alpha=0.8)
    )
    plt.xlabel("分块尺寸 T")
    plt.ylabel("平均优化后时间 (clk)")
    plt.title(f"固定 RAM 容量 {RAM_SIZE} 字节下不同 T 的整体耗时分析")
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.legend()
    plt.tight_layout()
    plt.savefig("scan_T_total_time.png", dpi=300, bbox_inches='tight')
    plt.show()
