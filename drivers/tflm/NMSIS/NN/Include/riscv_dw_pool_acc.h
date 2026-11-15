/* SPDX-License-Identifier: Apache-2.0 */
#ifndef RISCV_DW_POOL_ACC_H
#define RISCV_DW_POOL_ACC_H

#include "riscv_nn_types.h"
#include "../../../../dsa_dw_pool.h"

#ifndef DSA_NN_DW_POOL_ENABLE
#define DSA_NN_DW_POOL_ENABLE 1
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Returns 1 when handled, including invalid arguments and device failures.
 * A return value of 0 permits the caller to use its software implementation.
 */
int riscv_depthwise_conv_s8_try_dsa(
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
