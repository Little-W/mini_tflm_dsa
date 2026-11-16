/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_SOFTMAX_H
#define DSA_SOFTMAX_H

#include "dsa_accel.h"

#define DSA_SOFTMAX_OPCODE DSA_VECTOR_OP_SOFTMAX_S8
#define DSA_SOFTMAX_CAPABILITY DSA_VECTOR_CAP_SOFTMAX_S8
#define DSA_SOFTMAX_LUT_ENTRIES 256u
#ifndef DSA_SOFTMAX_TIMEOUT
#define DSA_SOFTMAX_TIMEOUT 2000000u
#endif

/* Each Q31 table entry contains exp(-index * input_scale * beta), evaluated
 * with the same fixed-point arithmetic and cutoff as the software kernel.
 * The prepared table and its bus address remain valid until the plan is freed.
 */
typedef struct {
    uint32_t depth, exp_lut_base, valid;
} dsa_softmax_plan_t;

static inline void dsa_softmax_barrier(void)
{
#if defined(__riscv)
    __asm__ volatile("fence iorw, iorw" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
}

static inline int dsa_softmax_span(const void *pointer, uint32_t bytes)
{
    return pointer && bytes && (uintptr_t)pointer <= UINT32_MAX - bytes;
}

static inline int dsa_softmax_supported(uint32_t depth)
{
    return depth && dsa_reg_read(NPU_REG_ID)==0x4e505531u &&
        dsa_reg_read(NPU_REG_CONFIG_ABI)==2u &&
        (dsa_reg_read(NPU_REG_VECTOR_CAPS)&DSA_SOFTMAX_CAPABILITY) &&
        depth<=dsa_reg_read(NPU_REG_SOFTMAX_MAX_DEPTH);
}

static inline uint32_t dsa_softmax_prepare(dsa_softmax_plan_t *plan,
                                          uint32_t depth, const int32_t *exp_lut)
{
    if (!plan) return DSA_ERR_NULL_PTR;
    plan->valid=0u;
    if (!depth || !dsa_softmax_span(exp_lut,DSA_SOFTMAX_LUT_ENTRIES*4u) ||
        ((uintptr_t)exp_lut & 3u)) return DSA_ERR_INVALID_DIM;
    if (!dsa_softmax_supported(depth)) return DSA_ERR_UNSUPPORTED;
    plan->depth=depth;
    plan->exp_lut_base=(uint32_t)(uintptr_t)exp_lut;
    plan->valid=0x534d5831u;
    return DSA_SUCCESS;
}

static inline uint32_t dsa_softmax_execute(const dsa_softmax_plan_t *plan,
                                          const int8_t *input, int8_t *output)
{
    uint32_t status, polls;
    uintptr_t in=(uintptr_t)input, out=(uintptr_t)output;
    if (!plan || plan->valid!=0x534d5831u) return DSA_ERR_INVALID_DIM;
    if (!dsa_softmax_span(input,plan->depth) || !dsa_softmax_span(output,plan->depth) ||
        (in<out+plan->depth && out<in+plan->depth) ||
        ((uint64_t)plan->exp_lut_base<(uint64_t)out+plan->depth &&
         (uint64_t)out<(uint64_t)plan->exp_lut_base+DSA_SOFTMAX_LUT_ENTRIES*4u))
        return DSA_ERR_INVALID_DIM;
    if (dsa_reg_read(NPU_REG_STATUS)&(1u<<1)) return DSA_ERR_BUSY;
    dsa_reg_write(NPU_REG_LHS_BASE,(uint32_t)in);
    dsa_reg_write(NPU_REG_RHS_BASE,plan->exp_lut_base);
    dsa_reg_write(NPU_REG_DST_BASE,(uint32_t)out);
    dsa_reg_write(NPU_REG_VECTOR_LENGTH,plan->depth);
    dsa_reg_write(NPU_REG_VECTOR_OP,DSA_SOFTMAX_OPCODE);
    dsa_reg_write(NPU_REG_STATUS,NPU_STATUS_DONE);
    dsa_softmax_barrier();
    dsa_reg_write(NPU_REG_CTRL,NPU_CTRL_START|NPU_CTRL_IRQ_ENABLE|NPU_CTRL_VECTOR_ENGINE);
    for (polls=0;polls<DSA_SOFTMAX_TIMEOUT;polls++) {
        status=dsa_reg_read(NPU_REG_STATUS);
        if (status&NPU_STATUS_DONE) break;
    }
    if (polls==DSA_SOFTMAX_TIMEOUT) return DSA_ERR_TIMEOUT;
    dsa_softmax_barrier();
    status=(status&NPU_STATUS_ERR_MASK) ?
        ((status&NPU_STATUS_ERR_MASK)>>NPU_STATUS_ERR_SHIFT) : dsa_reg_read(NPU_REG_WB_DATA);
    dsa_reg_write(NPU_REG_STATUS,NPU_STATUS_DONE);
    dsa_softmax_barrier();
    return status;
}

#endif
