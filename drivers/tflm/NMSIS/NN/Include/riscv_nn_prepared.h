/* SPDX-License-Identifier: Apache-2.0 */
#ifndef RISCV_NN_PREPARED_H
#define RISCV_NN_PREPARED_H
#include "../../../../dsa_prepared.h"
#include "../../../../dsa_softmax.h"
#include "riscv_nn_dsa.h"
#include "riscv_nn_types.h"

#ifndef DSA_NN_CONV_ENABLE
#define DSA_NN_CONV_ENABLE 1
#endif
#ifndef DSA_NN_FC_ENABLE
#define DSA_NN_FC_ENABLE 1
#endif
#ifndef DSA_NN_CONV_DATAFLOW_MODE
#define DSA_NN_CONV_DATAFLOW_MODE 2
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Layer configurations are constructed during model initialization and stay
 * in persistent arena storage. Execution receives their immutable pointers
 * and the current activation addresses; it does not plan or pack tensors. */
static inline riscv_nmsis_nn_status riscv_nn_execute_prepared_s8(
    const dsa_prepared_t *configuration, const int8_t *input, int8_t *output)
{
    return dsa_prepared_execute(configuration,input,output)==DSA_SUCCESS ?
        RISCV_NMSIS_NN_SUCCESS : RISCV_NMSIS_NN_FAILURE;
}

static inline riscv_nmsis_nn_status riscv_nn_execute_prepared_add_s8(
    const dsa_prepared_add_s8_t *configuration, const int8_t *input1,
    const int8_t *input2, int8_t *output)
{
    return dsa_prepared_add_s8_execute(configuration,input1,input2,output)==DSA_SUCCESS ?
        RISCV_NMSIS_NN_SUCCESS : RISCV_NMSIS_NN_FAILURE;
}

typedef struct {
    dsa_softmax_plan_t plan;
    uint32_t rows, elements;
} nmsis_nn_prepared_softmax_s8_t;

static inline riscv_nmsis_nn_status riscv_nn_prepare_softmax_s8(
    nmsis_nn_prepared_softmax_s8_t *configuration, uint32_t rows,
    uint32_t depth, const int32_t *exp_lut)
{
    uint32_t status;
    if (!configuration) return RISCV_NMSIS_NN_ARG_ERROR;
    configuration->plan.valid=configuration->rows=configuration->elements=0u;
    if (!rows || !depth || rows>UINT32_MAX/depth)
        return RISCV_NMSIS_NN_ARG_ERROR;
    status=dsa_softmax_prepare(&configuration->plan,depth,exp_lut);
    if (status==DSA_ERR_UNSUPPORTED) return RISCV_NMSIS_NN_NO_IMPL_ERROR;
    if (status!=DSA_SUCCESS) return RISCV_NMSIS_NN_ARG_ERROR;
    configuration->rows=rows;
    configuration->elements=rows*depth;
    return RISCV_NMSIS_NN_SUCCESS;
}

static inline riscv_nmsis_nn_status riscv_nn_execute_prepared_softmax_s8(
    const nmsis_nn_prepared_softmax_s8_t *configuration,
    const int8_t *input, int8_t *output)
{
    uintptr_t in=(uintptr_t)input,out=(uintptr_t)output;
    uint32_t count,depth;
    if (!configuration || configuration->plan.valid!=0x534d5831u ||
        !configuration->rows || !configuration->plan.depth)
        return RISCV_NMSIS_NN_ARG_ERROR;
    count=configuration->elements;
    depth=configuration->plan.depth;
    if (!dsa_softmax_span(input,count) || !dsa_softmax_span(output,count) ||
        (in<out+count && out<in+count) ||
        ((uint64_t)configuration->plan.exp_lut_base<(uint64_t)out+count &&
         (uint64_t)out<(uint64_t)configuration->plan.exp_lut_base+DSA_SOFTMAX_LUT_ENTRIES*4u))
        return RISCV_NMSIS_NN_ARG_ERROR;
    for (uint32_t offset=0u;offset<count;offset+=depth) {
        if (depth>count-offset) return RISCV_NMSIS_NN_ARG_ERROR;
        if (dsa_softmax_execute(&configuration->plan,input+offset,output+offset)!=DSA_SUCCESS)
            return RISCV_NMSIS_NN_FAILURE;
    }
    return RISCV_NMSIS_NN_SUCCESS;
}

#ifdef __cplusplus
}
#endif
#endif
