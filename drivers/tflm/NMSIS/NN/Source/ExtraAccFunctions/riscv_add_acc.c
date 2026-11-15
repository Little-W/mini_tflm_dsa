/* SPDX-License-Identifier: Apache-2.0 */
#include "dsa_accel.h"
#include "riscv_vector_acc.h"
#include "riscv_nn_dsa.h"

int riscv_add_s8_try_dsa(
    const dsa_vector_add_params_t *params, const int8_t *input1,
    const int8_t *input2, int8_t *output, int32_t length,
    int32_t output_offset, int32_t activation_min, int32_t activation_max,
    riscv_nmsis_nn_status *status)
{
#if !DSA_NN_VECTOR_ENABLE
    (void)params; (void)input1; (void)input2; (void)output; (void)length;
    (void)output_offset; (void)activation_min; (void)activation_max; (void)status;
    return 0;
#else
    dsa_vector_config_t config;
    uint32_t result;
    if (!status) return 0;
    *status = RISCV_NMSIS_NN_ARG_ERROR;
    if (!dsa_vector_add_quantization_valid(params, output_offset, activation_min, activation_max) ||
        !riscv_vector_add_buffers_valid(input1, input2, output, length)) return 1;
    if (!length) { *status = RISCV_NMSIS_NN_SUCCESS; return 1; }
    if (!dsa_nn_accelerator_enabled(DSA_NN_ACCEL_ADD) || output == input1 || output == input2) return 0;
    if ((uintptr_t)input1 > UINT32_MAX || (uintptr_t)input2 > UINT32_MAX ||
        (uintptr_t)output > UINT32_MAX ||
        (uint64_t)(uintptr_t)input1 + (uint32_t)length >= (UINT64_C(1) << 32) ||
        (uint64_t)(uintptr_t)input2 + (uint32_t)length >= (UINT64_C(1) << 32) ||
        (uint64_t)(uintptr_t)output + (uint32_t)length >= (UINT64_C(1) << 32)) return 0;
    dsa_vector_config_init(&config);
    config.operation = DSA_VECTOR_OP_ADD_S8;
    config.input_base = (uint32_t)(uintptr_t)input1;
    config.rhs_base = (uint32_t)(uintptr_t)input2;
    config.output_base = (uint32_t)(uintptr_t)output;
    config.length = (uint32_t)length;
    config.add = *params;
    config.output_offset = output_offset;
    config.activation_min = activation_min;
    config.activation_max = activation_max;
    result = dsa_vector_execute(&config);
    if (result == DSA_ERR_UNSUPPORTED) return 0;
    *status = result == DSA_SUCCESS ? RISCV_NMSIS_NN_SUCCESS : RISCV_NMSIS_NN_NO_IMPL_ERROR;
    return 1;
#endif
}
