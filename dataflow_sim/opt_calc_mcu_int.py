"""
MCU整数优化版本 - 面向只有整数运算单元的微控制器
策略：
1. 使用定点数（Q16格式，16位整数+16位小数）
2. 避免浮点、开方、三角函数等复杂运算
3. 使用启发式搜索代替精确求解三次方程
4. 所有运算都是整数加减乘除
"""

# ==========================================
# 定点数配置 (Q16格式: 16位整数部分 + 16位小数部分)
# ==========================================
FIXED_SHIFT = 16  # 小数位数
FIXED_ONE = 1 << FIXED_SHIFT  # 1.0 的定点表示 (65536)
FIXED_HALF = FIXED_ONE >> 1   # 0.5 的定点表示

TILE = 16  # 硬件块大小

# ==========================================
# 定点数运算工具函数（纯整数）
# ==========================================

def int_to_fixed(x):
    """整数转定点数"""
    return x << FIXED_SHIFT

def fixed_to_int(x):
    """定点数转整数（向下取整）"""
    return x >> FIXED_SHIFT

def fixed_mul(a, b):
    """定点数乘法：(a * b) / 2^16"""
    return (a * b) >> FIXED_SHIFT

def fixed_div(a, b):
    """定点数除法：(a * 2^16) / b"""
    if b == 0:
        return 0
    return (a << FIXED_SHIFT) // b

def ceil_div_int(a, b):
    """整数向上取整除法"""
    return (a + b - 1) // b

# ==========================================
# 核心计算函数（整数版本）
# ==========================================

def tiles_xyz_int(M, K, N, T=TILE):
    """计算tile数量，返回定点数"""
    x = int_to_fixed(ceil_div_int(M, T))
    y = int_to_fixed(ceil_div_int(N, T))
    z = int_to_fixed(ceil_div_int(K, T))
    return x, y, z

def mem_time_from_blocks_int(B_fixed, T=TILE):
    """访存时间，输入和输出都是定点数"""
    # mem_time = (T * T / 4) * B = (256 / 4) * B = 64 * B
    time_factor = (T * T) // 4  # 64，整数
    return (time_factor * B_fixed) >> FIXED_SHIFT

def comp_time_base_int(x_fixed, y_fixed, z_fixed):
    """基准计算时间，输入都是定点数"""
    # comp_time = 47 * x * y * z
    xyz = fixed_mul(fixed_mul(x_fixed, y_fixed), z_fixed)
    return (47 * xyz) >> FIXED_SHIFT

def ia_reuse_blocks_int(x_fixed, y_fixed, z_fixed, a, b):
    """
    计算复用块数（定点数版本）
    B_reuse = p * l * z * (2*a*b - (a+b)) + a * (l - 1)
    其中 p = x/a, l = y/b
    """
    if a == 0 or b == 0:
        return 0
    
    # p = x / a （定点数除法）
    p_fixed = fixed_div(x_fixed, int_to_fixed(a))
    # l = y / b
    l_fixed = fixed_div(y_fixed, int_to_fixed(b))
    
    # 2*a*b - (a+b)
    factor1 = 2 * a * b - (a + b)
    
    # p * l * z * factor1
    term1 = fixed_mul(p_fixed, l_fixed)
    term1 = fixed_mul(term1, z_fixed)
    term1 = fixed_mul(term1, int_to_fixed(factor1))
    
    # a * (l - 1)
    l_minus_1 = l_fixed - FIXED_ONE
    term2 = fixed_mul(int_to_fixed(a), l_minus_1)
    
    return term1 + term2

def comp_time_ia_saved_int(x_fixed, y_fixed, z_fixed, a, b):
    """
    计算节省的计算时间（定点数版本）
    save = p * l * z * ((a-1) * (31*b - 15)) + 15 * (a-1) * (l-1)
    """
    if a == 0 or b == 0:
        return 0
    
    p_fixed = fixed_div(x_fixed, int_to_fixed(a))
    l_fixed = fixed_div(y_fixed, int_to_fixed(b))
    
    # (a-1) * (31*b - 15)
    factor1 = (a - 1) * (31 * b - 15)
    
    # p * l * z * factor1
    term1 = fixed_mul(p_fixed, l_fixed)
    term1 = fixed_mul(term1, z_fixed)
    term1 = fixed_mul(term1, int_to_fixed(factor1))
    
    # 15 * (a-1) * (l-1)
    l_minus_1 = l_fixed - FIXED_ONE
    term2 = fixed_mul(int_to_fixed(15 * (a - 1)), l_minus_1)
    
    return term1 + term2

# ==========================================
# MCU启发式优化算法（整数版本）
# ==========================================

def mcu_heuristic_search(M, K, N, Smax):
    """
    MCU启发式搜索算法：
    1. 不求解三次方程（避免开方、三角函数）
    2. 使用智能搜索策略：从理论最优点附近开始搜索
    3. 纯整数运算
    
    返回：(最佳a, 最佳b, 模式, speedup的定点表示)
    """
    best_speedup_fixed = 0
    best_a, best_b = 1, 1
    best_mode = 'WS'
    
    for mode in ['WS', 'IS']:
        if mode == 'WS':
            x, y, z = tiles_xyz_int(M, K, N, TILE)
        else:
            x, y, z = tiles_xyz_int(N, K, M, TILE)
        
        # 计算基准时间（定点数）
        B_total_fixed = fixed_mul(int_to_fixed(2), fixed_mul(x, fixed_mul(y, z)))
        mem_t0 = mem_time_from_blocks_int(B_total_fixed, TILE)
        comp_t0 = comp_time_base_int(x, y, z)
        t0 = max(mem_t0, comp_t0)
        
        if t0 == 0:
            continue
        
        # 使用简化的搜索策略：遍历b，对每个b计算最大a
        x_int = fixed_to_int(x)
        y_int = fixed_to_int(y)
        
        # 遍历所有可能的b值（更全面但仍然高效）
        b_max_limit = min(y_int, Smax)
        
        for b in range(1, b_max_limit + 1):
            # 对于每个b，计算最大可能的a
            a = min(x_int, Smax // b)
            if a < 1:
                continue
            
            # 计算复用和加速比
            B_reuse_fixed = ia_reuse_blocks_int(x, y, z, a, b)
            mem_t1 = mem_time_from_blocks_int(B_total_fixed - B_reuse_fixed, TILE)
            
            comp_save_fixed = comp_time_ia_saved_int(x, y, z, a, b)
            comp_t1 = max(0, comp_t0 - comp_save_fixed)
            
            t1 = max(mem_t1, comp_t1)
            
            if t1 <= 0:
                continue
            
            # speedup = t0 / t1 （定点数除法）
            speedup_fixed = fixed_div(t0, t1)
            
            # 更新最佳解（优先speedup，其次a更大）
            if speedup_fixed > best_speedup_fixed:
                best_speedup_fixed = speedup_fixed
                best_a, best_b = a, b
                best_mode = mode
            elif speedup_fixed == best_speedup_fixed and a > best_a:
                best_a, best_b = a, b
                best_mode = mode
    
    return best_a, best_b, best_mode, best_speedup_fixed

def int_sqrt_approx(n):
    """
    整数平方根近似（牛顿迭代法，纯整数）
    适合MCU，不需要浮点运算
    """
    if n <= 1:
        return n
    
    # 初始估计：从最高位开始
    x = n
    while True:
        x1 = (x + n // x) >> 1  # x1 = (x + n/x) / 2
        if x1 >= x:
            return x
        x = x1

# ==========================================
# 测试和对比
# ==========================================

def test_mcu_vs_original():
    """测试MCU整数版本与原始浮点版本的对比"""
    import time
    
    # 导入原始浮点版本（假设在同一目录）
    from opt_calc_check import solve_brute_force
    
    test_cases = [
        (256, 256, 256, 16),
        (512, 512, 512, 16),
        (1024, 1024, 1024, 16),
        (128, 512, 256, 16),
        (2000, 2000, 2000, 16),
    ]
    
    print("=" * 80)
    print("MCU整数版本 vs 原始浮点版本对比")
    print("=" * 80)
    print(f"{'M':>6} {'K':>6} {'N':>6} | {'MCU_a':>5} {'MCU_b':>5} {'Mode':>4} {'Speedup':>8} | {'Float_a':>7} {'Float_b':>7} {'Mode':>4} {'Speedup':>8} | {'a匹配':>6} {'b匹配':>6}")
    print("-" * 80)
    
    total_match = 0
    total_time_mcu = 0
    total_time_float = 0
    
    for M, K, N, S in test_cases:
        # MCU整数版本
        start = time.time()
        a_mcu, b_mcu, mode_mcu, speedup_mcu_fixed = mcu_heuristic_search(M, K, N, S)
        time_mcu = time.time() - start
        total_time_mcu += time_mcu
        
        # 转换speedup为浮点数显示
        speedup_mcu = speedup_mcu_fixed / FIXED_ONE
        
        # 原始浮点版本
        start = time.time()
        speedup_float, _, _, (a_float, b_float, mode_float) = solve_brute_force(M, K, N, S)
        time_float = time.time() - start
        total_time_float += time_float
        
        # 检查匹配
        a_match = "✓" if a_mcu == a_float else "✗"
        b_match = "✓" if b_mcu == b_float else "✗"
        
        if a_mcu == a_float and b_mcu == b_float:
            total_match += 1
        
        print(f"{M:>6} {K:>6} {N:>6} | {a_mcu:>5} {b_mcu:>5} {mode_mcu:>4} {speedup_mcu:>8.4f} | {a_float:>7} {b_float:>7} {mode_float:>4} {speedup_float:>8.4f} | {a_match:>6} {b_match:>6}")
    
    print("-" * 80)
    print(f"匹配率: {total_match}/{len(test_cases)} ({100*total_match/len(test_cases):.1f}%)")
    print(f"MCU总时间: {total_time_mcu*1000:.3f} ms (平均 {total_time_mcu*1000/len(test_cases):.3f} ms/点)")
    print(f"浮点总时间: {total_time_float*1000:.3f} ms (平均 {total_time_float*1000/len(test_cases):.3f} ms/点)")
    if total_time_float > 0:
        print(f"速度比: MCU/Float = {total_time_mcu/total_time_float:.2f}x")
    else:
        print(f"速度比: 浮点版本时间过短，无法精确测量")
    print("=" * 80)

# ==========================================
# MCU C代码生成（参考）
# ==========================================

def generate_c_code():
    """生成可在MCU上运行的C代码"""
    c_code = """
/* MCU整数优化算法 - C语言实现 */
#include <stdint.h>

#define FIXED_SHIFT 16
#define FIXED_ONE (1 << FIXED_SHIFT)
#define TILE 16

typedef int32_t fixed_t;  // 定点数类型

/* 定点数乘法 */
static inline fixed_t fixed_mul(fixed_t a, fixed_t b) {
    return ((int64_t)a * b) >> FIXED_SHIFT;
}

/* 定点数除法 */
static inline fixed_t fixed_div(fixed_t a, fixed_t b) {
    if (b == 0) return 0;
    return ((int64_t)a << FIXED_SHIFT) / b;
}

/* 整数平方根（牛顿法）*/
static uint32_t int_sqrt(uint32_t n) {
    if (n <= 1) return n;
    uint32_t x = n;
    while (1) {
        uint32_t x1 = (x + n / x) >> 1;
        if (x1 >= x) return x;
        x = x1;
    }
}

/* MCU优化算法主函数 */
void mcu_optimize(uint16_t M, uint16_t K, uint16_t N, uint16_t Smax,
                  uint16_t *out_a, uint16_t *out_b, uint8_t *out_mode) {
    fixed_t best_speedup = 0;
    *out_a = 1;
    *out_b = 1;
    *out_mode = 0;  // 0=WS, 1=IS
    
    for (uint8_t mode = 0; mode < 2; mode++) {
        // 计算tile数量
        uint16_t x_int = (mode == 0) ? ((M + TILE - 1) / TILE) : ((N + TILE - 1) / TILE);
        uint16_t y_int = (N + TILE - 1) / TILE;
        uint16_t z_int = (K + TILE - 1) / TILE;
        
        fixed_t x = (fixed_t)x_int << FIXED_SHIFT;
        fixed_t y = (fixed_t)y_int << FIXED_SHIFT;
        fixed_t z = (fixed_t)z_int << FIXED_SHIFT;
        
        // 计算基准时间
        fixed_t xyz = fixed_mul(fixed_mul(x, y), z);
        fixed_t B_total = xyz << 1;  // 2 * x * y * z
        fixed_t mem_t0 = (64L * B_total) >> FIXED_SHIFT;
        fixed_t comp_t0 = (47L * xyz) >> FIXED_SHIFT;
        fixed_t t0 = (mem_t0 > comp_t0) ? mem_t0 : comp_t0;
        
        if (t0 == 0) continue;
        
        // 智能搜索
        uint16_t a_start = int_sqrt(x_int);
        if (a_start < 1) a_start = 1;
        
        uint16_t a_min = (a_start > 1) ? (a_start >> 1) : 1;
        uint16_t a_max = (x_int < Smax) ? x_int : Smax;
        if (a_start * 2 < a_max) a_max = a_start * 2;
        
        uint16_t a_step = ((a_max - a_min) / 20) + 1;
        
        for (uint16_t a = a_min; a <= a_max; a += a_step) {
            uint16_t b = (y_int < (Smax / a)) ? y_int : (Smax / a);
            if (b < 1) continue;
            
            // 计算复用和加速比（简化版本）
            fixed_t p = fixed_div(x, (fixed_t)a << FIXED_SHIFT);
            fixed_t l = fixed_div(y, (fixed_t)b << FIXED_SHIFT);
            
            int32_t factor1 = 2 * a * b - (a + b);
            fixed_t term1 = fixed_mul(fixed_mul(p, l), z);
            fixed_t B_reuse = ((int64_t)term1 * factor1) >> FIXED_SHIFT;
            
            fixed_t mem_t1 = (64L * (B_total - B_reuse)) >> FIXED_SHIFT;
            
            int32_t comp_factor = (a - 1) * (31 * b - 15);
            fixed_t comp_save = ((int64_t)term1 * comp_factor) >> FIXED_SHIFT;
            fixed_t comp_t1 = (comp_t0 > comp_save) ? (comp_t0 - comp_save) : 0;
            
            fixed_t t1 = (mem_t1 > comp_t1) ? mem_t1 : comp_t1;
            if (t1 <= 0) continue;
            
            fixed_t speedup = fixed_div(t0, t1);
            
            if (speedup > best_speedup) {
                best_speedup = speedup;
                *out_a = a;
                *out_b = b;
                *out_mode = mode;
            }
        }
    }
}
"""
    
    with open('mcu_optimize.c', 'w', encoding='utf-8') as f:
        f.write(c_code)
    
    print("MCU C代码已生成: mcu_optimize.c")

if __name__ == "__main__":
    # 运行测试
    test_mcu_vs_original()
    
    print("\n生成MCU C代码...")
    generate_c_code()
    
    print("\n" + "=" * 80)
    print("MCU整数实现要点总结：")
    print("=" * 80)
    print("1. 使用Q16定点数（16位整数+16位小数）替代浮点数")
    print("2. 避免开方、三角函数，使用整数牛顿迭代法求平方根")
    print("3. 不求解三次方程，使用智能启发式搜索")
    print("4. 所有运算都是整数：加减乘除和位移")
    print("5. 内存占用小，适合资源受限的MCU")
    print("6. 速度快，适合实时优化场景")
    print("=" * 80)
