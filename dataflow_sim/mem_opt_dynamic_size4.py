import math
import random
import numpy as np
from datetime import datetime
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


# ================================================= ============================================================
# 0) 中文字体（可选，但建议）
# ============================================================
def setup_chinese_font():
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
            return name
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return None


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
# 1) 全局设置
# ============================================================
TILE = 16  # 分块尺寸 T（单边）；单块访存耗时 = T^2/4 clk；T=16 -> 64clk

SIZES = list(range(32, 513, 8)) + [28, 36, 44, 52, 60, 68, 76, 84, 92, 100]
SIZES = sorted(set(SIZES))

INSTANCES_PER_SIZE = 64
SEED = 42

# 只优化 Smax（ab 动态调度）
S_MAX_LIST = [4, 8, 16, 32, 64, 96, 128, 192, 256, 384, 512, 768, 1024]

# 是否输出所有层详细日志（层数很多，会生成较大 log）
LOG_FULL_LAYERS = True
LOG_TOPK_LAYERS = 25  # LOG_FULL_LAYERS=False 时每实例只打印TopK（按t0降序）

# 加速比测试（sweet Smax）
TEST_SEED = 2026
TEST_SAMPLE_N = 120
TEST_WORST_K = 12
TEST_BEST_K = 12

# 规模分组（用于不同模型规模加速比展示）
SCALE_BIN_LABELS = ["Small", "Medium", "Large"]

LOG_PATH = "matrix_speedup_log.txt"


# ============================================================
# 2) 模型工作负载生成（层 = dict(op,M,K,N)）
# ============================================================
def _layer(op, M, K, N):
    return {"op": op, "M": int(M), "K": int(K), "N": int(N)}


def gen_mobilenet_like(H, W, width_mult=1.0):
    base = [32, 16, 24, 32, 64, 96, 160, 320, 1280]
    ch = [max(8, int(round(c * width_mult / 8)) * 8) for c in base]

    layers = []
    H1, W1 = max(1, H // 2), max(1, W // 2)
    layers.append(_layer("Conv3x3_im2col(stem)", H1 * W1, 3 * 3 * 3, ch[0]))

    res = [
        (H1, W1, ch[0], ch[1], 1),
        (max(1, H1 // 2),  max(1, W1 // 2),  ch[1], ch[2], 2),
        (max(1, H1 // 4),  max(1, W1 // 4),  ch[2], ch[3], 3),
        (max(1, H1 // 8),  max(1, W1 // 8),  ch[3], ch[4], 4),
        (max(1, H1 // 16), max(1, W1 // 16), ch[4], ch[6], 3),
    ]

    t = 6
    for hh, ww, cin, cout, repeats in res:
        c = cin
        for _ in range(repeats):
            layers.append(_layer("PW_expand",  hh * ww, c,   t * c))
            layers.append(_layer("PW_project", hh * ww, t * c, cout))
            c = cout

    hh, ww = max(1, H1 // 16), max(1, W1 // 16)
    layers.append(_layer("PW_head", hh * ww, ch[6], ch[8]))
    layers.append(_layer("FC", 1, ch[8], 1000))
    return layers


def gen_shufflenet_like(H, W, width_mult=1.0, groups=2):
    layers = []
    c1 = max(8, int(round(24 * width_mult / 8)) * 8)
    H1, W1 = max(1, H // 2), max(1, W // 2)
    layers.append(_layer("Conv3x3_im2col(stem)", H1 * W1, 3 * 3 * 3, c1))

    stage_out = [max(8, int(round(c * width_mult / 8)) * 8) for c in [240, 480, 960]]
    stage_res = [(max(1, H1 // 2), max(1, W1 // 2)),
                 (max(1, H1 // 4), max(1, W1 // 4)),
                 (max(1, H1 // 8), max(1, W1 // 8))]

    cin = c1
    for (hh, ww), cout in zip(stage_res, stage_out):
        repeats = 4
        c = cin
        for _ in range(repeats):
            layers.append(_layer("PW_1x1", hh * ww, c, cout // 2))
            layers.append(_layer(f"GroupConv3x3_im2col(g={groups})", hh * ww, (c // groups) * 9, cout // 2))
            layers.append(_layer("PW_1x1", hh * ww, cout // 2, cout))
            c = cout
        cin = cout

    hh, ww = stage_res[-1]
    layers.append(_layer("PW_head", hh * ww, cin, 1024))
    layers.append(_layer("FC", 1, 1024, 1000))
    return layers


def gen_ghostnet_like(H, W, width_mult=1.0):
    layers = []
    c1 = max(8, int(round(16 * width_mult / 8)) * 8)
    H1, W1 = max(1, H // 2), max(1, W // 2)
    layers.append(_layer("Conv3x3_im2col(stem)", H1 * W1, 3 * 3 * 3, c1))

    stage_ch = [max(8, int(round(c * width_mult / 8)) * 8) for c in [16, 24, 40, 80, 112, 160]]
    stage_res = [(H1, W1),
                 (max(1, H1 // 2), max(1, W1 // 2)),
                 (max(1, H1 // 4), max(1, W1 // 4)),
                 (max(1, H1 // 8), max(1, W1 // 8)),
                 (max(1, H1 // 8), max(1, W1 // 8)),
                 (max(1, H1 // 16), max(1, W1 // 16))]

    cin = c1
    for (hh, ww), cout in zip(stage_res, stage_ch):
        repeats = 2
        c = cin
        for _ in range(repeats):
            layers.append(_layer("PW_1x1", hh * ww, c, cout))
            layers.append(_layer("PW_cheap", hh * ww, cout, cout))  # 近似
            c = cout
        cin = cout

    hh, ww = stage_res[-1]
    layers.append(_layer("PW_head", hh * ww, cin, 960))
    layers.append(_layer("FC", 1, 960, 1000))
    return layers


def gen_convmlp_like(H, W, patch=4, dim=256, depth=8, mlp_ratio=4):
    hp, wp = max(1, H // patch), max(1, W // patch)
    layers = [_layer(f"PatchEmbed_im2col(p={patch})", hp * wp, 3 * patch * patch, dim)]
    for _ in range(depth):
        layers.append(_layer("TokenMix(PW_approx)", hp * wp, dim, dim))
        layers.append(_layer("MLP_fc1", hp * wp, dim, dim * mlp_ratio))
        layers.append(_layer("MLP_fc2", hp * wp, dim * mlp_ratio, dim))
    layers.append(_layer("FC", 1, dim, 1000))
    return layers


def gen_mlp_mixer_like(H, W, patch=16, dim=512, depth=8, token_mlp_dim=256, channel_mlp_ratio=4):
    hp, wp = max(1, H // patch), max(1, W // patch)
    Ttok = hp * wp
    layers = [_layer(f"PatchProj(p={patch})", Ttok, 3 * patch * patch, dim)]
    for _ in range(depth):
        layers.append(_layer("TokenMix_fc1", dim, Ttok, token_mlp_dim))
        layers.append(_layer("TokenMix_fc2", dim, token_mlp_dim, Ttok))
        ch = dim * channel_mlp_ratio
        layers.append(_layer("ChannelMix_fc1", Ttok, dim, ch))
        layers.append(_layer("ChannelMix_fc2", Ttok, ch, dim))
    layers.append(_layer("FC", 1, dim, 1000))
    return layers


MODEL_GENS = {
    "MobileNet": gen_mobilenet_like,
    "ShuffleNet": gen_shufflenet_like,
    "GhostNet": gen_ghostnet_like,
    "ConvMLP": gen_convmlp_like,
    "MLP-Mixer": gen_mlp_mixer_like,
}


def build_instances(seed=SEED):
    rnd = random.Random(seed)
    instances = []
    for size in SIZES:
        H = W = size
        for name, gen in MODEL_GENS.items():
            for _ in range(INSTANCES_PER_SIZE):
                params = {"H": H, "W": W}
                if name in ["MobileNet", "ShuffleNet", "GhostNet"]:
                    wm = rnd.choice([0.25, 0.35, 0.5, 0.75, 1.0, 1.25, 1.5])
                    params["width_mult"] = wm
                    if name == "ShuffleNet":
                        groups = rnd.choice([1, 2, 3, 4])
                        params["groups"] = groups
                        layers = gen(H=H, W=W, width_mult=wm, groups=groups)
                    else:
                        layers = gen(H=H, W=W, width_mult=wm)
                elif name == "ConvMLP":
                    patch = rnd.choice([2, 4, 8, 16])
                    dim = rnd.choice([96, 128, 192, 256, 384])
                    depth = rnd.choice([4, 6, 8, 10])
                    params.update({"patch": patch, "dim": dim, "depth": depth, "mlp_ratio": 4})
                    layers = gen(H=H, W=W, patch=patch, dim=dim, depth=depth, mlp_ratio=4)
                else:
                    patch = rnd.choice([4, 8, 16, 32])
                    dim = rnd.choice([256, 384, 512, 768])
                    depth = rnd.choice([4, 6, 8, 12])
                    token_mlp_dim = rnd.choice([128, 192, 256, 384])
                    params.update({"patch": patch, "dim": dim, "depth": depth,
                                   "token_mlp_dim": token_mlp_dim, "channel_mlp_ratio": 4})
                    layers = gen(H=H, W=W, patch=patch, dim=dim, depth=depth,
                                token_mlp_dim=token_mlp_dim, channel_mlp_ratio=4)

                instances.append({"model": name, "params": params, "layers": layers})
    return instances


# ============================================================
# 3) 模拟：动态调度ab + IA复用 + 访存/计算并行（总耗时取 max）
# ============================================================
def ceil_div(a, b):
    return (a + b - 1) // b


def tiles_xyz(M, K, N, T=TILE):
    x = float(ceil_div(M, T))
    y = float(ceil_div(N, T))
    z = float(ceil_div(K, T))
    return x, y, z


def dynamic_choose_param(M, K, N, Smax):
    """
    全量遍历WS和IS模式，寻找最优整数解，综合考虑计算和访存时间，取max作为实际时间
    """
    best_speedup = 0
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

        for b in range(1, min(int(math.ceil(y)), int(Smax)) + 1):
            a = min(int(math.ceil(x)), Smax // b)
            if a < 1: continue

            # 计算复用块数
            B_reuse, _ = ia_reuse_blocks(x, y, z, a, b)
            mem_t1 = mem_time_from_blocks(B_total - B_reuse, T=TILE)

            # 计算节省
            comp_save = comp_time_ia_saved(x, y, z, a, b)
            comp_t1 = max(0.0, comp_t0 - comp_save)

            t1 = max(mem_t1, comp_t1)
            speedup = (t0 / t1) if t1 > 0 else 0

            if speedup > best_speedup:
                best_speedup = speedup
                best_abc_mode = (a, b, mode)

    return best_abc_mode


def ia_reuse_blocks(x, y, z, a, b):
    x = float(x); y = float(y); z = float(z)
    a = float(max(1, a)); b = float(max(1, b))

    p = x / a
    l = y / b
    B_reuse = p * l * z * (2.0 * a * b - (a + b)) + a * (l - 1.0)

    B_total = 2.0 * x * y * z
    B_reuse = float(np.clip(B_reuse, 0.0, B_total))
    return B_reuse, B_total


def ram_utilization_smax(a, b, Smax):
    # 修正：利用率定义为“对整个RAM容量上限Smax的占用比例”
    # util = s / Smax = (a*b)/Smax
    s = int(a) * int(b)
    return float(s) / float(max(Smax, 1))


def mem_time_from_blocks(B, T=TILE):
    return (T * T / 4.0) * float(B)


def comp_time_base(x, y, z):
    xyz = float(x) * float(y) * float(z)
    return 47.0 * xyz


def comp_time_ia_saved(x, y, z, a, b):
    # 参考 mem_opt.py 的 IA 复用节省公式
    x = float(x); y = float(y); z = float(z)
    a = float(max(1, a)); b = float(max(1, b))
    p = x / a
    l = y / b
    save_common = p * l * z * ((a - 1.0) * (31.0 * b - 15.0)) + 15.0 * (a - 1.0) * (l - 1.0)
    return save_common


def _simulate_with_dims(M, K, N, Smax):
    a, b, mode = dynamic_choose_param(M, K, N, Smax)

    if mode == 'WS':
        x, y, z = tiles_xyz(M, K, N, T=TILE)
    else:
        x, y, z = tiles_xyz(N, K, M, T=TILE)

    B_reuse, B_total = ia_reuse_blocks(x, y, z, a, b)

    mem_t0 = mem_time_from_blocks(B_total, T=TILE)
    mem_t1 = mem_time_from_blocks(B_total - B_reuse, T=TILE)

    comp_t0 = comp_time_base(x, y, z)
    comp_save = comp_time_ia_saved(x, y, z, a, b)
    comp_t1 = max(0.0, comp_t0 - comp_save)

    t0 = max(mem_t0, comp_t0)
    t1 = max(mem_t1, comp_t1)
    speedup = (t0 / t1) if t1 > 0 else float("inf")

    reuse_ratio = (B_reuse / B_total) if B_total > 0 else 0.0
    util = ram_utilization_smax(a, b, Smax)

    return {
        "x": x, "y": y, "z": z,
        "a": a, "b": b, "s": a * b,
        "reuse_ratio": reuse_ratio,
        "util": util,
        "t0": t0, "t1": t1,
        "mem_t0": mem_t0, "mem_t1": mem_t1,
        "comp_t0": comp_t0, "comp_t1": comp_t1,
        "speedup": speedup,
        "mode": mode,
    }


def simulate_layer(layer, Smax):
    M, K, N = layer["M"], layer["K"], layer["N"]

    res = _simulate_with_dims(M, K, N, Smax)

    return {
        "op": layer["op"],
        "M": M, "K": K, "N": N,
        **res,
    }


def simulate_instance(instance, Smax):
    rows = [simulate_layer(layer, Smax) for layer in instance["layers"]]
    t0_sum = sum(r["t0"] for r in rows)
    t1_sum = sum(r["t1"] for r in rows)
    sp = (t0_sum / t1_sum) if t1_sum > 0 else float("inf")
    reuse_avg = float(np.mean([r["reuse_ratio"] for r in rows])) if rows else 0.0
    return rows, t0_sum, t1_sum, sp, reuse_avg


def mean_speedup_over_instances(instances, Smax):
    def process_instance(inst, Smax):
        rows, t0, t1, _, _ = simulate_instance(inst, Smax)
        a_list = [r['a'] for r in rows]
        b_list = [r['b'] for r in rows]
        reuse_list = [r['reuse_ratio'] for r in rows]
        return t0, t1, a_list, b_list, reuse_list

    with ThreadPoolExecutor() as executor:
        results = list(executor.map(lambda inst: process_instance(inst, Smax), instances))

    t0_list = [r[0] for r in results]
    t1_list = [r[1] for r in results]
    a_list = [a for r in results for a in r[2]]
    b_list = [b for r in results for b in r[3]]
    reuse_list = [ru for r in results for ru in r[4]]

    mt0 = float(np.mean(t0_list))
    mt1 = float(np.mean(t1_list))
    sp = (mt0 / mt1) if mt1 > 0 else float("inf")
    mean_a = float(np.mean(a_list)) if a_list else 0
    mean_b = float(np.mean(b_list)) if b_list else 0
    mean_reuse = float(np.mean(reuse_list)) if reuse_list else 0
    return mt0, mt1, sp, mean_a, mean_b, mean_reuse


def compute_for_Smax(args):
    Smax, instances = args
    mean_t0, mean_t1, sp, mean_a, mean_b, mean_reuse = mean_speedup_over_instances(instances, Smax)
    return {"Smax": Smax, "mean_t0": mean_t0, "mean_t1": mean_t1, "speedup": sp, "mean_a": mean_a, "mean_b": mean_b, "mean_reuse": mean_reuse}


def find_sweet_point_kneedle(S_list, T_list, enforce_monotone=True):
    S = np.array(S_list, dtype=np.float64)
    T = np.array(T_list, dtype=np.float64)

    order = np.argsort(S)
    S, T = S[order], T[order]
    if enforce_monotone:
        T = np.minimum.accumulate(T)

    x = (S - S[0]) / (S[-1] - S[0]) if S[-1] != S[0] else np.zeros_like(S)
    Tmin, Tmax = float(np.min(T)), float(np.max(T))
    if Tmax == Tmin:
        return int(S[0]), 0

    y = (Tmax - T) / (Tmax - Tmin)
    g = y - x
    k = int(np.argmax(g))
    return int(S[k]), k


def speedup_test(instances, sweet_Smax, seed=TEST_SEED):
    rnd = random.Random(seed)
    all_rows = []
    for inst_id, inst in enumerate(instances):
        rows, *_ = simulate_instance(inst, sweet_Smax)
        for li, r in enumerate(rows):
            all_rows.append((inst_id, li, r))

    sample = rnd.sample(all_rows, k=min(TEST_SAMPLE_N, len(all_rows)))
    sample_sorted = sorted(sample, key=lambda t: t[2]["speedup"])
    all_sorted = sorted(all_rows, key=lambda t: t[2]["speedup"])
    worst = all_sorted[:min(TEST_WORST_K, len(all_sorted))]
    best = list(reversed(all_sorted[-min(TEST_BEST_K, len(all_sorted)):]))

    return {"all_rows": all_rows, "sample_sorted": sample_sorted, "worst": worst, "best": best}


def fmt_params(params):
    keys = [k for k in params.keys() if k not in ("H", "W")]
    keys = ["H", "W"] + sorted(keys)
    return ", ".join([f"{k}={params[k]}" for k in keys])


# ============================================================
# 4) 绘图：time/speedup 曲线 + sweet 下 speedup 分布
# ============================================================
def plot_results(curve, sweet_Smax, test_pack, save_prefix=None, show=True):
    S = [c["Smax"] for c in curve]
    t1 = [c["mean_t1"] for c in curve]
    sp = [c["speedup"] for c in curve]

    # (1) mean_t1 vs Smax
    plt.figure(figsize=(9.2, 5.8))
    plt.plot(S, t1, marker="o", color='black', markerfacecolor='white', markersize=6, linewidth=1.5, label='优化后平均时间')
    plt.axvline(sweet_Smax, linestyle="--", color='red', linewidth=1.5, label='膝点')
    sweet_entry = next(c for c in curve if c["Smax"] == sweet_Smax)

    ymin, ymax = min(t1), max(t1)
    plt.text(
        sweet_Smax + 10,
        ymin + 0.10 * (ymax - ymin),
        f"膝点 Smax={sweet_Smax}\n平均 a={sweet_entry['mean_a']:.1f}, b={sweet_entry['mean_b']:.1f}\n平均复用率={sweet_entry['mean_reuse']*100:.1f}%",
        fontsize=11, bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="black", alpha=0.8)
    )
    plt.xlabel("Smax (块数上限)")
    plt.ylabel("平均优化后时间 (clk)")
    plt.title("不同 Smax 下平均优化后时间的对比分析")
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.legend()
    plt.tight_layout()
    if save_prefix:
        plt.savefig(f"{save_prefix}_t1_vs_smax.png", dpi=300, bbox_inches='tight')
    if show:
        plt.show()

    # (2) speedup vs Smax
    plt.figure(figsize=(9.2, 5.8))
    plt.plot(S, sp, marker="s", color='black', markerfacecolor='white', markersize=6, linewidth=1.5, label='加速比')
    plt.axvline(sweet_Smax, linestyle="--", color='red', linewidth=1.5, label='膝点')
    ymin, ymax = min(sp), max(sp)
    plt.text(
        sweet_Smax + 10,
        ymin + 0.10 * (ymax - ymin),
        f"膝点 Smax={sweet_Smax}\n加速比={sweet_entry['speedup']:.3f}x\n平均 a={sweet_entry['mean_a']:.1f}, b={sweet_entry['mean_b']:.1f}\n平均复用率={sweet_entry['mean_reuse']*100:.1f}%",
        fontsize=11, bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="black", alpha=0.8)
    )
    plt.xlabel("Smax (块数上限)")
    plt.ylabel("加速比 (原始时间 / 优化后时间)")
    plt.title("不同 Smax 下加速比的对比分析")
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.legend()
    plt.tight_layout()
    if save_prefix:
        plt.savefig(f"{save_prefix}_speedup_vs_smax.png", dpi=300, bbox_inches='tight')
    if show:
        plt.show()

    # (3) sweet 点下 speedup 分布（全层）
    all_speedups = [r["speedup"] for (_, _, r) in test_pack["all_rows"]]
    plt.figure(figsize=(9.2, 5.8))
    plt.hist(all_speedups, bins=60, color='lightgray', edgecolor='black', alpha=0.8)
    plt.axvline(np.mean(all_speedups), color='red', linestyle='--', linewidth=1.5, label=f'平均加速比: {np.mean(all_speedups):.2f}x')
    plt.xlabel("单层加速比")
    plt.ylabel("层数")
    plt.title(f"膝点 Smax={sweet_Smax} 下单层加速比分布")
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.legend()
    plt.tight_layout()
    if save_prefix:
        plt.savefig(f"{save_prefix}_speedup_hist.png", dpi=300, bbox_inches='tight')
    if show:
        plt.show()


# ============================================================
# 5) 写 log（表格不打印 op/params，但保留 (a,b,s)、reuse%、util）
# ============================================================
def write_log(filepath, instances, curve, sweet_Smax, sweet_idx, test_pack):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("============================================================\n")
        f.write("动态调度ab，仅优化Smax，仅IA复用，访存/计算并行（总耗时取 max）\n")
        f.write(f"生成时间: {now}\n")
        f.write("------------------------------------------------------------\n")
        f.write(f"TILE(T)={TILE} | block_time=T^2/4={TILE*TILE/4:.1f} clk\n")
        f.write(f"SIZES={min(SIZES)}..{max(SIZES)} (count={len(SIZES)}) | INSTANCES_PER_SIZE={INSTANCES_PER_SIZE} | SEED={SEED}\n")
        f.write(f"S_MAX_LIST={S_MAX_LIST}\n")
        f.write(f"total_instances={len(instances)}\n")
        f.write("============================================================\n\n")

        # 曲线
        f.write("[1] time vs Smax\n")
        f.write("Smax | mean_t0(clk)     | mean_t1(clk)     | speedup\n")
        f.write("-----+------------------+------------------+---------\n")
        for c in curve:
            f.write(f"{c['Smax']:>4} | {c['mean_t0']:>16.2f} | {c['mean_t1']:>16.2f} | {c['speedup']:>7.3f}x\n")
        f.write("-----+------------------+------------------+---------\n")
        f.write(f"[SWEET POINT] Smax={sweet_Smax} | idx={sweet_idx} | mean_t1={curve[sweet_idx]['mean_t1']:.2f} | speedup={curve[sweet_idx]['speedup']:.3f}x\n\n")

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

        # 逐实例逐层日志（表格仍然不打印 op）
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
            rows, t0_sum, t1_sum, sp, reuse_avg = simulate_instance(inst, sweet_Smax)
            f.write(f"=== Instance {inst_id:06d} ===\n")
            f.write(f"model:  {inst['model']}\n")
            # 注意：这里是“实例摘要信息”，不是表格列；如果你也不想要 params，可以删掉这一行
            f.write(f"params: {fmt_params(inst['params'])}\n")
            f.write(f"Smax={sweet_Smax} | layers={len(rows)} | instance_speedup={sp:.3f}x | mean_layer_reuse={reuse_avg*100:.2f}%\n")

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

    return filepath


# ============================================================
# 6) main
# ============================================================
if __name__ == "__main__":
    instances = build_instances(seed=SEED)

    # 使用多进程并行计算不同 Smax
    with Pool() as pool:
        args_list = [(Smax, instances) for Smax in S_MAX_LIST]
        curve = pool.map(compute_for_Smax, args_list)

    sweet_Smax, sweet_idx = find_sweet_point_kneedle(
        [c["Smax"] for c in curve],
        [c["mean_t1"] for c in curve],
        enforce_monotone=True
    )

    test_pack = speedup_test(instances, sweet_Smax, seed=TEST_SEED)

    # 先保存图片，不显示
    plot_results(curve, sweet_Smax, test_pack, save_prefix="plot", show=False)

    # 写log
    write_log(LOG_PATH, instances, curve, sweet_Smax, sweet_idx, test_pack)
    print(f"[OK] log written to: {LOG_PATH}")

    # 绘图弹窗
    plot_results(curve, sweet_Smax, test_pack, save_prefix=None, show=True)
