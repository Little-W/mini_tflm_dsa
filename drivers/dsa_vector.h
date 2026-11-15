/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_VECTOR_H
#define DSA_VECTOR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NPU_CTRL_VECTOR_ENGINE          (1u << 8)
#define NPU_REG_VECTOR_OP        0x0b0u
#define NPU_REG_VECTOR_LENGTH    0x0b4u
#define NPU_REG_VECTOR_CAPS      0x0b8u
#define NPU_REG_VECTOR_CYCLES    0x0bcu
#define NPU_REG_VECTOR_COMPUTE   0x0c0u
#define NPU_REG_VECTOR_DMA_WAIT  0x0c4u
#define NPU_REG_POOL_MAX_TAPS       0x0c8u
#define NPU_REG_VECTOR_ADD_INPUT1_MULT  0x0ccu
#define NPU_REG_VECTOR_ADD_INPUT1_SHIFT 0x0d0u
#define NPU_REG_VECTOR_ADD_INPUT2_MULT  0x0d4u
#define NPU_REG_VECTOR_ADD_INPUT2_SHIFT 0x0d8u
#define NPU_REG_VECTOR_ADD_LEFT_SHIFT   0x0dcu
#define DSA_VECTOR_VECTOR_S16    (1u << 8)

#define DSA_VECTOR_CAP_DW_S8     (1u << 0)
#define DSA_VECTOR_CAP_POOL_S8   (1u << 1)
#define DSA_VECTOR_CAP_VECTOR_S8 (1u << 2)
#define DSA_VECTOR_CAP_VECTOR_S16 (1u << 3)
#define DSA_VECTOR_CAP_LARGE_POOL (1u << 4)
#define DSA_VECTOR_CAP_ADD_S8     (1u << 5)
#define DSA_POOL_MAX_TAPS 256u
#define DSA_VECTOR_CAP_VERSION  1u
#define DSA_DW_MAX_TAPS     49u

typedef enum {
    DSA_VECTOR_OP_DW_S8 = 0,
    DSA_VECTOR_OP_AVGPOOL_S8 = 1,
    DSA_VECTOR_OP_MAXPOOL_S8 = 2,
    DSA_VECTOR_OP_MINPOOL_S8 = 3,
    DSA_VECTOR_OP_SUM = 4,
    DSA_VECTOR_OP_MAX = 5,
    DSA_VECTOR_OP_MIN = 6,
    DSA_VECTOR_OP_DOT = 7,
    DSA_VECTOR_OP_HADAMARD = 8,
    DSA_VECTOR_OP_ADD_S8 = 9
} dsa_vector_operation_t;

typedef struct {
    int32_t input1_offset, input2_offset;
    int32_t input1_multiplier, input1_shift;
    int32_t input2_multiplier, input2_shift;
    int32_t left_shift, output_multiplier, output_shift;
} dsa_vector_add_params_t;

/* Add performs three Q31 nearest-even rescalings. Each operand is offset,
 * multiplied by 2^left_shift, and rescaled independently before addition.
 * The sum is rescaled once, then offset and clipped to the activation range. */
static inline int dsa_vector_add_quantization_valid(
    const dsa_vector_add_params_t *p, int32_t output_offset,
    int32_t activation_min, int32_t activation_max)
{
    return p && p->input1_offset >= -127 && p->input1_offset <= 128 &&
        p->input2_offset >= -127 && p->input2_offset <= 128 &&
        p->input1_multiplier >= 0 && p->input2_multiplier >= 0 &&
        p->output_multiplier >= 0 && p->input1_shift >= -31 && p->input1_shift <= 0 &&
        p->input2_shift >= -31 && p->input2_shift <= 0 &&
        p->output_shift >= -31 && p->output_shift <= 30 &&
        p->left_shift >= 0 && p->left_shift <= 22 &&
        output_offset >= -128 && output_offset <= 127 &&
        activation_min >= -128 && activation_max <= 127 && activation_min <= activation_max;
}

/* Image commands process one NHWC batch. DW filters use [Kh, Kw, C]
 * storage and a channel multiplier of one. Vector operands are signed s8
 * or signed s16; reduction outputs are one s32 and Hadamard outputs are
 * length s32 elements. Reduction arithmetic uses modulo 2^32 accumulation.
 * ADD_S8 reads two length-byte inputs and writes one length-byte output.
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
    dsa_vector_add_params_t add;
} dsa_vector_config_t;

void dsa_vector_config_init(dsa_vector_config_t *config);
uint32_t dsa_vector_capabilities(void);
/* Pure validation: does not access MMIO or tensor memory. */
uint32_t dsa_vector_validate(const dsa_vector_config_t *config);
/* Unsupported/busy returns precede START. A timeout leaves DMA state intact;
 * the caller must quiesce the device before reusing its buffers.
 */
uint32_t dsa_vector_execute(const dsa_vector_config_t *config);

#ifdef __cplusplus
}
#endif
#endif
