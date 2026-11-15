/* SPDX-License-Identifier: Apache-2.0 */
#ifndef CONV_SOC_PERF_BENCHMARK_H
#define CONV_SOC_PERF_BENCHMARK_H

#include <stdint.h>

/* Test-only RAM protocol. All fields below are little-endian 32-bit words;
 * signed fields use two's complement. The SoC loader installs identical
 * tensors and descriptors for each cold-reset run, changing only mode. */
#define BENCH_CONFIG_ADDRESS 0x000a0000u
#define BENCH_CONFIG_MAGIC 0x43565046u
#define BENCH_RESULT_MAGIC 0x43565052u
#define BENCH_ABI_VERSION 1u
#define BENCH_PROGRESS_ADDRESS 0x2000000cu
#define BENCH_PROGRESS_BEGIN 0xc0b10001u
#define BENCH_PROGRESS_END 0xc0b10002u
#define BENCH_MODE_LEGACY 0u
#define BENCH_MODE_HW_WS 1u
#define BENCH_MODE_HW_IS 2u

#ifndef DSA_NN_CONV_DATAFLOW_MODE
#define DSA_NN_CONV_DATAFLOW_MODE 0
#endif

typedef struct {
    uint32_t magic;             /* word 0 */
    uint32_t version;
    uint32_t mode;
    uint32_t case_id;
    uint32_t batches;           /* word 4 */
    uint32_t input_h;
    uint32_t input_w;
    uint32_t input_c;
    uint32_t kernel_h;          /* word 8 */
    uint32_t kernel_w;
    uint32_t group_c;
    uint32_t output_h;
    uint32_t output_w;          /* word 12 */
    uint32_t output_c;
    uint32_t stride_h;
    uint32_t stride_w;
    uint32_t dilation_h;        /* word 16 */
    uint32_t dilation_w;
    uint32_t pad_top;
    uint32_t pad_left;
    int32_t input_offset;       /* word 20 */
    int32_t output_offset;
    int32_t activation_min;
    int32_t activation_max;
    uint32_t input_base;        /* word 24 */
    uint32_t filter_base;
    uint32_t bias_base;
    uint32_t multiplier_base;
    uint32_t shift_base;        /* word 28 */
    uint32_t output_base;
    uint32_t scratch_base;
    uint32_t golden_base;
    uint32_t input_bytes;       /* word 32 */
    uint32_t filter_bytes;
    uint32_t output_bytes;
    uint32_t scratch_bytes;
    uint32_t expected_starts;   /* word 36; checked independently by the TB */
    uint32_t reserved;
} benchmark_config_t;

typedef struct {
    uint32_t magic;             /* word 0 */
    uint32_t version;
    uint32_t complete;
    uint32_t mode;
    uint32_t compiled_dataflow; /* word 4 */
    uint32_t case_id;
    int32_t nmsis_status;
    uint32_t error;
    uint32_t start_cycle;       /* word 8 */
    uint32_t end_cycle;
    uint32_t total_call_cycles;
    uint32_t npu_cycles_last;   /* Conv-only register; UINT32_MAX for legacy */
    uint32_t conv_caps;         /* word 12 */
    uint32_t input_bytes;
    uint32_t filter_bytes;
    uint32_t output_bytes;
    uint32_t scratch_bytes;     /* word 16 */
    uint32_t compared_outputs;
    uint32_t mismatches;
    uint32_t first_mismatch;
    int32_t first_expected;     /* word 20 */
    int32_t first_actual;
    uint32_t output_fnv1a;
    uint32_t guard_errors;
} benchmark_result_t;

enum {
    BENCH_ERROR_NONE = 0,
    BENCH_ERROR_CONFIG = 1,
    BENCH_ERROR_COMPILED_MODE = 2,
    BENCH_ERROR_CAPABILITY = 3,
    BENCH_ERROR_NMSIS = 4,
    BENCH_ERROR_OUTPUT = 5,
    BENCH_ERROR_GUARD = 6
};

extern volatile benchmark_result_t benchmark_result;
int benchmark_run(void);

#endif
