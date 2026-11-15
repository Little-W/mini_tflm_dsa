/* SPDX-License-Identifier: Apache-2.0 */
#ifndef RISCV_VECTOR_ENGINE_ACC_H
#define RISCV_VECTOR_ENGINE_ACC_H

#include "riscv_nn_types.h"
#include "../../../../dsa_vector.h"

#ifndef DSA_NN_VECTOR_ENABLE
#ifdef DSA_NN_DW_POOL_ENABLE
#define DSA_NN_VECTOR_ENABLE DSA_NN_DW_POOL_ENABLE
#else
#define DSA_NN_VECTOR_ENABLE 1
#endif
#endif

#define DSA_NN_DW_CONV_MAX_CHANNELS 16u

/* A single input channel permits a bounded HWIO-to-OHWI weight conversion.
 * The size is independent of the runtime accelerator mask. */
static inline int32_t riscv_depthwise_conv_s8_dsa_buffer_size(
    const nmsis_nn_dw_conv_params *params, const nmsis_nn_dims *input_dims,
    const nmsis_nn_dims *filter_dims, const nmsis_nn_dims *output_dims)
{
#if DSA_NN_VECTOR_ENABLE
    uint64_t taps;
    if (!params || !input_dims || !filter_dims || !output_dims ||
        input_dims->c != 1 || params->ch_mult < 2 ||
        params->ch_mult > (int32_t)DSA_NN_DW_CONV_MAX_CHANNELS ||
        output_dims->c != params->ch_mult ||
        filter_dims->n != 1 || filter_dims->c != output_dims->c ||
        filter_dims->h <= 0 || filter_dims->w <= 0) return 0;
    taps = (uint64_t)filter_dims->h * (uint32_t)filter_dims->w;
    if (taps > DSA_DW_MAX_TAPS) return 0;
    return (int32_t)(taps * (uint32_t)output_dims->c);
#else
    (void)params; (void)input_dims; (void)filter_dims; (void)output_dims;
    return 0;
#endif
}

/* Exact in-place output is supported by software. Partial output overlap is
 * rejected before any tensor access; the two read-only inputs may overlap. */
static inline int riscv_vector_add_buffers_valid(const int8_t *a, const int8_t *b,
                                                int8_t *output, int32_t length)
{
    const uintptr_t aa = (uintptr_t)a, bb = (uintptr_t)b, oo = (uintptr_t)output;
    if (length < 0) return 0;
    if (length == 0) return 1;
    if (!a || !b || !output || (uintptr_t)length > UINTPTR_MAX - aa ||
        (uintptr_t)length > UINTPTR_MAX - bb || (uintptr_t)length > UINTPTR_MAX - oo) return 0;
    if (oo != aa && aa < oo + (uintptr_t)length && oo < aa + (uintptr_t)length) return 0;
    if (oo != bb && bb < oo + (uintptr_t)length && oo < bb + (uintptr_t)length) return 0;
    return 1;
}

#ifdef __cplusplus
extern "C" {
#endif

/* Returns 1 when handled, including invalid arguments and device failures.
 * A return value of 0 permits the caller to use its software implementation.
 */
int riscv_add_s8_try_dsa(
    const dsa_vector_add_params_t *params, const int8_t *input1,
    const int8_t *input2, int8_t *output, int32_t length,
    int32_t output_offset, int32_t activation_min, int32_t activation_max,
    riscv_nmsis_nn_status *status);

int riscv_depthwise_conv_s8_try_dsa(
    const nmsis_nn_context *ctx,
    const nmsis_nn_dw_conv_params *params,
    const nmsis_nn_per_channel_quant_params *quant,
    const nmsis_nn_dims *input_dims, const int8_t *input,
    const nmsis_nn_dims *filter_dims, const int8_t *filter,
    const int32_t *bias, const nmsis_nn_dims *output_dims, int8_t *output,
    riscv_nmsis_nn_status *status);

int riscv_pool_s8_try_dsa(
    uint32_t operation, const nmsis_nn_pool_params *params,
    const nmsis_nn_dims *input_dims, const int8_t *input,
    const nmsis_nn_dims *filter_dims,
    const nmsis_nn_dims *output_dims, int8_t *output,
    riscv_nmsis_nn_status *status);

riscv_nmsis_nn_status riscv_depthwise_conv_s8_acc(
    const nmsis_nn_context *ctx, const nmsis_nn_dw_conv_params *params,
    const nmsis_nn_per_channel_quant_params *quant,
    const nmsis_nn_dims *input_dims, const int8_t *input,
    const nmsis_nn_dims *filter_dims, const int8_t *filter,
    const nmsis_nn_dims *bias_dims, const int32_t *bias,
    const nmsis_nn_dims *output_dims, int8_t *output);

#ifdef __cplusplus
}
#endif
#endif
