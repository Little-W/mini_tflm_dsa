import numpy as np
import math

# 从 opt_calc_check.py 复制必要的函数
TILE = 16

def cbrt_real(x: float) -> float:
    return x**(1/3) if x >= 0 else -((-x)**(1/3))

def depressed_cubic_real_roots(p: float, q: float, eps: float=1e-12):
    Delta = (q/2)**2 + (p/3)**3
    if Delta > eps:
        u = cbrt_real(-q/2 + math.sqrt(Delta))
        v = cbrt_real(-q/2 - math.sqrt(Delta))
        return [u + v]
    if abs(Delta) <= eps:
        u = cbrt_real(-q/2)
        return [2*u, -u]
    r = math.sqrt(-p/3)
    arg = (-q/2) / (r**3)
    arg = max(-1.0, min(1.0, arg))
    phi = math.acos(arg)
    return [2*r*math.cos((phi + 2*math.pi*k)/3) for k in range(3)]

def stationary_a_roots(x, y, z, S):
    X = x*y*z
    A = - (X + S) / (2*y)
    C = (X * S) / (2*y)
    p = - (A*A)/3
    q = 2*(A**3)/27 + C
    t_roots = depressed_cubic_real_roots(p, q)
    a_roots = [t - A/3 for t in t_roots]
    out = []
    for r in a_roots:
        if all(abs(r-u) > 1e-9 for u in out):
            out.append(r)
    return out

def neighbor_candidates(a_cont, b_cont, x, y, S):
    A = [math.floor(a_cont), int(round(a_cont)), math.ceil(a_cont)]
    B = [math.floor(b_cont), int(round(b_cont)), math.ceil(b_cont)]
    xI, yI = int(x), int(y)
    cand = set()
    for a in A:
        for b in B:
            a = int(a); b = int(b)
            if a < 1 or b < 1:
                continue
            a = min(a, min(xI, S))
            b = min(b, min(yI, S))
            if a * b > S:
                b = max(1, min(b, S // a))
            if a >= 1 and b >= 1 and a * b <= S:
                cand.add((a, b))
    out = [(a,b) for (a,b) in cand if 1 <= a <= xI and 1 <= b <= yI and a*b <= S]
    return out

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

def continuous_opt_abS(x, y, z, S):
    # 计算基准时间
    B_total = 2.0 * x * y * z
    mem_t0 = mem_time_from_blocks(B_total, TILE)
    comp_t0 = comp_time_base(x, y, z)
    t0 = max(mem_t0, comp_t0)

    # 求解连续域候选点
    a_min = max(1.0, S / y)
    a_max = min(float(x), float(S))
    
    cand_continuous = []
    if a_min <= a_max:
        cand_continuous.append(a_min)
        cand_continuous.append(a_max)
        for r in stationary_a_roots(x, y, z, S):
            if a_min <= r <= a_max:
                cand_continuous.append(r)
    else:
        cand_continuous.append(min(float(x), float(S)))

    print(f"  连续候选点: {cand_continuous}")

    # 对所有连续候选点取整，生成整数候选集合
    cand_integer = set()
    for a_cont in cand_continuous:
        b_cont = S / a_cont
        print(f"  连续点 a={a_cont:.2f}, b={b_cont:.2f}")
        neighbors = neighbor_candidates(a_cont, b_cont, x, y, S)
        print(f"    邻域整数: {neighbors}")
        for a, b in neighbors:
            cand_integer.add((a, b))
    
    if not cand_integer:
        cand_integer.add((1, 1))

    print(f"  所有整数候选: {sorted(cand_integer)}")

    # 评估每个整数候选
    best_time = float('inf')
    best_speedup = 0
    best_mem_speedup = 0
    best_comp_speedup = 0
    best_a, best_b = 1, 1

    print(f"\n  评估每个候选:")
    for a, b in sorted(cand_integer):
        B_reuse, _ = ia_reuse_blocks(x, y, z, a, b)
        mem_t1 = mem_time_from_blocks(B_total - B_reuse, TILE)
        comp_save = comp_time_ia_saved(x, y, a, b)
        comp_t1 = max(0.0, comp_t0 - comp_save)
        t1 = max(mem_t1, comp_t1)
        speedup = t0 / t1 if t1 > 0 else 0
        mem_speedup = mem_t0 / mem_t1 if mem_t1 > 0 else 0
        comp_speedup = comp_t0 / comp_t1 if comp_t1 > 0 else 0
        
        print(f"    a={a}, b={b}: t1={t1:.2f}, speedup={speedup:.4f}, mem_sp={mem_speedup:.4f}, comp_sp={comp_speedup:.4f}")

        if t1 < best_time and t1 > 0:
            best_time = t1
            best_speedup = speedup
            best_mem_speedup = mem_speedup
            best_comp_speedup = comp_speedup
            best_a, best_b = a, b

    return best_a, best_b, best_speedup, best_mem_speedup, best_comp_speedup

# 测试特殊点 k=1, m=901, n=401
print("=== 测试点: k=1, m=901, n=401, S=16 (IS 模式) ===")
m, k, n, S = 901, 1, 401, 16
x, y, z = tiles_xyz(n, k, m, TILE)  # IS 模式: N, K, M
print(f"Tiles: x={x}, y={y}, z={z}")

a, b, speedup, mem_speedup, comp_speedup = continuous_opt_abS(x, y, z, S)
print(f"\n最终选择: a={a}, b={b}")
print(f"Speedup: {speedup:.4f}")
print(f"Mem Speedup: {mem_speedup:.4f}")
print(f"Comp Speedup: {comp_speedup:.4f}")
print(f"\n期望: a=16, b=1 (暴力法结果)")
