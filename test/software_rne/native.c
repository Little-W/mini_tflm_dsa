/* SPDX-License-Identifier: Apache-2.0 */
#include "riscv_nnsupportfunctions.h"
int32_t check_nmsis_requant(int32_t x, int32_t m, int s) { return riscv_nn_requantize(x,m,s); }
int32_t check_nmsis_s64(int64_t x, int32_t m, int s) { return riscv_nn_requantize_s64(x,m,s); }
int32_t check_nmsis_reduce(int32_t m) { return REDUCE_MULTIPLIER(m); }
int32_t check_nmsis_divide(int64_t x, int d) { return riscv_nn_divide_rne(x,d); }
int32_t check_nmsis_offset(int32_t x, int o) { return riscv_nn_add_s32_sat(x,o); }
