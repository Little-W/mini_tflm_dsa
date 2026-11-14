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

def solve_brute_force_single_mode(x, y, z, Smax):
    """单个模式的暴力搜索，返回所有达到最优的解"""
    best_speedup = 0
    best_solutions = []
    
    B_total = 2.0 * x * y * z
    mem_t0 = mem_time_from_blocks(B_total, T=TILE)
    comp_t0 = comp_time_base(x, y, z)
    t0 = max(mem_t0, comp_t0)

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

            if speedup > best_speedup + 1e-6:
                best_speedup = speedup
                best_solutions = [(a, b, speedup, mem_speedup, comp_speedup, mem_t1, comp_t1, t1)]
            elif abs(speedup - best_speedup) < 1e-6:
                best_solutions.append((a, b, speedup, mem_speedup, comp_speedup, mem_t1, comp_t1, t1))

    return best_solutions

# 测试一个具体例子
print("=== 寻找有多个等效解的案例（访存/计算时间不同但总时间相近）===\n")

# 遍历找到有多个最优解的点，且这些解的访存/计算时间不同
found_count = 0
for k in [1, 101, 201]:
    for m in [101, 201, 301, 401, 501]:
        for n in [101, 201, 301, 401]:
            x, y, z = tiles_xyz(m, k, n, T=TILE)
            solutions = solve_brute_force_single_mode(x, y, z, 16)
            
            if len(solutions) > 1:
                # 检查是否有解的访存或计算时间不同
                has_diff = False
                for i in range(len(solutions) - 1):
                    mem_t1, comp_t1 = solutions[i][5], solutions[i][6]
                    mem_t2, comp_t2 = solutions[i+1][5], solutions[i+1][6]
                    if abs(mem_t1 - mem_t2) > 1 or abs(comp_t1 - comp_t2) > 1:
                        has_diff = True
                        break
                
                if has_diff:
                    print(f"找到案例: k={k}, m={m}, n={n}")
                    print(f"Tiles: x={x}, y={y}, z={z}")
                    print(f"找到 {len(solutions)} 个等效最优解:\n")
                    
                    for i, (a, b, speedup, mem_sp, comp_sp, mem_t, comp_t, t) in enumerate(solutions):
                        print(f"解{i+1}: a={a}, b={b}")
                        print(f"  总speedup = {speedup:.4f}")
                        print(f"  访存speedup = {mem_sp:.4f}, 访存时间 = {mem_t:.2f}")
                        print(f"  计算speedup = {comp_sp:.4f}, 计算时间 = {comp_t:.2f}")
                        print(f"  瓶颈时间 = {t:.2f} ({'访存' if mem_t >= comp_t else '计算'})")
                        print()
                    
                    found_count += 1
                    if found_count >= 3:  # 找3个例子
                        break
        if found_count >= 3:
            break
    if found_count >= 3:
        break

if found_count == 0:
    print("在测试范围内未找到符合条件的案例")

print("\n=== 分析：为什么会有访存/计算speedup差异 ===")
print("""
当两个不同的参数组合 (a1,b1) 和 (a2,b2) 产生相同的总时间时：
- t1 = max(mem_t1, comp_t1)
- t2 = max(mem_t2, comp_t2)
- 如果 t1 ≈ t2，则总speedup相同

但是：
- mem_t1 可能不等于 mem_t2 → 访存speedup不同
- comp_t1 可能不等于 comp_t2 → 计算speedup不同

这是正常现象，说明存在多个参数组合能达到相同的最优性能。
暴力法和公式法可能选择不同的等效解，但总speedup相同。
""")