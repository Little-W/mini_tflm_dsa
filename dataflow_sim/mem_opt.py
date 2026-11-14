import math
import random
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# =========================
# 0) 中文字体：自动探测 + 正确生效
# =========================
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
            print(f"[字体] 使用中文字体：{name}")
            return name
    print("[字体] 未找到常见中文字体（SimHei/微软雅黑/Noto CJK 等）。建议安装 Noto Sans CJK SC 或 WenQuanYi Micro Hei。")
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return None

setup_chinese_font()
plt.rcParams["font.size"] = 15
plt.rcParams["axes.titlesize"] = 16
plt.rcParams["axes.labelsize"] = 15
plt.rcParams["legend.fontsize"] = 13
plt.rcParams["xtick.labelsize"] = 13
plt.rcParams["ytick.labelsize"] = 13

# =========================
# 1) 全局设置
# =========================
TILE = 16

SIZES = list(range(32, 513, 8))
SIZES += [28, 36, 44, 52, 60, 68, 76, 84, 92, 100]
SIZES = sorted(set(SIZES))

INSTANCES_PER_SIZE = 16
SEED = 42

S_MAX_LIST = [4, 8, 16, 32, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 2048]

CAP_EFFECTIVE_AB = True

# =========================
# 2) 模型工作负载生成（只含 PW / Conv(img2col) / Dense，不含DW）
# =========================
def gen_mobilenet_like(H, W, width_mult=1.0):
    base = [32, 16, 24, 32, 64, 96, 160, 320, 1280]
    ch = [max(8, int(round(c * width_mult / 8)) * 8) for c in base]

    shapes = []
    H1, W1 = max(1, H // 2), max(1, W // 2)
    shapes.append((H1 * W1, 3 * 3 * 3, ch[0]))  # stem conv(img2col)

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
            shapes.append((hh * ww, c, t * c))         # PW expand
            shapes.append((hh * ww, t * c, cout))      # PW project
            c = cout

    hh, ww = max(1, H1 // 16), max(1, W1 // 16)
    shapes.append((hh * ww, ch[6], ch[8]))            # head PW
    shapes.append((1, ch[8], 1000))                   # FC
    return shapes

def gen_shufflenet_like(H, W, width_mult=1.0, groups=2):
    shapes = []
    c1 = max(8, int(round(24 * width_mult / 8)) * 8)
    H1, W1 = max(1, H // 2), max(1, W // 2)
    shapes.append((H1 * W1, 3 * 3 * 3, c1))

    stage_out = [max(8, int(round(c * width_mult / 8)) * 8) for c in [240, 480, 960]]
    stage_res = [(max(1, H1 // 2), max(1, W1 // 2)),
                 (max(1, H1 // 4), max(1, W1 // 4)),
                 (max(1, H1 // 8), max(1, W1 // 8))]

    cin = c1
    for (hh, ww), cout in zip(stage_res, stage_out):
        repeats = 4
        c = cin
        for _ in range(repeats):
            shapes.append((hh * ww, c, cout // 2))                 # 1x1
            shapes.append((hh * ww, (c // groups) * 9, cout // 2)) # 3x3 group conv(img2col)
            shapes.append((hh * ww, cout // 2, cout))              # 1x1
            c = cout
        cin = cout

    hh, ww = stage_res[-1]
    shapes.append((hh * ww, cin, 1024))
    shapes.append((1, 1024, 1000))
    return shapes

def gen_ghostnet_like(H, W, width_mult=1.0):
    shapes = []
    c1 = max(8, int(round(16 * width_mult / 8)) * 8)
    H1, W1 = max(1, H // 2), max(1, W // 2)
    shapes.append((H1 * W1, 3 * 3 * 3, c1))

    stage_ch = [max(8, int(round(c * width_mult / 8)) * 8) for c in [16, 24, 40, 80, 112, 160]]
    stage_res = [(H1, W1), (max(1, H1 // 2), max(1, W1 // 2)), (max(1, H1 // 4), max(1, W1 // 4)),
                 (max(1, H1 // 8), max(1, W1 // 8)), (max(1, H1 // 8), max(1, W1 // 8)), (max(1, H1 // 16), max(1, W1 // 16))]

    cin = c1
    for (hh, ww), cout in zip(stage_res, stage_ch):
        repeats = 2
        c = cin
        for _ in range(repeats):
            shapes.append((hh * ww, c, cout))     # 1x1
            shapes.append((hh * ww, cout, cout))  # 1x1
            c = cout
        cin = cout

    hh, ww = stage_res[-1]
    shapes.append((hh * ww, cin, 960))
    shapes.append((1, 960, 1000))
    return shapes

def gen_convmlp_like(H, W, patch=4, dim=256, depth=8, mlp_ratio=4):
    hp, wp = max(1, H // patch), max(1, W // patch)
    shapes = [(hp * wp, 3 * patch * patch, dim)]  # patch embed conv(img2col)
    for _ in range(depth):
        shapes.append((hp * wp, dim, dim))                 # token mix（近似PW）
        shapes.append((hp * wp, dim, dim * mlp_ratio))     # dense
        shapes.append((hp * wp, dim * mlp_ratio, dim))     # dense
    shapes.append((1, dim, 1000))
    return shapes

def gen_mlp_mixer_like(H, W, patch=16, dim=512, depth=8, token_mlp_dim=256, channel_mlp_ratio=4):
    hp, wp = max(1, H // patch), max(1, W // patch)
    T = hp * wp
    shapes = [(T, 3 * patch * patch, dim)]  # patch projection
    for _ in range(depth):
        shapes.append((dim, T, token_mlp_dim))
        shapes.append((dim, token_mlp_dim, T))
        ch = dim * channel_mlp_ratio
        shapes.append((T, dim, ch))
        shapes.append((T, ch, dim))
    shapes.append((1, dim, 1000))
    return shapes

MODEL_GENS = {
    "MobileNet": gen_mobilenet_like,
    "ShuffleNet": gen_shufflenet_like,
    "GhostNet": gen_ghostnet_like,
    "ConvMLP": gen_convmlp_like,
    "MLP-Mixer": gen_mlp_mixer_like,
}

# =========================
# 3) 构建数据集：返回“实例级”列表（每个实例是一组层）
# =========================
def build_instances(seed=SEED):
    rnd = random.Random(seed)
    instances = []

    for size in SIZES:
        H = W = size
        for name, gen in MODEL_GENS.items():
            for _ in range(INSTANCES_PER_SIZE):
                if name in ["MobileNet", "ShuffleNet", "GhostNet"]:
                    wm = rnd.choice([0.35, 0.5, 0.75, 1.0, 1.25])
                    if name == "ShuffleNet":
                        groups = rnd.choice([2, 3])
                        layers = gen(H=H, W=W, width_mult=wm, groups=groups)
                    else:
                        layers = gen(H=H, W=W, width_mult=wm)
                elif name == "ConvMLP":
                    patch = rnd.choice([2, 4, 8])
                    dim = rnd.choice([96, 128, 192, 256, 384])
                    depth = rnd.choice([4, 6, 8, 10])
                    layers = gen(H=H, W=W, patch=patch, dim=dim, depth=depth, mlp_ratio=4)
                else:
                    patch = rnd.choice([8, 16])
                    dim = rnd.choice([256, 384, 512, 768])
                    depth = rnd.choice([4, 6, 8, 12])
                    token_mlp_dim = rnd.choice([128, 192, 256, 384])
                    layers = gen(H=H, W=W, patch=patch, dim=dim, depth=depth,
                                token_mlp_dim=token_mlp_dim, channel_mlp_ratio=4)

                instances.append(layers)

    return instances

# =========================
# 4) (M,K,N)->(x,y,z) 与实例索引展开
# =========================
def flatten_instances(instances):
    Ms, Ks, Ns = [], [], []
    inst_id = []
    for i, layers in enumerate(instances):
        for (M, K, N) in layers:
            Ms.append(int(M)); Ks.append(int(K)); Ns.append(int(N))
            inst_id.append(i)

    Ms = np.array(Ms, dtype=np.int64)
    Ks = np.array(Ks, dtype=np.int64)
    Ns = np.array(Ns, dtype=np.int64)
    inst_id = np.array(inst_id, dtype=np.int32)

    x = ((Ms + TILE - 1) // TILE).astype(np.float64)
    y = ((Ns + TILE - 1) // TILE).astype(np.float64)
    z = ((Ks + TILE - 1) // TILE).astype(np.float64)

    xyz = x * y * z
    B_total = 2.0 * xyz  # 2xyz

    return x, y, z, xyz, B_total, inst_id, len(instances)

# =========================
# 5) 复用块数 + 计算节省周期 + 总耗时（分解为 mem / comp）
# =========================
def calc_components_for_method(x, y, xyz, B_total, a, b, method):
    # 有效截断，避免 a>x 或 b>y 时出现虚高
    if CAP_EFFECTIVE_AB:
        ae = np.minimum(x, float(a))
        be = np.minimum(y, float(b))
    else:
        ae = float(a)
        be = float(b)

    p = x / ae
    l = y / be

    # --- Breuse（按原公式）---
    base_reuse = p * l * (2.0 * ae * be - (ae + be))
    if method == "IA":
        B_reuse = base_reuse + ae * (l - 1.0)
    else:  # "W"
        B_reuse = base_reuse + (p - 1.0)

    B_reuse = np.clip(B_reuse, 0.0, B_total)

    # --- 访存时间：64clk/块，访存块数=B_total-Breuse ---
    B_mem = B_total - B_reuse
    T_mem = 64.0 * B_mem

    # --- 计算时间基线：47clk/块计算，总共xyz次 ---
    T_comp_base = 47.0 * xyz

    # --- 复用节省的计算周期（新公式）---
    save_common = p * l * ((ae - 1.0) * (31.0 * be - 15.0))
    if method == "IA":
        T_save = save_common + 15.0 * (ae - 1.0) * (l - 1.0)
    else:
        T_save = save_common + 16.0 * (p - 1.0)

    T_comp = np.maximum(0.0, T_comp_base - T_save)

    T_total = T_mem + T_comp
    return T_total, T_mem, T_comp, B_reuse, T_save

def ram_utilization(x, y, a, b):
    gx = np.ceil(x / float(a))
    gy = np.ceil(y / float(b))
    denom = gx * gy * float(a) * float(b)
    return (x * y) / np.maximum(denom, 1.0)

# =========================
# 6) 基准（无复用）统计：只按建模定义，不走 IA/W 公式
# =========================
def baseline_stats(xyz, B_total, inst_id, n_inst):
    # 无复用：B_reuse=0, T_save=0
    T_mem_layer = 64.0 * B_total
    T_comp_layer = 47.0 * xyz
    T_total_layer = T_mem_layer + T_comp_layer

    inst_time = np.bincount(inst_id, weights=T_total_layer, minlength=n_inst)
    inst_mem = np.bincount(inst_id, weights=T_mem_layer, minlength=n_inst)
    inst_comp = np.bincount(inst_id, weights=T_comp_layer, minlength=n_inst)

    mean_time = float(np.mean(inst_time))
    mean_mem = float(np.mean(inst_mem))
    mean_comp = float(np.mean(inst_comp))

    mem_ratio = (mean_mem / mean_time) if mean_time > 0 else 0.0
    comp_ratio = (mean_comp / mean_time) if mean_time > 0 else 0.0
    return mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio

# =========================
# 7) 对给定(a,b)计算“实例平均耗时”（目标：最小）
# =========================
def score_config(x, y, xyz, B_total, inst_id, n_inst, a, b):
    T_ia, M_ia, C_ia, _, _ = calc_components_for_method(x, y, xyz, B_total, a, b, "IA")
    T_w , M_w , C_w , _, _ = calc_components_for_method(x, y, xyz, B_total, a, b, "W")

    # 层级选择更快的方法（并对 mem/comp 做同样选择）
    ia_win = (T_ia <= T_w)
    T_best = np.where(ia_win, T_ia, T_w)
    M_best = np.where(ia_win, M_ia, M_w)
    C_best = np.where(ia_win, C_ia, C_w)

    # 每个实例聚合后再平均（避免深模型层多主导）
    inst_time = np.bincount(inst_id, weights=T_best, minlength=n_inst)
    inst_mem  = np.bincount(inst_id, weights=M_best, minlength=n_inst)
    inst_comp = np.bincount(inst_id, weights=C_best, minlength=n_inst)

    mean_time = float(np.mean(inst_time))
    mean_mem  = float(np.mean(inst_mem))
    mean_comp = float(np.mean(inst_comp))

    mem_ratio  = (mean_mem / mean_time) if mean_time > 0 else 0.0
    comp_ratio = (mean_comp / mean_time) if mean_time > 0 else 0.0

    ia_ratio = float(np.mean(ia_win))

    # RAM利用率（参考）：实例内层均值，再对实例平均
    U_layer = ram_utilization(x, y, a, b)
    inst_util_sum = np.bincount(inst_id, weights=U_layer, minlength=n_inst)
    inst_cnt = np.bincount(inst_id, minlength=n_inst)
    inst_util = inst_util_sum / np.maximum(inst_cnt, 1)
    mean_util = float(np.mean(inst_util))

    method = "IA" if ia_ratio >= 0.5 else "W"
    return mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio, mean_util, method, ia_ratio

# =========================
# 8) 枚举配置 + 扫描不同 Smax
# =========================
def all_configs_upto(S_max_max):
    cfgs = []
    for a in range(1, S_max_max + 1):
        for b in range(1, S_max_max // a + 1):
            cfgs.append((a * b, a, b))
    return cfgs

def optimize_over_smax(x, y, xyz, B_total, inst_id, n_inst, S_max_list):
    cfgs = all_configs_upto(max(S_max_list))

    rec = []
    rec_mul = []

    for (s, a, b) in cfgs:
        mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio, mean_util, method, ia_ratio = \
            score_config(x, y, xyz, B_total, inst_id, n_inst, a, b)

        rec.append((s, a, b, mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio, mean_util, method, ia_ratio))

        if (a % b == 0) or (b % a == 0):
            rec_mul.append((s, a, b, mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio, mean_util, method, ia_ratio))

    curve = []
    curve_mul = []

    for Smax in S_max_list:
        cand = [r for r in rec if r[0] <= Smax]
        best = min(cand, key=lambda t: t[3])
        (s, a, b, mt, mm, mc, mr, cr, mu, method, ia_ratio) = best
        curve.append(dict(Smax=Smax, s=s, a=a, b=b, time=mt, mem=mm, comp=mc,
                          mem_ratio=mr, comp_ratio=cr, util=mu, method=method, ia_ratio=ia_ratio))

        cand2 = [r for r in rec_mul if r[0] <= Smax]
        if cand2:
            best2 = min(cand2, key=lambda t: t[3])
            (s2, a2, b2, mt2, mm2, mc2, mr2, cr2, mu2, method2, ia_ratio2) = best2
            curve_mul.append(dict(Smax=Smax, s=s2, a=a2, b=b2, time=mt2, mem=mm2, comp=mc2,
                                  mem_ratio=mr2, comp_ratio=cr2, util=mu2, method=method2, ia_ratio=ia_ratio2))
        else:
            curve_mul.append(dict(Smax=Smax, s=-1, a=-1, b=-1, time=float("nan"), mem=float("nan"), comp=float("nan"),
                                  mem_ratio=float("nan"), comp_ratio=float("nan"),
                                  util=float("nan"), method="NA", ia_ratio=float("nan")))

    return curve, curve_mul

# =========================
# 9) Kneedle 膝点（sweet spot）
# =========================
def find_sweet_point_kneedle(curve, enforce_monotone=True):
    S = np.array([c["Smax"] for c in curve], dtype=np.float64)
    T = np.array([c["time"] for c in curve], dtype=np.float64)

    order = np.argsort(S)
    S, T = S[order], T[order]

    if enforce_monotone:
        T = np.minimum.accumulate(T)

    if S[-1] == S[0]:
        return int(S[0]), 0, (None, None, None)

    x = (S - S[0]) / (S[-1] - S[0])

    Tmin, Tmax = float(np.min(T)), float(np.max(T))
    if Tmax == Tmin:
        return int(S[0]), 0, (x, np.zeros_like(x), np.zeros_like(x))

    y = (Tmax - T) / (Tmax - Tmin)

    g = y - x
    k = int(np.argmax(g))
    return int(S[k]), k, (x, y, g)

# =========================
# 10) 绘图
# =========================
def plot_curves(curve, curve_mul):
    Smax = [c["Smax"] for c in curve]
    t1 = [c["time"] for c in curve]
    t2 = [c["time"] for c in curve_mul]

    plt.figure(figsize=(9.6, 6.2))
    plt.plot(Smax, t1, marker="o", label="最优总耗时（无约束）")
    plt.plot(Smax, t2, marker="o", label="最优总耗时（a/b整数倍约束）")
    plt.xlabel("部分和 RAM 容量上限 S_max（块）")
    plt.ylabel("总耗时（clk，实例平均）")
    plt.title("总耗时 vs RAM 容量上限")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(frameon=True)

    sweet_Smax, _, _ = find_sweet_point_kneedle(curve, enforce_monotone=True)
    sweet_entry = next(c for c in curve if c["Smax"] == sweet_Smax)
    plt.axvline(sweet_Smax, linestyle="--")
    plt.text(
        sweet_Smax,
        min(t1) + 0.1 * (max(t1) - min(t1)),
        f"  膝点 Smax={sweet_Smax}\n  访存{sweet_entry['mem_ratio']*100:.1f}% 计算{sweet_entry['comp_ratio']*100:.1f}%",
        va="bottom"
    )
    plt.tight_layout()
    plt.show()

    u1 = [c["util"] for c in curve]
    u2 = [c["util"] for c in curve_mul]

    plt.figure(figsize=(9.6, 6.2))
    plt.plot(Smax, u1, marker="o", label="RAM 利用率（无约束最优配置，仅参考）")
    plt.plot(Smax, u2, marker="o", label="RAM 利用率（整数倍约束最优配置，仅参考）")
    plt.xlabel("部分和 RAM 容量上限 S_max（块）")
    plt.ylabel("RAM 利用率（层均值再对实例平均）")
    plt.title("RAM 利用率 vs RAM 容量上限（参考）")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(frameon=True)
    plt.tight_layout()
    plt.show()

# =========================
# 11) main
# =========================
if __name__ == "__main__":
    print("[设置] TILE =", TILE)
    print("[设置] 尺寸数量 =", len(SIZES), "范围 =", (min(SIZES), max(SIZES)), "步长≈8")
    print("[设置] INSTANCES_PER_SIZE =", INSTANCES_PER_SIZE)
    print("[设置] S_MAX_LIST =", S_MAX_LIST)
    print("[设置] CAP_EFFECTIVE_AB =", CAP_EFFECTIVE_AB)

    instances = build_instances(seed=SEED)
    x, y, z, xyz, B_total, inst_id, n_inst = flatten_instances(instances)

    print("[数据] 实例数 =", n_inst, "层数 =", len(x))

    # 基准：无复用（严格按定义）
    baseline_time, baseline_mem, baseline_comp, baseline_mr, baseline_cr = baseline_stats(
        xyz, B_total, inst_id, n_inst
    )
    print(f"[基准] 无复用耗时 = {baseline_time:.2f} clk | 访存={baseline_mem:.2f} ({baseline_mr*100:.1f}%) | "
          f"计算={baseline_comp:.2f} ({baseline_cr*100:.1f}%)")

    curve, curve_mul = optimize_over_smax(x, y, xyz, B_total, inst_id, n_inst, S_MAX_LIST)

    print("\n[逐 S_max 最优（无约束，目标：最小总耗时）]")
    for c in curve:
        total_speedup = baseline_time / c["time"] if c["time"] > 0 else 0.0
        mem_speedup = baseline_mem / c["mem"] if c["mem"] > 0 else 0.0
        comp_speedup = baseline_comp / c["comp"] if c["comp"] > 0 else 0.0
        print(
            f"Smax={c['Smax']:>4} | time={c['time']:.2f} clk | 加速比={total_speedup:.2f}x | "
            f"访存({c['mem_ratio']*100:.1f}%) | "
            f"计算({c['comp_ratio']*100:.1f}%) | "
            f"method≈{c['method']} | (a,b,s)=({c['a']},{c['b']},{c['s']}) | util={c['util']:.3f} | IA胜率={c['ia_ratio']:.2f}"
        )

    print("\n[逐 S_max 最优（a/b整数倍约束，参考）]")
    for c in curve_mul:
        if np.isnan(c["time"]) or c["time"] <= 0:
            print(
                f"Smax={c['Smax']:>4} | 无可行解（倍数约束下）"
            )
            continue
        total_speedup = baseline_time / c["time"] if c["time"] > 0 else 0.0
        mem_speedup = baseline_mem / c["mem"] if c["mem"] > 0 else 0.0
        comp_speedup = baseline_comp / c["comp"] if c["comp"] > 0 else 0.0
        print(
            f"Smax={c['Smax']:>4} | time={c['time']:.2f} clk | 总加速比={total_speedup:.2f}x | "
            f"访存={c['mem']:.2f} ({c['mem_ratio']*100:.1f}%) 加速比={mem_speedup:.2f}x | "
            f"计算={c['comp']:.2f} ({c['comp_ratio']*100:.1f}%) 加速比={comp_speedup:.2f}x | "
            f"method≈{c['method']} | (a,b,s)=({c['a']},{c['b']},{c['s']}) | util={c['util']:.3f} | IA胜率={c['ia_ratio']:.2f}"
        )

    sweet_Smax, _, _ = find_sweet_point_kneedle(curve, enforce_monotone=True)
    sweet_entry = next(c for c in curve if c["Smax"] == sweet_Smax)
    sweet_total_speedup = baseline_time / sweet_entry["time"] if sweet_entry["time"] > 0 else 0.0
    sweet_mem_speedup = baseline_mem / sweet_entry["mem"] if sweet_entry["mem"] > 0 else 0.0
    sweet_comp_speedup = baseline_comp / sweet_entry["comp"] if sweet_entry["comp"] > 0 else 0.0

    print("\n[SWEET POINT（Kneedle 膝点）]")
    print(
        f"膝点 Smax = {sweet_Smax} | time={sweet_entry['time']:.2f} clk | 总加速比={sweet_total_speedup:.2f}x | "
        f"访存占比={sweet_entry['mem_ratio']*100:.1f}% 访存加速比={sweet_mem_speedup:.2f}x | "
        f"计算占比={sweet_entry['comp_ratio']*100:.1f}% 计算加速比={sweet_comp_speedup:.2f}x"
    )

    plot_curves(curve, curve_mul)
