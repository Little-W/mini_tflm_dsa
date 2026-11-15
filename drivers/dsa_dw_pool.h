/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_DW_POOL_H
#define DSA_DW_POOL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NPU_CTRL_DW_POOL          (1u << 8)
#define NPU_REG_DW_POOL_OP        0x0b0u
#define NPU_REG_DW_POOL_LENGTH    0x0b4u
#define NPU_REG_DW_POOL_CAPS      0x0b8u
#define NPU_REG_DW_POOL_CYCLES    0x0bcu
#define NPU_REG_DW_POOL_COMPUTE   0x0c0u
#define NPU_REG_DW_POOL_DMA_WAIT  0x0c4u
#define DSA_DW_POOL_VECTOR_S16    (1u << 8)

#define DSA_DW_POOL_CAP_DW_S8     (1u << 0)
#define DSA_DW_POOL_CAP_POOL_S8   (1u << 1)
#define DSA_DW_POOL_CAP_VECTOR_S8 (1u << 2)
#define DSA_DW_POOL_CAP_VECTOR_S16 (1u << 3)
#define DSA_DW_POOL_CAP_VERSION  1u
#define DSA_DW_POOL_MAX_TAPS     49u

typedef enum {
    DSA_DW_OP_DW_S8 = 0,
    DSA_DW_OP_AVGPOOL_S8 = 1,
    DSA_DW_OP_MAXPOOL_S8 = 2,
    DSA_DW_OP_MINPOOL_S8 = 3,
    DSA_DW_OP_SUM = 4,
    DSA_DW_OP_MAX = 5,
    DSA_DW_OP_MIN = 6,
    DSA_DW_OP_DOT = 7,
    DSA_DW_OP_HADAMARD = 8
} dsa_dw_pool_operation_t;

/* Image commands process one NHWC batch. DW filters use [Kh, Kw, C]
 * storage and a channel multiplier of one. Vector operands are signed s8
 * or signed s16; reduction outputs are one s32 and Hadamard outputs are
 * length s32 elements. Vector arithmetic uses modulo 2^32 accumulation.
 * Addresses are 32-bit bus addresses. Quantization arrays contain one
 * s32 entry per channel. A zero bias_base selects zero bias.
 * Output storage must be separate from every input and parameter array.
 * Allocation end addresses must be smaller than 2^32.
 * Input/output buffers must be accessible to the DMA and remain valid
 * until completion. Cache maintenance is a platform responsibility.
 */
typedef struct {
    uint32_t operation, vector_s16, length;
    uint32_t input_base, rhs_base, output_base, bias_base;
    uint32_t multiplier_base, shift_base;
    uint32_t input_h, input_w, input_c;
    uint32_t kernel_h, kernel_w, output_h, output_w;
    uint32_t stride_h, stride_w, dilation_h, dilation_w;
    uint32_t pad_top, pad_left;
    int32_t input_offset, output_offset, activation_min, activation_max;
    uint32_t bypass_cache;
} dsa_dw_pool_config_t;

void dsa_dw_pool_config_init(dsa_dw_pool_config_t *config);
uint32_t dsa_dw_pool_capabilities(void);
/* Pure validation: does not access MMIO or tensor memory. */
uint32_t dsa_dw_pool_validate(const dsa_dw_pool_config_t *config);
/* Unsupported/busy returns precede START. A timeout leaves DMA state intact;
 * the caller must quiesce the device before reusing its buffers.
 */
uint32_t dsa_dw_pool_execute(const dsa_dw_pool_config_t *config);

#ifdef __cplusplus
}
#endif
#endif
