#include "dsa_accel.h"

static int8_t lhs[16 * 16] __attribute__((aligned(16)));
static int8_t rhs[16 * 16] __attribute__((aligned(16)));
static volatile int8_t output[16 * 16] __attribute__((aligned(16)));

int main(void)
{
    dsa_matmul_config_t config;
    dsa_matmul_config_init(&config);
    for (unsigned i = 0; i < 16 * 16; ++i) {
        lhs[i] = 1;
        rhs[i] = 1;
        output[i] = 0;
    }
    config.lhs_ptr = lhs;
    config.rhs_ptr = rhs;
    config.dst_ptr = (void *)output;
    config.K = 16;
    config.N = 16;
    config.M = 16;
    config.lhs_row_stride = 16;
    config.rhs_row_stride = 16;
    config.dst_row_stride = 16;
    config.lhs_dtype = DSA_DTYPE_S8;
    config.rhs_dtype = DSA_DTYPE_S8;
    config.out_dtype = DSA_DTYPE_S8;
    config.dst_mult = 0x7fffffff;
    config.dst_shift = 0;
    config.act_min = -128;
    config.act_max = 127;
    if (dsa_matmul_execute(&config) != DSA_SUCCESS) return 2;
    for (unsigned i = 0; i < 16 * 16; ++i)
        if (output[i] != 16) return 3;
    return 1;
}
