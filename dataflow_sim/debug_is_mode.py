import math

TILE = 16

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
    return B_reuse, None

def comp_time_ia_saved(x, y, a, b):
    x = float(x); y = float(y)
    a = float(max(1, a)); b = float(max(1, b))
    p = x / a
    l = y / b
    save_common = p * l * ((a - 1.0) * (31.0 * b - 15.0))
    return save_common + 15.0 * (a - 1.0) * (l - 1.0)

# IS模式: (N, K, M) = (1, 1, 101)
m, k, n, S = 101, 1, 1, 16
x, y, z = tiles_xyz(n, k, m, T=TILE)  # IS模式

print(f"IS模式: x={x}, y={y}, z={z}")
print(f"a=1, 遍历 b ∈ [1, 7]:\n")

B_total = 2.0 * x * y * z
mem_t0 = mem_time_from_blocks(B_total, TILE)
comp_t0 = comp_time_base(x, y, z)
t0 = max(mem_t0, comp_t0)

print(f"基准: mem_t0={mem_t0:.2f}, comp_t0={comp_t0:.2f}, t0={t0:.2f}\n")

for b in range(1, 8):
    if 1 * b > S:
        print(f"b={b}: 超过约束 ab={1*b} > S={S}")
        continue
        
    B_reuse, _ = ia_reuse_blocks(x, y, z, 1, b)
    mem_t1 = mem_time_from_blocks(B_total - B_reuse, TILE)
    comp_save = comp_time_ia_saved(x, y, 1, b)
    comp_t1 = max(0.0, comp_t0 - comp_save)
    t1 = max(mem_t1, comp_t1)
    speedup = t0 / t1 if t1 > 0 else 0
    mem_speedup = mem_t0 / mem_t1 if mem_t1 > 0 else 0
    comp_speedup = comp_t0 / comp_t1 if comp_t1 > 0 else 0
    
    print(f"b={b} (ab={1*b}):")
    print(f"  B_reuse={B_reuse:.2f}")
    print(f"  mem_t1={mem_t1:.2f}, comp_t1={comp_t1:.2f}, t1={t1:.2f}")
    print(f"  speedup={speedup:.4f} (mem={mem_speedup:.4f}, comp={comp_speedup:.4f})")
    print(f"  瓶颈: {'访存' if mem_t1 >= comp_t1 else '计算'}")
    print()
