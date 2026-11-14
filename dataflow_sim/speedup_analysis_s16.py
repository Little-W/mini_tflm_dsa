import math
import random
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from mem_opt_dynamic_size4 import (
    setup_chinese_font,
    _layer,
    gen_mobilenet_like,
    gen_shufflenet_like,
    gen_ghostnet_like,
    gen_convmlp_like,
    gen_mlp_mixer_like,
    MODEL_GENS,
    build_instances,
    ceil_div,
    tiles_xyz,
    dynamic_choose_param,
    ia_reuse_blocks,
    ram_utilization_smax,
    mem_time_from_blocks,
    comp_time_base,
    comp_time_ia_saved,
    simulate_layer,
    simulate_instance,
    speedup_test,
    fmt_params,
    TILE,
    SIZES,
    INSTANCES_PER_SIZE,
    SEED,
    TEST_SEED,
    TEST_SAMPLE_N,
    TEST_WORST_K,
    TEST_BEST_K
)

# ============================================================
# 1) 全局设置（脚本特定）
# ============================================================
# 固定 S_max = 16
S_MAX = 16

# 是否输出所有层详细日志（层数很多，会生成较大 log）
LOG_FULL_LAYERS = True
LOG_TOPK_LAYERS = 25  # LOG_FULL_LAYERS=False 时每实例只打印TopK（按t0降序）

LOG_PATH = "speedup_analysis_s16_log.txt"

# 中文字体设置
setup_chinese_font()
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

# ============================================================
# 4) 加速比分布分析
# ============================================================
def analyze_speedup_distribution(all_rows):
    speedups = [r["speedup"] for (_, _, r) in all_rows]
    speedups = np.array(speedups)
    
    # 基本统计
    mean_sp = np.mean(speedups)
    median_sp = np.median(speedups)
    std_sp = np.std(speedups)
    min_sp = np.min(speedups)
    max_sp = np.max(speedups)
    
    # 百分位数
    percentiles = [10, 25, 50, 75, 90, 95, 99]
    perc_values = np.percentile(speedups, percentiles)
    
    # 分布区间
    bins = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, float('inf')]
    hist, bin_edges = np.histogram(speedups, bins=bins)
    
    return {
        "mean": mean_sp,
        "median": median_sp,
        "std": std_sp,
        "min": min_sp,
        "max": max_sp,
        "percentiles": dict(zip(percentiles, perc_values)),
        "histogram": dict(zip([f"{bins[i]:.0f}-{bins[i+1]:.0f}" if bins[i+1] != float('inf') else f"{bins[i]:.0f}+" for i in range(len(bins)-1)], hist)),
        "speedups": speedups  # 添加原始数据用于绘图
    }

# ============================================================
# 4.1) 时间分布分析
# ============================================================
def analyze_time_distributions(all_rows):
    comp_t0s = [r["comp_t0"] for (_, _, r) in all_rows]
    comp_t1s = [r["comp_t1"] for (_, _, r) in all_rows]
    mem_t0s = [r["mem_t0"] for (_, _, r) in all_rows]
    mem_t1s = [r["mem_t1"] for (_, _, r) in all_rows]
    
    comp_t0s = np.array(comp_t0s)
    comp_t1s = np.array(comp_t1s)
    mem_t0s = np.array(mem_t0s)
    mem_t1s = np.array(mem_t1s)
    
    # 检查comp_t0 == comp_t1的层数
    equal_count = np.sum(comp_t0s == comp_t1s)
    total_count = len(comp_t0s)
    equal_ratio = equal_count / total_count if total_count > 0 else 0
    
    # 计算comp_save = comp_t0 - comp_t1 (如果comp_t1 < comp_t0)
    comp_saves = np.maximum(0, comp_t0s - comp_t1s)
    mean_save = np.mean(comp_saves)
    
    def compute_stats(times):
        return {
            "mean": np.mean(times),
            "median": np.median(times),
            "std": np.std(times),
            "min": np.min(times),
            "max": np.max(times),
            "data": times
        }
    
    return {
        "comp_t0": compute_stats(comp_t0s),
        "comp_t1": compute_stats(comp_t1s),
        "mem_t0": compute_stats(mem_t0s),
        "mem_t1": compute_stats(mem_t1s),
        "equal_count": equal_count,
        "equal_ratio": equal_ratio,
        "mean_comp_save": mean_save
    }

# ============================================================
# 4.2) 时间比例分析
# ============================================================
def analyze_time_ratios(all_rows):
    ratios = []
    mem_dominant = 0
    comp_dominant = 0
    
    for _, _, r in all_rows:
        mem_t1 = r["mem_t1"]
        comp_t1 = r["comp_t1"]
        if comp_t1 > 0:
            ratio = mem_t1 / comp_t1
            ratios.append(ratio)
            if ratio > 1:
                mem_dominant += 1
            else:
                comp_dominant += 1
    
    ratios = np.array(ratios)
    
    return {
        "ratios": ratios,
        "mem_dominant_count": mem_dominant,
        "comp_dominant_count": comp_dominant,
        "total": len(ratios),
        "mem_dominant_ratio": mem_dominant / len(ratios) if len(ratios) > 0 else 0,
        "comp_dominant_ratio": comp_dominant / len(ratios) if len(ratios) > 0 else 0
    }

# ============================================================
# 4.3) 参数分布分析
# ============================================================
def analyze_param_distributions(all_rows):
    as_ = [r["a"] for (_, _, r) in all_rows]
    bs = [r["b"] for (_, _, r) in all_rows]
    ss = [r["s"] for (_, _, r) in all_rows]
    modes = [r["mode"] for (_, _, r) in all_rows]
    
    as_ = np.array(as_)
    bs = np.array(bs)
    ss = np.array(ss)
    
    # 统计a=1, b=1的层数
    a1_count = np.sum(as_ == 1)
    b1_count = np.sum(bs == 1)
    both1_count = np.sum((as_ == 1) & (bs == 1))
    
    # 统计mode
    ws_count = modes.count('WS')
    is_count = modes.count('IS')
    
    return {
        "a_stats": {"mean": np.mean(as_), "min": np.min(as_), "max": np.max(as_), "a1_count": a1_count},
        "b_stats": {"mean": np.mean(bs), "min": np.min(bs), "max": np.max(bs), "b1_count": b1_count},
        "s_stats": {"mean": np.mean(ss), "min": np.min(ss), "max": np.max(ss)},
        "mode_stats": {"ws_count": ws_count, "is_count": is_count, "ws_ratio": ws_count / len(modes), "is_ratio": is_count / len(modes)},
        "both1_count": both1_count,
        "total": len(as_)
    }

# ============================================================
# 4.5) 绘制分布图像
# ============================================================
def plot_speedup_distribution(analysis, save_prefix=None):
    speedups = analysis["speedups"]
    
    plt.figure(figsize=(10, 6))
    plt.hist(speedups, bins=50, color='lightgray', edgecolor='black', alpha=0.8)
    plt.axvline(analysis["mean"], color='red', linestyle='--', linewidth=1.5, label=f'平均加速比: {analysis["mean"]:.3f}x')
    plt.axvline(analysis["median"], color='blue', linestyle='--', linewidth=1.5, label=f'中位数加速比: {analysis["median"]:.3f}x')
    plt.xlabel('加速比')
    plt.ylabel('层数')
    plt.title('固定 S_max=16 下加速比分布分析')
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.tight_layout()
    if save_prefix:
        plt.savefig(f"{save_prefix}_speedup_distribution.png", dpi=300, bbox_inches='tight')
    # plt.show()  # 移除显示，防止阻塞

# ============================================================
# 4.6) 绘制时间分布图像
# ============================================================
def plot_time_distributions(time_analysis, save_prefix=None):
    labels = ['comp_t0', 'comp_t1', 'mem_t0', 'mem_t1']
    titles = ['原始计算时间', '优化后计算时间', '原始访存时间', '优化后访存时间']
    
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes = axes.flatten()
    
    for i, (label, title) in enumerate(zip(labels, titles)):
        data = time_analysis[label]["data"]
        mean_val = time_analysis[label]["mean"]
        median_val = time_analysis[label]["median"]
        
        axes[i].hist(data, bins=50, color='lightgray', edgecolor='black', alpha=0.8)
        axes[i].axvline(mean_val, color='red', linestyle='--', linewidth=1.5, label=f'平均: {mean_val:.2f}')
        axes[i].axvline(median_val, color='blue', linestyle='--', linewidth=1.5, label=f'中位数: {median_val:.2f}')
        axes[i].set_xlabel('时间 (clk)')
        axes[i].set_ylabel('层数')
        axes[i].set_title(f'{title}分布 (S_max=16)')
        axes[i].legend()
        axes[i].grid(True, linestyle="--", alpha=0.7)
    
    plt.tight_layout()
    if save_prefix:
        plt.savefig(f"{save_prefix}_time_distributions.png", dpi=300, bbox_inches='tight')
    # plt.show()  # 移除显示，防止阻塞

# ============================================================
# 4.7) 绘制时间比例分布图像
# ============================================================
def plot_time_ratios(ratio_analysis, save_prefix=None):
    ratios = ratio_analysis["ratios"]
    
    plt.figure(figsize=(10, 6))
    plt.hist(ratios, bins=50, color='lightgray', edgecolor='black', alpha=0.8)
    plt.axvline(1.0, color='red', linestyle='--', linewidth=1.5, label='比例=1 (平衡点)')
    plt.xlabel('优化后访存时间 / 计算时间')
    plt.ylabel('层数')
    plt.title('固定 S_max=16 下优化后访存与计算时间比例分布')
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.tight_layout()
    if save_prefix:
        plt.savefig(f"{save_prefix}_time_ratios.png", dpi=300, bbox_inches='tight')
    # plt.show()  # 移除显示，防止阻塞

# ============================================================
# 5) 写 log
# ============================================================
def write_analysis_log(filepath, instances, Smax, test_pack, analysis, param_analysis):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("============================================================\n")
        f.write("加速比分布分析：固定 S_max = 16\n")
        f.write(f"生成时间: {now}\n")
        f.write("------------------------------------------------------------\n")
        f.write(f"TILE(T)={TILE} | block_time=T^2/4={TILE*TILE/4:.1f} clk\n")
        f.write(f"SIZES={min(SIZES)}..{max(SIZES)} (count={len(SIZES)}) | INSTANCES_PER_SIZE={INSTANCES_PER_SIZE} | SEED={SEED}\n")
        f.write(f"S_MAX={Smax}\n")
        f.write(f"total_instances={len(instances)}\n")
        f.write("============================================================\n\n")

        # 分布统计
        f.write("[1] 加速比分布统计\n")
        f.write(f"平均加速比: {analysis['mean']:.3f}x\n")
        f.write(f"中位数加速比: {analysis['median']:.3f}x\n")
        f.write(f"标准差: {analysis['std']:.3f}\n")
        f.write(f"最小加速比: {analysis['min']:.3f}x\n")
        f.write(f"最大加速比: {analysis['max']:.3f}x\n")
        f.write("百分位数:\n")
        for p, v in analysis['percentiles'].items():
            f.write(f"  {p}th: {v:.3f}x\n")
        f.write("直方图分布:\n")
        for bin_range, count in analysis['histogram'].items():
            f.write(f"  {bin_range}: {count}\n")
        f.write("\n")

        header = (
            f"{'No.':>3}  {'Model':<10}  "
            f"{'M':>7} {'K':>7} {'N':>7}  "
            f"{'x':>4} {'y':>4} {'z':>4}  "
            f"{'a':>3} {'b':>3} {'s':>4}  "
            f"{'reuse%':>7}  {'util':>6}  {'speedup':>8} {'mode':>4}\n"
        )
        sep = "-" * (len(header) - 1) + "\n"

        def dump_rows(title, rows):
            f.write(title + "\n")
            f.write(header)
            f.write(sep)
            for j, (inst_id, li, r) in enumerate(rows):
                inst = instances[inst_id]
                f.write(
                    f"{j:>3}  {inst['model']:<10}  "
                    f"{r['M']:>7d} {r['K']:>7d} {r['N']:>7d}  "
                    f"{int(r['x']):>4d} {int(r['y']):>4d} {int(r['z']):>4d}  "
                    f"{r['a']:>3d} {r['b']:>3d} {r['s']:>4d}  "
                    f"{r['reuse_ratio']*100:>6.1f}%  "
                    f"{r['util']:>6.3f}  "
                    f"{r['speedup']:>7.3f}x {r['mode']:>4}\n"
                )
            f.write("\n")

        dump_rows("[2.1] sample_sorted_by_speedup", test_pack["sample_sorted"])
        dump_rows(f"[2.2] worst_{TEST_WORST_K}", test_pack["worst"])
        dump_rows(f"[2.3] best_{TEST_BEST_K}", test_pack["best"])

        # 逐实例逐层日志
        f.write("[3] per-instance per-layer logs\n")
        f.write(f"LOG_FULL_LAYERS={LOG_FULL_LAYERS} | if False -> Top-{LOG_TOPK_LAYERS} by t0\n\n")

        layer_header = (
            f"{'L#':>3}  "
            f"{'M':>7} {'K':>7} {'N':>7}  "
            f"{'x':>4} {'y':>4} {'z':>4}  "
            f"{'a':>3} {'b':>3} {'s':>4}  "
            f"{'reuse%':>7}  {'util':>6}  {'speedup':>8} {'mode':>4}\n"
        )
        layer_sep = "-" * (len(layer_header) - 1) + "\n"

        for inst_id, inst in enumerate(instances):
            rows, t0_sum, t1_sum, sp, reuse_avg = simulate_instance(inst, Smax)
            f.write(f"=== Instance {inst_id:06d} ===\n")
            f.write(f"model:  {inst['model']}\n")
            f.write(f"params: {fmt_params(inst['params'])}\n")
            f.write(f"Smax={Smax} | layers={len(rows)} | instance_speedup={sp:.3f}x | mean_layer_reuse={reuse_avg*100:.2f}%\n")

            f.write(layer_header)
            f.write(layer_sep)

            if (not LOG_FULL_LAYERS) and len(rows) > LOG_TOPK_LAYERS:
                order = np.argsort([-r["t0"] for r in rows])[:LOG_TOPK_LAYERS]
                rows_to_dump = [rows[i] for i in order]
            else:
                rows_to_dump = rows

            for li, r in enumerate(rows_to_dump):
                f.write(
                    f"{li:>3}  "
                    f"{r['M']:>7d} {r['K']:>7d} {r['N']:>7d}  "
                    f"{int(r['x']):>4d} {int(r['y']):>4d} {int(r['z']):>4d}  "
                    f"{r['a']:>3d} {r['b']:>3d} {r['s']:>4d}  "
                    f"{r['reuse_ratio']*100:>6.1f}%  "
                    f"{r['util']:>6.3f}  "
                    f"{r['speedup']:>7.3f}x {r['mode']:>4}\n"
                )
            f.write("\n")
        # 参数分布
        f.write("[4] 参数分布统计\n")
        f.write(f"a: 平均={param_analysis['a_stats']['mean']:.2f}, 最小={param_analysis['a_stats']['min']}, 最大={param_analysis['a_stats']['max']}, a=1的层数={param_analysis['a_stats']['a1_count']} ({param_analysis['a_stats']['a1_count']/param_analysis['total']*100:.1f}%)\n")
        f.write(f"b: 平均={param_analysis['b_stats']['mean']:.2f}, 最小={param_analysis['b_stats']['min']}, 最大={param_analysis['b_stats']['max']}, b=1的层数={param_analysis['b_stats']['b1_count']} ({param_analysis['b_stats']['b1_count']/param_analysis['total']*100:.1f}%)\n")
        f.write(f"s: 平均={param_analysis['s_stats']['mean']:.2f}, 最小={param_analysis['s_stats']['min']}, 最大={param_analysis['s_stats']['max']}\n")
        f.write(f"mode: WS层数={param_analysis['mode_stats']['ws_count']} ({param_analysis['mode_stats']['ws_ratio']*100:.1f}%), IS层数={param_analysis['mode_stats']['is_count']} ({param_analysis['mode_stats']['is_ratio']*100:.1f}%)\n")
        f.write(f"a=1且b=1的层数: {param_analysis['both1_count']} ({param_analysis['both1_count']/param_analysis['total']*100:.1f}%)\n")
        f.write("\n")
    return filepath

# ============================================================
# 6) main
# ============================================================
if __name__ == "__main__":
    instances = build_instances(seed=SEED)

    test_pack = speedup_test(instances, S_MAX, seed=TEST_SEED)
    analysis = analyze_speedup_distribution(test_pack["all_rows"])
    time_analysis = analyze_time_distributions(test_pack["all_rows"])
    ratio_analysis = analyze_time_ratios(test_pack["all_rows"])
    param_analysis = analyze_param_distributions(test_pack["all_rows"])
    
    write_analysis_log(LOG_PATH, instances, S_MAX, test_pack, analysis, param_analysis)
    print(f"[OK] log written to: {LOG_PATH}")
    
    # 打印到控制台的简要统计
    print("\n加速比分布分析 (S_max=16):")
    print(f"平均加速比: {analysis['mean']:.3f}x")
    print(f"中位数加速比: {analysis['median']:.3f}x")
    print(f"标准差: {analysis['std']:.3f}")
    print(f"最小/最大: {analysis['min']:.3f}x / {analysis['max']:.3f}x")
    print("百分位数:")
    for p, v in analysis['percentiles'].items():
        print(f"  {p}th: {v:.3f}x")
    print("直方图分布:")
    for bin_range, count in analysis['histogram'].items():
        print(f"  {bin_range}: {count}")
    
    # 时间比例统计
    print("\n优化后时间比例分析 (mem_t1 / comp_t1):")
    print(f"访存主导层数: {ratio_analysis['mem_dominant_count']} ({ratio_analysis['mem_dominant_ratio']*100:.1f}%)")
    print(f"计算主导层数: {ratio_analysis['comp_dominant_count']} ({ratio_analysis['comp_dominant_ratio']*100:.1f}%)")
    print(f"总层数: {ratio_analysis['total']}")
    
    # 计算时间检查
    print("\n计算时间检查:")
    print(f"comp_t0 == comp_t1 的层数: {time_analysis['equal_count']} ({time_analysis['equal_ratio']*100:.1f}%)")
    print(f"平均计算节省时间 (comp_save): {time_analysis['mean_comp_save']:.2f} clk")
    
    # 参数分布检查
    print("\n参数分布检查:")
    print(f"a: 平均={param_analysis['a_stats']['mean']:.2f}, 最小={param_analysis['a_stats']['min']}, 最大={param_analysis['a_stats']['max']}, a=1的层数={param_analysis['a_stats']['a1_count']} ({param_analysis['a_stats']['a1_count']/param_analysis['total']*100:.1f}%)")
    print(f"b: 平均={param_analysis['b_stats']['mean']:.2f}, 最小={param_analysis['b_stats']['min']}, 最大={param_analysis['b_stats']['max']}, b=1的层数={param_analysis['b_stats']['b1_count']} ({param_analysis['b_stats']['b1_count']/param_analysis['total']*100:.1f}%)")
    print(f"s: 平均={param_analysis['s_stats']['mean']:.2f}, 最小={param_analysis['s_stats']['min']}, 最大={param_analysis['s_stats']['max']}")
    print(f"mode: WS层数={param_analysis['mode_stats']['ws_count']} ({param_analysis['mode_stats']['ws_ratio']*100:.1f}%), IS层数={param_analysis['mode_stats']['is_count']} ({param_analysis['mode_stats']['is_ratio']*100:.1f}%)")
    print(f"a=1且b=1的层数: {param_analysis['both1_count']} ({param_analysis['both1_count']/param_analysis['total']*100:.1f}%)")
    plot_speedup_distribution(analysis, save_prefix="speedup_s16")
    plot_time_distributions(time_analysis, save_prefix="speedup_s16")
    plot_time_ratios(ratio_analysis, save_prefix="speedup_s16")