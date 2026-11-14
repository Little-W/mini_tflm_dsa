import numpy as np
import math

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
    B_total = 2.0 * x * y * z
    mem_t0 = mem_time_from_blocks(B_total, TILE)
    comp_t0 = comp_time_base(x, y, z)
    t0 = max(mem_t0, comp_t0)

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

    cand_integer = set()
    for a_cont in cand_continuous:
        b_cont = S / a_cont
        neighbors = neighbor_candidates(a_cont, b_cont, x, y, S)
        for a, b in neighbors:
            cand_integer.add((a, b))
    
    if not cand_integer:
        cand_integer.add((1, 1))

    best_time = float('inf')
    best_speedup = 0
    best_mem_speedup = 0
    best_comp_speedup = 0
    best_a, best_b = 1, 1

    for a, b in cand_integer:
        B_reuse, _ = ia_reuse_blocks(x, y, z, a, b)
        mem_t1 = mem_time_from_blocks(B_total - B_reuse, TILE)
        comp_save = comp_time_ia_saved(x, y, a, b)
        comp_t1 = max(0.0, comp_t0 - comp_save)
        t1 = max(mem_t1, comp_t1)

        if t1 < best_time and t1 > 0:
            best_time = t1
            best_speedup = t0 / t1
            best_mem_speedup = (mem_t0 / mem_t1) if mem_t1 > 0 else 0
            best_comp_speedup = (comp_t0 / comp_t1) if comp_t1 > 0 else 0
            best_a, best_b = a, b

    return best_a, best_b, best_speedup, best_mem_speedup, best_comp_speedup

def solve_brute_force_single_mode(M, K, N, Smax, mode):
    """单个模式的暴力搜索"""
    if mode == 'WS':
        x, y, z = tiles_xyz(M, K, N, T=TILE)
    else:
        x, y, z = tiles_xyz(N, K, M, T=TILE)

    best_speedup = 0
    best_mem_speedup = 0
    best_comp_speedup = 0
    best_a, best_b = 1, 1

    B_total = 2.0 * x * y * z
    mem_t0 = mem_time_from_blocks(B_total, T=TILE)
    comp_t0 = comp_time_base(x, y, z)
    t0 = max(mem_t0, comp_t0)

    print(f"  {mode}模式: x={x}, y={y}, z={z}")
    print(f"    遍历范围: a ∈ [1, {min(int(x), int(Smax))}], b ∈ [1, {min(int(y), int(Smax))}]")
    print(f"    基准时间: mem_t0={mem_t0:.2f}, comp_t0={comp_t0:.2f}, t0={t0:.2f}")

    for a in range(1, min(int(x), int(Smax)) + 1):
        for b in range(1, min(int(y), int(Smax)) + 1):
            if a * b > Smax:
                continue

            B_reuse, _ = ia_reuse_blocks(x, y, z, a, b)
            mem_t1 = mem_time_from_blocks(B_total - B_reuse, T=TILE)
            comp_save = comp_time_ia_saved(x, y, a, b)
            comp_t1 = max(0.0, comp_t0 - comp_save)
            t1 = max(mem_t1, comp_t1)
            speedup = (t0 / t1) if t1 > 0 else 0
            mem_speedup = (mem_t0 / mem_t1) if mem_t1 > 0 else 0
            comp_speedup = (comp_t0 / comp_t1) if comp_t1 > 0 else 0

            if speedup > best_speedup:
                best_speedup = speedup
                best_mem_speedup = mem_speedup
                best_comp_speedup = comp_speedup
                best_a, best_b = a, b

    print(f"    最优解: a={best_a}, b={best_b}, speedup={best_speedup:.4f}")
    print(f"    访存speedup={best_mem_speedup:.4f}, 计算speedup={best_comp_speedup:.4f}\n")
    
    return best_speedup, best_mem_speedup, best_comp_speedup, best_a, best_b

def solve_formula_single_mode(M, K, N, Smax, mode):
    """单个模式的公式求解"""
    if mode == 'WS':
        x, y, z = tiles_xyz(M, K, N, TILE)
    else:
        x, y, z = tiles_xyz(N, K, M, TILE)

    print(f"  {mode}模式: x={x}, y={y}, z={z}")
    a, b, speedup, mem_speedup, comp_speedup = continuous_opt_abS(x, y, z, Smax)
    print(f"    最优解: a={a}, b={b}, speedup={speedup:.4f}")
    print(f"    访存speedup={mem_speedup:.4f}, 计算speedup={comp_speedup:.4f}\n")
    
    return speedup, mem_speedup, comp_speedup, a, b

# 测试案例：k=1, m=101, n=1
print("=" * 60)
print("测试案例: k=1, m=101, n=1, S=16")
print("=" * 60)

m, k, n, S = 101, 1, 1, 16

print("\n【暴力法】")
print("WS模式 (M, K, N) = (101, 1, 1):")
bf_ws_speedup, bf_ws_mem, bf_ws_comp, bf_ws_a, bf_ws_b = solve_brute_force_single_mode(m, k, n, S, 'WS')

print("IS模式 (N, K, M) = (1, 1, 101):")
bf_is_speedup, bf_is_mem, bf_is_comp, bf_is_a, bf_is_b = solve_brute_force_single_mode(m, k, n, S, 'IS')

bf_best_mode = 'WS' if bf_ws_speedup >= bf_is_speedup else 'IS'
print(f"暴力法最终选择: {bf_best_mode}模式")

print("\n【公式法】")
print("WS模式 (M, K, N) = (101, 1, 1):")
fm_ws_speedup, fm_ws_mem, fm_ws_comp, fm_ws_a, fm_ws_b = solve_formula_single_mode(m, k, n, S, 'WS')

print("IS模式 (N, K, M) = (1, 1, 101):")
fm_is_speedup, fm_is_mem, fm_is_comp, fm_is_a, fm_is_b = solve_formula_single_mode(m, k, n, S, 'IS')

fm_best_mode = 'WS' if fm_ws_speedup >= fm_is_speedup else 'IS'
print(f"公式法最终选择: {fm_best_mode}模式")

print("\n" + "=" * 60)
print("对比结果:")
print("=" * 60)
print(f"暴力法: {bf_best_mode}模式, speedup={max(bf_ws_speedup, bf_is_speedup):.4f}")
print(f"公式法: {fm_best_mode}模式, speedup={max(fm_ws_speedup, fm_is_speedup):.4f}")
print(f"两种方法选择的模式是否一致: {bf_best_mode == fm_best_mode}")
