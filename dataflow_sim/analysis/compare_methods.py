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

def old_method(x, y, z, Smax):
    """原来的双重循环方法"""
    best_speedup = 0
    best_a, best_b = 1, 1
    
    B_total = 2.0 * x * y * z
    mem_t0 = mem_time_from_blocks(B_total, TILE)
    comp_t0 = comp_time_base(x, y, z)
    t0 = max(mem_t0, comp_t0)
    
    for a in range(1, min(int(x), int(Smax)) + 1):
        for b in range(1, min(int(y), int(Smax)) + 1):
            if a * b > Smax:
                continue
            
            B_reuse, _ = ia_reuse_blocks(x, y, z, a, b)
            mem_t1 = mem_time_from_blocks(B_total - B_reuse, TILE)
            comp_save = comp_time_ia_saved(x, y, a, b)
            comp_t1 = max(0.0, comp_t0 - comp_save)
            t1 = max(mem_t1, comp_t1)
            speedup = (t0 / t1) if t1 > 0 else 0
            
            if speedup > best_speedup:
                best_speedup = speedup
                best_a, best_b = a, b
    
    return best_a, best_b, best_speedup

def new_method(x, y, z, Smax):
    """新的遍历b+计算a的方法"""
    best_speedup = 0
    best_a, best_b = 1, 1
    
    B_total = 2.0 * x * y * z
    mem_t0 = mem_time_from_blocks(B_total, TILE)
    comp_t0 = comp_time_base(x, y, z)
    t0 = max(mem_t0, comp_t0)
    
    for b in range(1, min(int(math.ceil(y)), int(Smax)) + 1):
        a = min(int(math.ceil(x)), Smax // b)
        if a < 1:
            continue
        
        B_reuse, _ = ia_reuse_blocks(x, y, z, a, b)
        mem_t1 = mem_time_from_blocks(B_total - B_reuse, TILE)
        comp_save = comp_time_ia_saved(x, y, a, b)
        comp_t1 = max(0.0, comp_t0 - comp_save)
        t1 = max(mem_t1, comp_t1)
        speedup = (t0 / t1) if t1 > 0 else 0
        
        if speedup > best_speedup:
            best_speedup = speedup
            best_a, best_b = a, b
    
    return best_a, best_b, best_speedup

# 测试案例：k=101, m=401, n=401
print("测试案例: k=101, m=401, n=401, S=16 (WS模式)")
m, k, n, S = 401, 101, 401, 16
x, y, z = tiles_xyz(m, k, n, T=TILE)
print(f"Tiles: x={x}, y={y}, z={z}\n")

old_a, old_b, old_speedup = old_method(x, y, z, S)
print(f"旧方法: a={old_a}, b={old_b}, speedup={old_speedup:.6f}")

new_a, new_b, new_speedup = new_method(x, y, z, S)
print(f"新方法: a={new_a}, b={new_b}, speedup={new_speedup:.6f}")

print(f"\n差异: {abs(old_speedup - new_speedup):.6f}")

if abs(old_speedup - new_speedup) > 1e-6:
    print("\n⚠️ 警告：新方法可能错过了最优解！")
    print("\n详细分析：检查旧方法找到的最优解是否在新方法的搜索空间中")
    print(f"旧方法的最优解: a={old_a}, b={old_b}, ab={old_a*old_b}")
    print(f"当 b={old_b} 时，新方法计算的 a = min({int(math.ceil(x))}, {S}//{old_b}) = {min(int(math.ceil(x)), S // old_b)}")
    
    # 测试所有可能的(a,b)组合，看哪些被新方法遗漏
    print("\n所有 ab<=S 的候选解及其speedup：")
    B_total = 2.0 * x * y * z
    mem_t0 = mem_time_from_blocks(B_total, TILE)
    comp_t0 = comp_time_base(x, y, z)
    t0 = max(mem_t0, comp_t0)
    
    candidates = []
    for a in range(1, min(int(x), int(S)) + 1):
        for b in range(1, min(int(y), int(S)) + 1):
            if a * b > S:
                continue
            B_reuse, _ = ia_reuse_blocks(x, y, z, a, b)
            mem_t1 = mem_time_from_blocks(B_total - B_reuse, TILE)
            comp_save = comp_time_ia_saved(x, y, a, b)
            comp_t1 = max(0.0, comp_t0 - comp_save)
            t1 = max(mem_t1, comp_t1)
            speedup = (t0 / t1) if t1 > 0 else 0
            candidates.append((a, b, speedup))
    
    # 按speedup排序
    candidates.sort(key=lambda x: x[2], reverse=True)
    print("\n前10个最优候选：")
    for i, (a, b, sp) in enumerate(candidates[:10]):
        in_new = (b <= min(int(math.ceil(y)), S) and a == min(int(math.ceil(x)), S // b))
        print(f"  {i+1}. a={a}, b={b}, speedup={sp:.6f} {'✓新方法会选' if in_new else '✗新方法遗漏'}")
else:
    print("\n✅ 两种方法找到相同的最优解")
