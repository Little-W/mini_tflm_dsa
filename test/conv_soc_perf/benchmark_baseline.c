/* SPDX-License-Identifier: Apache-2.0 */
/* Compile the byte-for-byte e8a7337 accelerated Conv snapshot with private
 * symbols. Its 32-row s8 CPU im2col and per-output-row pointwise scheduling
 * are deliberately unchanged. It calls the same production DSA GEMM driver
 * used by the current tree. Do not compile benchmark_baseline_e8.c separately.
 */
#define riscv_convolve_s8_acc benchmark_legacy_convolve_s8
#define riscv_convolve_1x1_s8_acc benchmark_legacy_convolve_1x1_s8
#define riscv_convolve_1x1_s8_fast_acc benchmark_legacy_convolve_1x1_s8_fast
#define riscv_convolve_wrapper_s8_acc benchmark_legacy_convolve_wrapper_s8
#define riscv_convolve_s8_get_buffer_size_acc benchmark_legacy_get_buffer_size
#define riscv_convolve_wrapper_s8_get_buffer_size_acc benchmark_legacy_wrapper_get_buffer_size
#include "benchmark_baseline_e8.c"
