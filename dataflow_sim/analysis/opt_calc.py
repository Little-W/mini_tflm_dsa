import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D


def solve_best_abc(x, y, S):
    """在整数约束下寻找最优的 a, b, c"""
    best_score = -1
    best_abc = (1, 1, 1)

    # 遍历所有可能的 a 和 b
    # 约束：a >= 1, b >= 1, c = S // (a*b) >= 1
    for a in range(1, min(int(x), int(S)) + 1):
        for b in range(1, min(int(y), S // a) + 1):
            c = S // a
            if c < 1: continue

            p, l = x / a, y / b
            # 目标函数公式
            score = p * l * (a * b * (c + 1) - (a * c + b)) + a * c * (l - 1.0)

            if score > best_score:
                best_score = score
                best_abc = (a, b, c)
    return best_score, best_abc


# ==========================================
# 参数设置：扫描 x, y 的范围
# ==========================================
S = 16
size = 30  # 扫描 1 到 30 的网格
x_range = np.arange(1, size + 1)
y_range = np.arange(1, size + 1)

X, Y = np.meshgrid(x_range, y_range)
Z_score = np.zeros(X.shape)
Z_a = np.zeros(X.shape)
Z_b = np.zeros(X.shape)
Z_c = np.zeros(X.shape)

# 执行网格动态搜索
for i in range(len(y_range)):
    for j in range(len(x_range)):
        score, (a, b, c) = solve_best_abc(X[i, j], Y[i, j], S)
        Z_score[i, j] = score
        Z_a[i, j] = a
        Z_b[i, j] = b
        Z_c[i, j] = c

# ==========================================
# 绘制结果图表
# ==========================================
fig = plt.figure(figsize=(16, 12))
plt.rcParams['font.sans-serif'] = ['SimHei']  # 用于显示中文（如果环境支持）
plt.rcParams['axes.unicode_minus'] = False

# 1. B_reuse 最大值得分 (3D)
ax1 = fig.add_subplot(221, projection='3d')
surf = ax1.plot_surface(X, Y, Z_score, cmap='viridis', antialiased=True)
ax1.set_title(f'最大 B_reuse 得分 (S={S})')
ax1.set_xlabel('x')
ax1.set_ylabel('y')
fig.colorbar(surf, ax=ax1, shrink=0.5)

# 2. 最优参数 a 的取值
ax2 = fig.add_subplot(222)
im2 = ax2.imshow(Z_a, origin='lower', extent=[1, size, 1, size], cmap='Reds')
ax2.set_title('最优参数 a')
ax2.set_xlabel('x')
ax2.set_ylabel('y')
fig.colorbar(im2, ax=ax2)

# 3. 最优参数 b 的取值
ax3 = fig.add_subplot(223)
im3 = ax3.imshow(Z_b, origin='lower', extent=[1, size, 1, size], cmap='Blues')
ax3.set_title('最优参数 b')
ax3.set_xlabel('x')
ax3.set_ylabel('y')
fig.colorbar(im3, ax=ax3)

# 4. 最优参数 c 的取值
ax4 = fig.add_subplot(224)
im4 = ax4.imshow(Z_c, origin='lower', extent=[1, size, 1, size], cmap='Greens')
ax4.set_title('最优参数 c')
ax4.set_xlabel('x')
ax4.set_ylabel('y')
fig.colorbar(im4, ax=ax4)

plt.tight_layout()
plt.show()

# 打印部分采样结果供核对
print(f"部分结果采样 (S={S}):")
for test_x, test_y in [(10, 10), (10, 20), (20, 10)]:
    s, (a, b, c) = solve_best_abc(test_x, test_y, S)
    print(f"当 x={test_x}, y={test_y} 时: a={a}, b={b}, c={c} -> B_reuse={s:.2f}")