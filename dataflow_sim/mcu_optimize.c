
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
