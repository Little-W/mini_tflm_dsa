#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <float.h>

#define TILE 16

// 向上取整除法
int ceil_div(int a, int b) {
    return (a + b - 1) / b;
}

// 计算瓦片数
void tiles_xyz(int M, int K, int N, float *x, float *y, float *z) {
    *x = (float)ceil_div(M, TILE);
    *y = (float)ceil_div(N, TILE);
    *z = (float)ceil_div(K, TILE);
}

// 实数立方根，避免负数变复数
double cbrt_real(double x) {
    return copysign(pow(fabs(x), 1.0/3.0), x);
}

// 解 t^3 + p t + q = 0，返回所有实根
void depressed_cubic_real_roots(double p, double q, double *roots, int *num_roots) {
    double eps = 1e-12;
    double q_half = q * 0.5;
    double p_third = p / 3.0;
    double Delta = q_half * q_half + p_third * p_third * p_third;

    if (Delta > eps) {
        // 一个实根
        double sqrt_delta = sqrt(Delta);
        roots[0] = cbrt_real(-q_half + sqrt_delta) + cbrt_real(-q_half - sqrt_delta);
        *num_roots = 1;
    } else if (fabs(Delta) <= eps) {
        // 重根
        double u = cbrt_real(-q_half);
        roots[0] = 2 * u;
        roots[1] = -u;
        *num_roots = 2;
    } else {
        // 三个实根
        double r = sqrt(-p_third);
        double r_cubed = r * r * r;
        double arg = fmax(-1.0, fmin(1.0, -q_half / r_cubed));
        double phi = acos(arg);

        double two_r = 2.0 * r;
        double phi_third = phi / 3.0;
        double two_pi_third = 2.0943951023931953;  // 2*pi/3

        roots[0] = two_r * cos(phi_third);
        roots[1] = two_r * cos(phi_third + two_pi_third);
        roots[2] = two_r * cos(phi_third + 2 * two_pi_third);
        *num_roots = 3;
    }
}

// 解驻点方程，返回所有实根
void stationary_a_roots(double x, double y, double z, double S, double *a_roots, int *num_a_roots) {
    double X = x * y * z;
    double A = -(X + S) / (2 * y);
    double C = (X * S) / (2 * y);

    double p = -(A * A) / 3;
    double q = 2 * (A * A * A) / 27 + C;

    double t_roots[3];
    int num_t_roots;
    depressed_cubic_real_roots(p, q, t_roots, &num_t_roots);

    *num_a_roots = 0;
    for (int i = 0; i < num_t_roots; i++) {
        double a = t_roots[i] - A / 3;
        // 去重
        int duplicate = 0;
        for (int j = 0; j < *num_a_roots; j++) {
            if (fabs(a - a_roots[j]) < 1e-9) {
                duplicate = 1;
                break;
            }
        }
        if (!duplicate) {
            a_roots[*num_a_roots] = a;
            (*num_a_roots)++;
        }
    }
}

// 访存时间
double mem_time_from_blocks(double B) {
    return (TILE * TILE / 4.0) * B;
}

// 计算基准时间
double comp_time_base(double x, double y, double z) {
    return 47.0 * x * y * z;
}

// IA复用块数
double ia_reuse_blocks(double x, double y, double z, int a, int b) {
    double aa = fmax(1, a);
    double bb = fmax(1, b);
    double p = x / aa;
    double l = y / bb;
    return p * l * z * (2.0 * aa * bb - (aa + bb)) + aa * (l - 1.0);
}

// 计算节省
double comp_time_ia_saved(double x, double y, double z, int a, int b) {
    double aa = fmax(1, a);
    double bb = fmax(1, b);
    double p = x / aa;
    double l = y / bb;
    return p * l * z * ((aa - 1.0) * (31.0 * bb - 15.0)) + 15.0 * (aa - 1.0) * (l - 1.0);
}

// 连续优化ab=S下的整数解，只用WS模式
void continuous_opt_abS(double x, double y, double z, int S, int *best_a, int *best_b, double *best_speedup, double *best_mem_speedup, double *best_comp_speedup) {
    // 计算基准时间
    double B_total = 2.0 * x * y * z;
    double mem_t0 = mem_time_from_blocks(B_total);
    double comp_t0 = comp_time_base(x, y, z);
    double t0 = fmax(mem_t0, comp_t0);

    // 求解连续域候选点
    int a_min = fmax(1, ceil_div(S, (int)ceil(y)));
    int a_max = fmin((int)ceil(x), S);

    // 整数候选集合
    int cand_integer[100][2];  // 假设最多100个候选
    int num_cand = 0;

    // 边界点
    if (a_min <= a_max) {
        for (int i = 0; i < 2; i++) {
            int a = (i == 0) ? a_min : a_max;
            int b = fmin((int)ceil(y), S / a);
            if (b >= 1 && a * b <= S) {
                int duplicate = 0;
                for (int j = 0; j < num_cand; j++) {
                    if (cand_integer[j][0] == a && cand_integer[j][1] == b) {
                        duplicate = 1;
                        break;
                    }
                }
                if (!duplicate) {
                    cand_integer[num_cand][0] = a;
                    cand_integer[num_cand][1] = b;
                    num_cand++;
                }
            }
        }
    } else {
        int a = a_max;
        if (a >= 1) {
            int b = fmin((int)ceil(y), S / a);
            if (b >= 1 && a * b <= S) {
                cand_integer[num_cand][0] = a;
                cand_integer[num_cand][1] = b;
                num_cand++;
            }
        }
    }

    // 驻点
    double a_roots[3];
    int num_a_roots;
    stationary_a_roots(x, y, z, S, a_roots, &num_a_roots);
    for (int i = 0; i < num_a_roots; i++) {
        double a_cont = a_roots[i];
        if (a_min < a_cont && a_cont < a_max) {
            int a_closest = (int)round(a_cont);
            if (a_min <= a_closest && a_closest <= a_max) {
                int b = fmin((int)ceil(y), S / a_closest);
                if (b >= 1 && a_closest * b <= S) {
                    int duplicate = 0;
                    for (int j = 0; j < num_cand; j++) {
                        if (cand_integer[j][0] == a_closest && cand_integer[j][1] == b) {
                            duplicate = 1;
                            break;
                        }
                    }
                    if (!duplicate) {
                        cand_integer[num_cand][0] = a_closest;
                        cand_integer[num_cand][1] = b;
                        num_cand++;
                    }
                }
            }
        }
    }

    // 如果没有候选，添加默认
    if (num_cand == 0) {
        cand_integer[0][0] = 1;
        cand_integer[0][1] = 1;
        num_cand = 1;
    }

    // 评估每个候选
    double best_time = DBL_MAX;
    *best_speedup = 0;
    *best_mem_speedup = 0;
    *best_comp_speedup = 0;
    *best_a = 1;
    *best_b = 1;

    for (int i = 0; i < num_cand; i++) {
        int a = cand_integer[i][0];
        int b = cand_integer[i][1];
        double B_reuse = ia_reuse_blocks(x, y, z, a, b);
        double mem_t1 = mem_time_from_blocks(B_total - B_reuse);
        double comp_save = comp_time_ia_saved(x, y, z, a, b);
        double comp_t1 = fmax(0.0, comp_t0 - comp_save);
        double t1 = fmax(mem_t1, comp_t1);

        if (t1 <= 0) continue;

        double speedup = t0 / t1;

        if (t1 < best_time - 1e-9) {
            best_time = t1;
            *best_speedup = speedup;
            *best_mem_speedup = (mem_t1 > 0) ? (mem_t0 / mem_t1) : 0;
            *best_comp_speedup = (comp_t1 > 0) ? (comp_t0 / comp_t1) : 0;
            *best_a = a;
            *best_b = b;
        } else if (fabs(t1 - best_time) < 1e-9 && a > *best_a) {
            best_time = t1;
            *best_speedup = speedup;
            *best_mem_speedup = (mem_t1 > 0) ? (mem_t0 / mem_t1) : 0;
            *best_comp_speedup = (comp_t1 > 0) ? (comp_t0 / comp_t1) : 0;
            *best_a = a;
            *best_b = b;
        }
    }
}

// 公式贪心法，只用WS模式
void solve_formula_greedy_ws(int M, int K, int N, int Smax, int *best_a, int *best_b, double *best_speedup, double *best_mem_speedup, double *best_comp_speedup) {
    float x, y, z;
    tiles_xyz(M, K, N, &x, &y, &z);
    continuous_opt_abS(x, y, z, Smax, best_a, best_b, best_speedup, best_mem_speedup, best_comp_speedup);
}

// 示例主函数
int main() {
    int M = 100, K = 100, N = 100, S = 16;
    int best_a, best_b;
    double best_speedup, best_mem_speedup, best_comp_speedup;

    solve_formula_greedy_ws(M, K, N, S, &best_a, &best_b, &best_speedup, &best_mem_speedup, &best_comp_speedup);

    printf("Best a: %d, b: %d, speedup: %.4f, mem_speedup: %.4f, comp_speedup: %.4f\n",
           best_a, best_b, best_speedup, best_mem_speedup, best_comp_speedup);

    return 0;
}