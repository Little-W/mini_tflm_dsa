import numpy as np
import matplotlib.pyplot as plt

# ---- 字体与字号（PPT 友好）----
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Noto Sans CJK SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 16
plt.rcParams["axes.titlesize"] = 18
plt.rcParams["axes.labelsize"] = 16
plt.rcParams["legend.fontsize"] = 14
plt.rcParams["xtick.labelsize"] = 14
plt.rcParams["ytick.labelsize"] = 14

def gaussian_smooth(y, sigma_bins: float = 1.4):
    radius = int(np.ceil(4 * sigma_bins))
    x = np.arange(-radius, radius + 1)
    k = np.exp(-0.5 * (x / sigma_bins) ** 2)
    k /= k.sum()
    return np.convolve(y, k, mode="same")

def weighted_density(values, weights, bins=90, smooth_sigma_bins=1.4, pad_decades=0.3):
    v = np.asarray(values, float)
    w = np.asarray(weights, float)
    vmin = max(v.min(), 1e-12)
    vmax = max(v.max(), vmin * 1.0001)

    edges = np.logspace(np.log10(vmin) - pad_decades, np.log10(vmax) + pad_decades, bins + 1)
    centers = np.sqrt(edges[:-1] * edges[1:])  # 几何中心（适配 log 轴）
    hist, _ = np.histogram(v, bins=edges, weights=w, density=False)

    total = hist.sum()
    p = hist / total if total > 0 else np.zeros_like(hist, dtype=float)
    p = gaussian_smooth(p, smooth_sigma_bins)
    p /= p.sum() + 1e-12
    return centers, p

# ----------------- 打印到 log：当前设置大前提 -----------------
H0, W0 = 224, 224
downsample_count = 5
expansion_t = 6
use_k5_dw = False          # MobileNetV2 典型为 DW 3x3
mac_weighted = True        # MAC 加权更贴近热点

print("[设置] 示例模型：MobileNetV2 风格（示意）")
print(f"[设置] 输入尺寸：{H0}×{W0}")
print(f"[设置] stride=2 下采样次数（近似）：{downsample_count}（~7×7）")
print(f"[设置] MBConv 扩张倍率 t：{expansion_t}")
print(f"[设置] Depthwise 核：{'含 5×5' if use_k5_dw else '仅 3×3'}")
print(f"[设置] 统计权重：{'MAC=M·K·N 加权' if mac_weighted else '每层均匀'}")

# ----------------- MobileNetV2 风格代表性 stage（用于示例分布） -----------------
# (Hout, Wout, Cin, Cout, repeats) —— 只用于生成“典型分布”，不追求逐层完全精确
stage_specs = [
    (112, 112, 32, 16, 1),
    (56,  56, 16, 24, 2),
    (28,  28, 24, 32, 3),
    (14,  14, 32, 64, 4),
    (7,    7, 64, 160, 3),
]

# ----------------- 生成代表性 op 列表 -----------------
ops = []  # (M, K, N, weight)

# Stem 3x3: Cin=3 -> 32 at 112x112
M = 112 * 112
K = 3 * 3 * 3
N = 32
w = M * K * N if mac_weighted else 1.0
ops.append((M, K, N, w))

for H, W, Cin0, Cout0, repeats in stage_specs:
    M = H * W
    for i in range(repeats):
        Cin = Cin0 if i == 0 else Cout0
        Cout = Cout0

        # 1x1 Expand
        K = Cin
        N = expansion_t * Cin
        w = M * K * N if mac_weighted else 1.0
        ops.append((M, K, N, w))

        # DW 3x3
        K = 9
        N = expansion_t * Cin
        w = M * K * N if mac_weighted else 1.0
        ops.append((M, K, N, w))

        # 1x1 Project
        K = expansion_t * Cin
        N = Cout
        w = M * K * N if mac_weighted else 1.0
        ops.append((M, K, N, w))

# Final 1x1 + FC（常见尾部）
M, K, N = 7 * 7, 160, 1280
w = M * K * N if mac_weighted else 1.0
ops.append((M, K, N, w))

M, K, N = 1, 1280, 1000
w = M * K * N if mac_weighted else 1.0
ops.append((M, K, N, w))

M_vals = np.array([o[0] for o in ops], float)
K_vals = np.array([o[1] for o in ops], float)
N_vals = np.array([o[2] for o in ops], float)
weights = np.array([o[3] for o in ops], float)

# ----------------- 分布（原始数值 + 对数坐标）-----------------
xM, pM = weighted_density(M_vals, weights)
xK, pK = weighted_density(K_vals, weights)
xN, pN = weighted_density(N_vals, weights)

# ----------------- 绘图 -----------------
plt.figure(figsize=(12.0, 6.8))
ax = plt.gca()

ax.plot(xM, pM, linewidth=3, label="M：输出空间位置数（Hout·Wout）")
ax.fill_between(xM, 0, pM, alpha=0.18)

ax.plot(xK, pK, linewidth=3, label="K：展开维度（Cin·Kh·Kw；DW 为 Kh·Kw）")
ax.fill_between(xK, 0, pK, alpha=0.18)

ax.plot(xN, pN, linewidth=3, label="N：输出通道数（Cout）")
ax.fill_between(xN, 0, pN, alpha=0.18)

ax.set_xscale("log")
ax.set_xlabel("数值")
ax.set_ylabel("概率（平滑后）")

ax.set_title("MobileNet 示例：M/K/N 分布")
ax.grid(True, which="both", linestyle="--", alpha=0.5)
ax.legend(frameon=True, loc="upper right")

# ---- 峰值标注（原始数值）----
ymax = ax.get_ylim()[1]
y_anno_M = ymax * 0.06
y_anno_K = ymax * 0.10

# M 峰值：112²/56²/28²/14²/7²
for v in [112*112, 56*56, 28*28, 14*14, 7*7]:
    ax.text(v, y_anno_M, f"{v}", ha="center", va="bottom", fontsize=14)

# K 峰值：DW 3x3
ax.text(9, y_anno_K, "9", ha="center", va="bottom", fontsize=14)

plt.tight_layout()
plt.show()
