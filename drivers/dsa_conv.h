/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_CONV_H
#define DSA_CONV_H
#include <stdint.h>
#include "dsa_matrix.h"

#ifndef DSA_NN_POINTWISE_DIRECT
#define DSA_NN_POINTWISE_DIRECT 1
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ABI 2 remains valid for GEMM. Conv has an independent capability version. */
#define NPU_REG_CONV_INPUT_BASE   0x074u
#define NPU_REG_CONV_INPUT_HW     0x078u
#define NPU_REG_CONV_CHANNELS     0x07cu
#define NPU_REG_CONV_GROUP_OFFSET 0x080u
#define NPU_REG_CONV_KERNEL_HW    0x084u
#define NPU_REG_CONV_OUTPUT_HW    0x088u
#define NPU_REG_CONV_STRIDE_HW    0x08cu
#define NPU_REG_CONV_DILATION_HW  0x090u
#define NPU_REG_CONV_PADDING_HW   0x094u
#define NPU_REG_CONV_INPUT_OFFSET 0x098u
#define NPU_REG_CONV_CAPS         0x09cu
#define NPU_REG_CONV_HITS         0x0a0u
#define NPU_REG_CONV_MISSES       0x0a4u
#define NPU_REG_CONV_READ_BYTES   0x0a8u
#define NPU_REG_CONV_CYCLES       0x0acu
#define NPU_CTRL_HW_CONV          (1u << 6)
#define NPU_CTRL_CONV_BYPASS      (1u << 7)
#define DSA_CONV_CAP_S8           (1u << 0)
#define DSA_CONV_CAP_NARROW_READ   (1u << 1)
#define DSA_CONV_CAP_IS            (1u << 2)
#define DSA_CONV_CAP_VERSION      1u
#define DSA_ERR_TIMEOUT           0x80000001u
#define DSA_ERR_UNSUPPORTED       0x80000002u
#define DSA_ERR_BUSY              0x80000003u

/* One NHWC batch and one contiguous input/output channel group per command.
 * All addresses are 32-bit bus addresses, never C/SV structure copies.
 * OHWI filter storage is used directly. dst_row_stride is the complete Cout
 * for a grouped convolution; output_channels is this group's Cout.
 * Input is s8; block DMA applies input_offset and returns corrected s16
 * matrix blocks to the active loader (IA in WS, kernel in IS).
 * Bias/accumulation are s32; output is s8 with per-channel integer round-to-nearest, ties-to-even.
 * The caller guarantees no signed accumulator/pre-quantization overflow.
 */
typedef struct {
    uint32_t input_base, filter_base, output_base, bias_base;
    uint32_t multiplier_base, shift_base;
    uint32_t input_h, input_w, input_c, group_c, group_offset;
    uint32_t kernel_h, kernel_w, output_h, output_w;
    uint32_t stride_h, stride_w, dilation_h, dilation_w;
    uint32_t pad_top, pad_left;
    uint32_t output_channels, dst_row_stride;
    int32_t input_offset, output_offset, activation_min, activation_max;
    uint32_t bypass_cache, ia_reuse_num, w_reuse_num;
    /* 0: WS, 1: IS, 2: automatic. Zero-initialized callers retain WS behavior.
     * Public dimensions, NHWC input and OHWI filter layout do not change. */
    uint32_t dataflow_mode;
    uint32_t rhs_tile_packed;
} dsa_conv_s8_config_t;

uint32_t dsa_conv_capabilities(void);
/* Pure validation; does not touch MMIO or input/filter data. */
uint32_t dsa_conv_s8_validate(const dsa_conv_s8_config_t *config);
/* Unsupported/busy return before START. A failure after START must not fall
 * through to software while the device can still write output memory.
 */
uint32_t dsa_conv_s8_execute(const dsa_conv_s8_config_t *config);

#ifdef __cplusplus
}
#endif
#endif
