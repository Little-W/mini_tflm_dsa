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
# T：只取 4 的倍数，细化范围（可自行调整上界）
T_MIN, T_MAX, T_STEP = 4, 64, 4
T_LIST = list(range(T_MIN, T_MAX + 1, T_STEP))

# 输入尺寸步进（含小尺寸）
SIZES = list(range(32, 513, 8))
SIZES += [28, 36, 44, 52, 60, 68, 76, 84, 92, 100]
SIZES = sorted(set(SIZES))

INSTANCES_PER_SIZE = 6
SEED = 42

# 复用/节省周期计算时的有效截断（避免小层+大a,b虚高）
CAP_EFFECTIVE_AB = True

# ——特别注意：RAM 采用“实际容量”，不是块数——
# 我们用“实际容量上限 C_max = (块数上限) * (T_min^2)” 来生成一组固定的真实容量列表
# 这样对任意 T，块数上限会变成 floor(C_max / T^2)
# （确保对最小 T=4 时，块数上限不会超过 2048）
S_BLOCK_LIST_AT_TMIN = [4, 8, 16, 32, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048]
RAM_CAP_LIST = [s * (T_MIN * T_MIN) for s in S_BLOCK_LIST_AT_TMIN]  # 真实容量上限（单位：元素/槽位）

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
    Tok = hp * wp
    shapes = [(Tok, 3 * patch * patch, dim)]  # patch projection
    for _ in range(depth):
        shapes.append((dim, Tok, token_mlp_dim))
        shapes.append((dim, token_mlp_dim, Tok))
        ch = dim * channel_mlp_ratio
        shapes.append((Tok, dim, ch))
        shapes.append((Tok, ch, dim))
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
# 4) 展平：保留 (M,K,N) 与实例索引
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
    return Ms, Ks, Ns, inst_id, len(instances)

def block_arrays_from_MKN(Ms, Ks, Ns, T):
    # x=ceil(M/T), y=ceil(N/T), z=ceil(K/T)
    x = ((Ms + T - 1) // T).astype(np.float64)
    y = ((Ns + T - 1) // T).astype(np.float64)
    z = ((Ks + T - 1) // T).astype(np.float64)
    xyz = x * y * z
    B_total = 2.0 * xyz
    return x, y, z, xyz, B_total

# =========================
# 5) 耗时模型（含 T）
#    - 单块访存耗时： (T^2)/4 clk
#    - 计算基线： (3T-1) xyz
#    - 计算节省：
#      ΔT_IA = pl[(a-1)((2T-1)b-(T-1))] + (T-1)(a-1)(l-1)
#      ΔT_W  = pl[(a-1)((2T-1)b-(T-1))] + T(p-1)
# =========================
def calc_components_for_method(T, x, y, xyz, B_total, a, b, method):
    if CAP_EFFECTIVE_AB:
        ae = np.minimum(x, float(a))
        be = np.minimum(y, float(b))
    else:
        ae = float(a)
        be = float(b)

    p = x / ae
    l = y / be

    # 复用块数（以块计）
    base_reuse = p * l * (2.0 * ae * be - (ae + be))
    if method == "IA":
        B_reuse = base_reuse + ae * (l - 1.0)
    else:  # "W"
        B_reuse = base_reuse + (p - 1.0)
    B_reuse = np.clip(B_reuse, 0.0, B_total)

    # 访存耗时：每块 (T^2)/4 clk
    mem_cost = (float(T) * float(T)) / 4.0
    B_mem = B_total - B_reuse
    T_mem = mem_cost * B_mem

    # 计算基线
    T_comp_base = (3.0 * float(T) - 1.0) * xyz

    # 计算节省周期（用 ae/be 做有效截断）
    save_common = p * l * ((ae - 1.0) * (((2.0 * float(T) - 1.0) * be) - (float(T) - 1.0)))
    if method == "IA":
        T_save = save_common + (float(T) - 1.0) * (ae - 1.0) * (l - 1.0)
    else:
        T_save = save_common + float(T) * (p - 1.0)

    T_comp = np.maximum(0.0, T_comp_base - T_save)
    T_total = T_mem + T_comp
    return T_total, T_mem, T_comp

def ram_utilization(x, y, a, b):
    gx = np.ceil(x / float(a))
    gy = np.ceil(y / float(b))
    denom = gx * gy * float(a) * float(b)
    return (x * y) / np.maximum(denom, 1.0)

# =========================
# 6) baseline（同一 T 下无复用）
# =========================
def baseline_stats(T, xyz, B_total, inst_id, n_inst):
    mem_cost = (float(T) * float(T)) / 4.0
    T_mem_layer = mem_cost * B_total
    T_comp_layer = (3.0 * float(T) - 1.0) * xyz
    T_total_layer = T_mem_layer + T_comp_layer

    inst_time = np.bincount(inst_id, weights=T_total_layer, minlength=n_inst)
    inst_mem  = np.bincount(inst_id, weights=T_mem_layer, minlength=n_inst)
    inst_comp = np.bincount(inst_id, weights=T_comp_layer, minlength=n_inst)

    mean_time = float(np.mean(inst_time))
    mean_mem  = float(np.mean(inst_mem))
    mean_comp = float(np.mean(inst_comp))

    mem_ratio  = (mean_mem / mean_time) if mean_time > 0 else 0.0
    comp_ratio = (mean_comp / mean_time) if mean_time > 0 else 0.0
    return mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio

# =========================
# 7) 给定 (T,a,b) 的实例均值耗时（逐层选 min(IA,W)）
# =========================
def score_config(T, x, y, xyz, B_total, inst_id, n_inst, a, b):
    T_ia, M_ia, C_ia = calc_components_for_method(T, x, y, xyz, B_total, a, b, "IA")
    T_w , M_w , C_w  = calc_components_for_method(T, x, y, xyz, B_total, a, b, "W")

    ia_win = (T_ia <= T_w)
    T_best = np.where(ia_win, T_ia, T_w)
    M_best = np.where(ia_win, M_ia, M_w)
    C_best = np.where(ia_win, C_ia, C_w)

    inst_time = np.bincount(inst_id, weights=T_best, minlength=n_inst)
    inst_mem  = np.bincount(inst_id, weights=M_best, minlength=n_inst)
    inst_comp = np.bincount(inst_id, weights=C_best, minlength=n_inst)

    mean_time = float(np.mean(inst_time))
    mean_mem  = float(np.mean(inst_mem))
    mean_comp = float(np.mean(inst_comp))

    mem_ratio  = (mean_mem / mean_time) if mean_time > 0 else 0.0
    comp_ratio = (mean_comp / mean_time) if mean_time > 0 else 0.0

    ia_ratio = float(np.mean(ia_win))
    method = "IA" if ia_ratio >= 0.5 else "W"

    U_layer = ram_utilization(x, y, a, b)
    inst_util_sum = np.bincount(inst_id, weights=U_layer, minlength=n_inst)
    inst_cnt = np.bincount(inst_id, minlength=n_inst)
    inst_util = inst_util_sum / np.maximum(inst_cnt, 1)
    mean_util = float(np.mean(inst_util))

    return mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio, mean_util, method, ia_ratio

# =========================
# 8) 配置枚举与 prefix 最小查询
# =========================
def all_configs_upto(S_max_blocks):
    cfgs = []
    for a in range(1, S_max_blocks + 1):
        for b in range(1, S_max_blocks // a + 1):
            cfgs.append((a * b, a, b))
    return cfgs

def prepare_prefix_best(records):
    """
    records: list of tuples (s, a, b, time, mem, comp, mem_ratio, comp_ratio, util, method, ia_ratio)
    return: s_vals(np.array), prefix_best(list of same tuple)
    """
    rec_sorted = sorted(records, key=lambda r: r[0])
    s_vals = np.array([r[0] for r in rec_sorted], dtype=np.int64)
    prefix_best = []
    best = None
    for r in rec_sorted:
        if best is None or r[3] < best[3]:
            best = r
        prefix_best.append(best)
    return s_vals, prefix_best

def query_best(s_vals, prefix_best, S_limit_blocks):
    if S_limit_blocks <= 0:
        return None
    idx = int(np.searchsorted(s_vals, S_limit_blocks, side="right") - 1)
    if idx < 0:
        return None
    return prefix_best[idx]

# =========================
# 9) Kneedle（通用版：x 单调增，y 单调减更常见）
# =========================
def kneedle_on_decreasing_curve(x, y, enforce_monotone=True):
    """
    x: increasing
    y: typically decreasing
    返回：knee_x, knee_idx, (x_norm, y_norm, g)
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    order = np.argsort(x)
    x = x[order]
    y = y[order]

    if enforce_monotone:
        y = np.minimum.accumulate(y)

    if x[-1] == x[0]:
        return float(x[0]), 0, (None, None, None)

    x_norm = (x - x[0]) / (x[-1] - x[0])

    ymin, ymax = float(np.min(y)), float(np.max(y))
    if ymax == ymin:
        y_norm = np.zeros_like(x_norm)
        g = y_norm - x_norm
        return float(x[0]), 0, (x_norm, y_norm, g)

    # 将“耗时下降”转成“收益上升”
    y_norm = (ymax - y) / (ymax - ymin)
    g = y_norm - x_norm
    k = int(np.argmax(g))
    return float(x[k]), k, (x_norm, y_norm, g)

# =========================
# 10) 对单个 T：独立迭代、打印 log、找甜点（按“实际容量”）
# =========================
def run_single_T(T, Ms, Ks, Ns, inst_id, n_inst, ram_cap_list):
    # 过滤：实际容量至少能容纳 1 个块（T^2 元素）
    ram_cap_list = [c for c in ram_cap_list if c >= T * T]
    ram_cap_list = sorted(ram_cap_list)

    x, y, z, xyz, B_total = block_arrays_from_MKN(Ms, Ks, Ns, T)
    bt, bm, bc, bmr, bcr = baseline_stats(T, xyz, B_total, inst_id, n_inst)

    # 对当前 T，最大可用块数上限 = floor(max(C)/T^2)
    S_max_blocks_global = int(max(ram_cap_list) // (T * T))
    S_max_blocks_global = max(1, S_max_blocks_global)

    # 枚举并评分（一次性做完，后续 prefix 查询）
    cfgs = all_configs_upto(S_max_blocks_global)

    rec = []
    rec_mul = []
    for (s, a, b) in cfgs:
        mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio, mean_util, method, ia_ratio = \
            score_config(T, x, y, xyz, B_total, inst_id, n_inst, a, b)
        tup = (s, a, b, mean_time, mean_mem, mean_comp, mem_ratio, comp_ratio, mean_util, method, ia_ratio)
        rec.append(tup)
        if (a % b == 0) or (b % a == 0):
            rec_mul.append(tup)

    s_vals, pref_best = prepare_prefix_best(rec)
    if rec_mul:
        s_vals_mul, pref_best_mul = prepare_prefix_best(rec_mul)
    else:
        s_vals_mul, pref_best_mul = None, None

    # 扫描真实容量曲线
    curve = []
    curve_mul = []

    print(f"\n===================== [T={T}] =====================")
    print(f"[T={T}] baseline: time={bt:.2f} | mem={bm:.2f} ({bmr*100:.1f}%) | comp={bc:.2f} ({bcr*100:.1f}%)")
    print(f"[T={T}] 扫描 RAM 实际容量上限 C_max（单位：元素/槽位），并在块数上限 S_max=floor(C_max/T^2) 下取最优(a,b)")

    for Cmax in ram_cap_list:
        S_limit = int(Cmax // (T * T))
        S_limit = max(1, S_limit)

        best = query_best(s_vals, pref_best, S_limit)
        if best is None:
            continue
        (s, a, b, mt, mm, mc, mr, cr, mu, method, ia_ratio) = best

        used_actual = int(s * (T * T))
        total_speedup = bt / mt if mt > 0 else 0.0
        mem_speedup = bm / mm if mm > 0 else 0.0
        comp_speedup = bc / mc if mc > 0 else 0.0

        curve.append(dict(
            T=T, Cmax=int(Cmax), Smax_blocks=S_limit,
            s=s, a=a, b=b,
            time=mt, mem=mm, comp=mc,
            mem_ratio=mr, comp_ratio=cr,
            util=mu, method=method, ia_ratio=ia_ratio,
            used_actual=used_actual
        ))

        # 倍数约束
        if pref_best_mul is not None:
            best2 = query_best(s_vals_mul, pref_best_mul, S_limit)
            if best2 is None:
                curve_mul.append(dict(T=T, Cmax=int(Cmax), time=float("nan")))
            else:
                (s2, a2, b2, mt2, mm2, mc2, mr2, cr2, mu2, method2, ia_ratio2) = best2
                used2 = int(s2 * (T * T))
                curve_mul.append(dict(
                    T=T, Cmax=int(Cmax), Smax_blocks=S_limit,
                    s=s2, a=a2, b=b2,
                    time=mt2, mem=mm2, comp=mc2,
                    mem_ratio=mr2, comp_ratio=cr2,
                    util=mu2, method=method2, ia_ratio=ia_ratio2,
                    used_actual=used2
                ))

        # log（无约束）
        print(
            f"[T={T}] Cmax={int(Cmax):>6} | Smax_blocks={S_limit:>4} | "
            f"time={mt:>10.2f} | 总加速比={total_speedup:>6.2f}x | "
            f"mem={mm:>10.2f} ({mr*100:>5.1f}%) mem加速比={mem_speedup:>6.2f}x | "
            f"comp={mc:>10.2f} ({cr*100:>5.1f}%) comp加速比={comp_speedup:>6.2f}x | "
            f"(a,b,s)=({a},{b},{s}) | used={used_actual:>7} | IA胜率={ia_ratio:>4.2f}"
        )

    # 甜点：在“time vs Cmax（实际容量）”曲线上做 Kneedle
    x_cap = [c["Cmax"] for c in curve]
    y_time = [c["time"] for c in curve]
    sweet_C, sweet_idx, _ = kneedle_on_decreasing_curve(x_cap, y_time, enforce_monotone=True)

    sweet_entry = min(curve, key=lambda d: abs(d["Cmax"] - sweet_C))
    print(f"[T={T}] SWEET（Kneedle）: Cmax≈{int(sweet_C)} -> 取 Cmax={sweet_entry['Cmax']} | "
          f"Smax_blocks={sweet_entry['Smax_blocks']} | time={sweet_entry['time']:.2f} | "
          f"(a,b,s)=({sweet_entry['a']},{sweet_entry['b']},{sweet_entry['s']}) | used_actual={sweet_entry['used_actual']}")

    return {
        "T": T,
        "baseline": (bt, bm, bc, bmr, bcr),
        "curve": curve,
        "curve_mul": curve_mul,
        "sweet": sweet_entry,  # 甜点点本身（其 Cmax 已是实际容量）
        "prefix": (s_vals, pref_best),
        "prefix_mul": (s_vals_mul, pref_best_mul)
    }

# =========================
# 11) 固定“最大甜点实际容量”后，跨 T 比较时间并找膝点 + 画图
# =========================
def compare_T_under_fixed_capacity(results_by_T, C_ref):
    Ts = []
    times = []
    details = []

    print("\n===================== [跨T对比：固定实际容量 C_ref] =====================")
    print(f"[跨T对比] 选取 C_ref = 所有T的甜点中最大的实际容量上限 = {C_ref}")
    print("[跨T对比] 对每个 T，采用同一实际容量上限 C_ref，块数上限 Smax=floor(C_ref/T^2)，在该约束下选最优(a,b)并比较 time")

    for res in results_by_T:
        T = res["T"]
        (bt, bm, bc, _, _) = res["baseline"]
        s_vals, pref_best = res["prefix"]

        S_limit = int(C_ref // (T * T))
        if S_limit <= 0:
            continue

        best = query_best(s_vals, pref_best, S_limit)
        if best is None:
            continue

        (s, a, b, mt, mm, mc, mr, cr, mu, method, ia_ratio) = best
        used_actual = int(s * (T * T))

        # 这里只比较“总耗时 mt”；如需也可打印 mem/comp
        Ts.append(T)
        times.append(mt)
        details.append(dict(T=T, C_ref=C_ref, Smax_blocks=S_limit, s=s, a=a, b=b,
                            time=mt, mem=mm, comp=mc, mem_ratio=mr, comp_ratio=cr,
                            used_actual=used_actual, method=method, ia_ratio=ia_ratio,
                            baseline_time=bt, baseline_mem=bm, baseline_comp=bc))

        print(
            f"[C_ref={C_ref}] T={T:>2} | Smax_blocks={S_limit:>4} | time={mt:>10.2f} | "
            f"(a,b,s)=({a},{b},{s}) | used_actual={used_actual:>7} | "
            f"mem%={mr*100:>5.1f}% comp%={cr*100:>5.1f}%"
        )

    # 膝点：time 随 T 增大通常下降
    knee_T, knee_idx, _ = kneedle_on_decreasing_curve(Ts, times, enforce_monotone=True)
    knee_T_int = int(round(knee_T))

    print(f"[跨T对比] Kneedle 膝点：T≈{knee_T:.2f}（取整T={knee_T_int}）")

    # 画图：time vs T（固定 C_ref）
    plt.figure(figsize=(9.6, 6.2))
    plt.plot(Ts, times, marker="o", label=f"固定实际容量 C_ref={C_ref} 下的最优总耗时")
    plt.axvline(knee_T, linestyle="--")
    ymin, ymax = min(times), max(times)
    plt.text(knee_T, ymin + 0.12 * (ymax - ymin), f"  膝点 T≈{knee_T:.2f}", va="bottom")

    plt.xlabel("分块尺寸 T（只取4的倍数）")
    plt.ylabel("总耗时（clk，实例平均）")
    plt.title("固定实际RAM容量下：总耗时 vs T（寻找T相关膝点）")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(frameon=True)
    plt.tight_layout()
    plt.show()

    return details, knee_T

# =========================
# 12) main
# =========================
if __name__ == "__main__":
    print("[设置] T_LIST =", T_LIST)
    print("[设置] RAM_CAP_LIST（实际容量上限）=", RAM_CAP_LIST)
    print("[设置] 尺寸数量 =", len(SIZES), "范围 =", (min(SIZES), max(SIZES)), "步长≈8")
    print("[设置] INSTANCES_PER_SIZE =", INSTANCES_PER_SIZE)
    print("[设置] CAP_EFFECTIVE_AB =", CAP_EFFECTIVE_AB)

    instances = build_instances(seed=SEED)
    Ms, Ks, Ns, inst_id, n_inst = flatten_instances(instances)
    print("[数据] 实例数 =", n_inst, "层数 =", len(Ms))

    # 1) 每个 T 独立扫描（不混在一起比较），结果全部打印到 log
    results = []
    for T in T_LIST:
        res = run_single_T(T, Ms, Ks, Ns, inst_id, n_inst, RAM_CAP_LIST)
        results.append(res)

    # 2) 计算每个 T 的甜点实际容量（这里甜点点的 Cmax 就是“实际容量上限”）
    sweet_caps = [(r["T"], int(r["sweet"]["Cmax"])) for r in results]
    print("\n===================== [各T甜点的实际RAM容量上限 C_sweet] =====================")
    for T, C in sweet_caps:
        print(f"T={T:>2} | C_sweet={C}")

    # 3) 选取“最大甜点容量”作为统一对比容量
    C_ref = max(C for _, C in sweet_caps)

    # 4) 在固定 C_ref 下，跨 T 比较总耗时，找 T 相关膝点并画图
    compare_T_under_fixed_capacity(results, C_ref)
