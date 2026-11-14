#include "dsa_accel.h"

static const int16_t lhs[16] = {
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
};
static int8_t rhs[16 * 20];
static volatile int16_t output[20];

int main(void)
{
    dsa_matmul_config_t config;
    dsa_matmul_config_init(&config);
    config.lhs_ptr = lhs;
    config.rhs_ptr = rhs;
    config.dst_ptr = (void *)output;
    config.K = 1;
    config.N = 16;
    config.M = 20;
    config.lhs_row_stride = sizeof(lhs);
    config.rhs_row_stride = 16;
    config.dst_row_stride = sizeof(output);
    config.lhs_dtype = DSA_DTYPE_S16;
    config.rhs_dtype = DSA_DTYPE_S8;
    config.bias_dtype = DSA_DTYPE_S32;
    config.out_dtype = DSA_DTYPE_S16;
    config.dst_mult = 0x40000000;
    config.dst_shift = 0;
    config.act_min = -32768;
    config.act_max = 32767;
    for (unsigned i = 0; i < sizeof(rhs); ++i) rhs[i] = 1;
    for (unsigned i = 0; i < 20; ++i) output[i] = -1;
    if (dsa_matmul_execute(&config) != DSA_SUCCESS) return 2;
    for (unsigned i = 0; i < 20; ++i) {
        if (output[i] != 8) return 3;
    }
    return 1;
}
