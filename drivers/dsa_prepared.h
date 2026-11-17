/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_PREPARED_H
#define DSA_PREPARED_H

#include <stdint.h>
#include "dsa_conv.h"
#include "dsa_vector.h"

#ifdef __cplusplus
extern "C" {
#endif

#ifndef DSA_NN_PREPARED_ENABLE
#define DSA_NN_PREPARED_ENABLE 1
#endif
#define DSA_PREPARED_VALID 0x50525031u
#define DSA_PREPARED_MAX_REGISTERS 36u

/* Prepared descriptors and their constant tensors remain immutable until
 * invalidation. Preparing does not require activation addresses. Execution
 * binds fresh activation addresses and checks their full DMA spans. Device
 * replacement or a change to shapes, weights, bias or quantization requires
 * invalidation and preparation before another execution. */
typedef struct {
    uint32_t valid, input_bytes, output_bytes, ctrl;
    uint32_t spatial, register_count, readonly_count;
    uint32_t source_filter_base;
    uint32_t memory_policy_valid, ps_control, ia_bank_count;
    struct { uint32_t begin, end; } readonly[4];
    struct { uint32_t offset, value; } registers[DSA_PREPARED_MAX_REGISTERS];
} dsa_prepared_t;

/* Dense int8 GEMM: input [rows, depth], OHWI-compatible weights
 * [channels, depth], output [rows, channels]. Strides are bytes. */
typedef struct {
    uint32_t filter_base, bias_base, multiplier_base, shift_base;
    uint32_t rows, depth, channels;
    uint32_t input_stride, filter_stride, output_stride;
    uint32_t per_channel, dataflow_mode, ia_reuse_num, w_reuse_num;
    int32_t input_offset, filter_offset, output_offset;
    int32_t multiplier, shift, activation_min, activation_max;
    uint32_t lhs_tile_packed, rhs_tile_packed;
} dsa_prepared_matmul_s8_config_t;

/* Elementwise Add keeps both activation addresses dynamic. The descriptor
 * contains the immutable length, quantization and activation limits. */
typedef struct {
    uint32_t valid, length;
    dsa_vector_add_params_t quantization;
    int32_t output_offset, activation_min, activation_max;
} dsa_prepared_add_s8_t;

void dsa_prepared_invalidate(dsa_prepared_t *prepared);
uint32_t dsa_prepare_conv_s8(dsa_prepared_t *prepared,
                           const dsa_conv_s8_config_t *config);
uint32_t dsa_prepare_spatial_s8(dsa_prepared_t *prepared,
                              const dsa_vector_config_t *config);
uint32_t dsa_prepare_matmul_s8(dsa_prepared_t *prepared,
                             const dsa_prepared_matmul_s8_config_t *config);
uint32_t dsa_prepared_execute(const dsa_prepared_t *prepared,
                             const void *input, void *output);
uint32_t dsa_prepare_add_s8(dsa_prepared_add_s8_t *prepared, uint32_t length,
                          const dsa_vector_add_params_t *quantization,
                          int32_t output_offset, int32_t activation_min,
                          int32_t activation_max);
uint32_t dsa_prepared_add_s8_execute(const dsa_prepared_add_s8_t *prepared,
                                   const int8_t *input1, const int8_t *input2,
                                   int8_t *output);

#ifdef __cplusplus
}
#endif
#endif
