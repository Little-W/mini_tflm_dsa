/* SPDX-License-Identifier: Apache-2.0 */
#include <limits.h>
#include <stdint.h>
#include "dsa_accel.h"
#include "riscv_nnfunctions.h"

#ifndef DSA_NN_CONV_ENABLE
#define DSA_NN_CONV_ENABLE 1
#endif

/* Select the shared-DMA Conv dataflow for all NMSIS s8 entry points in this
 * translation unit: 0 = WS, 1 = IS, 2 = automatic (default). Unsupported hardware
 * falls back before START; this is not a runtime global configuration. */
#ifndef DSA_NN_CONV_DATAFLOW_MODE
#define DSA_NN_CONV_DATAFLOW_MODE 2
#endif
#if DSA_NN_CONV_DATAFLOW_MODE < 0 || DSA_NN_CONV_DATAFLOW_MODE > 2
#error "DSA_NN_CONV_DATAFLOW_MODE must be 0 (WS), 1 (IS), or 2 (automatic)"
#endif

#if DSA_NN_CONV_ENABLE
static int nn_conv_dim(int32_t v) { return v > 0 && v <= 65535; }
static int nn_conv_address(const void *p, uint64_t size)
{
    return p && (uintptr_t)p <= UINT32_MAX && size &&
           (uint64_t)(uintptr_t)p + size <= UINT32_MAX;
}
#endif

int riscv_convolve_s8_try_dsa(
    const nmsis_nn_conv_params *p,
    const nmsis_nn_per_channel_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *f, const int8_t *filter,
    const int32_t *bias, const nmsis_nn_dims *upscale,
    const nmsis_nn_dims *out, int8_t *output,
    riscv_nmsis_nn_status *status)
{
#if !DSA_NN_CONV_ENABLE
    (void)p; (void)q; (void)in; (void)input; (void)f; (void)filter;
    (void)bias; (void)upscale; (void)out; (void)output; (void)status;
    return 0;
#else
    uint32_t groups, group_outputs, reduction, batch, group, oc;
    uint64_t input_batch, output_batch, weights_size, bound;
    int64_t lo, hi;
    dsa_conv_s8_config_t c = {0};
    if (!dsa_nn_accelerator_enabled(DSA_NN_ACCEL_CONV) || !status) return 0;
    *status = RISCV_NMSIS_NN_ARG_ERROR;
    if (!p || !q || !in || !f || !out || !input || !filter || !output ||
        !q->multiplier || !q->shift) return 1;
    if (in->h <= 0 || in->w <= 0 || in->c <= 0 ||
        f->h <= 0 || f->w <= 0 || f->c <= 0 ||
        out->h <= 0 || out->w <= 0 || out->c <= 0 ||
        in->n <= 0 || out->n != in->n || f->c > in->c || in->c % f->c ||
        p->stride.h <= 0 || p->stride.w <= 0 ||
        p->dilation.h <= 0 || p->dilation.w <= 0 ||
        p->padding.h < 0 || p->padding.w < 0 ||
        p->input_offset < -127 || p->input_offset > 128 ||
        p->output_offset < -128 || p->output_offset > 127 ||
        p->activation.min < -128 || p->activation.max > 127 ||
        p->activation.min > p->activation.max) return 1;
    groups = (uint32_t)in->c / (uint32_t)f->c;
    if ((uint32_t)out->c % groups) return 1;
    group_outputs = (uint32_t)out->c / groups;
    /* Valid NMSIS dimensions beyond the hardware's u16 fields are unsupported,
     * not malformed: preserve the software fallback contract. */
    if (!nn_conv_dim(in->h) || !nn_conv_dim(in->w) || !nn_conv_dim(in->c) ||
        !nn_conv_dim(f->h) || !nn_conv_dim(f->w) || !nn_conv_dim(f->c) ||
        !nn_conv_dim(out->h) || !nn_conv_dim(out->w) || !nn_conv_dim(out->c) ||
        !nn_conv_dim(p->stride.h) || !nn_conv_dim(p->stride.w) ||
        !nn_conv_dim(p->dilation.h) || !nn_conv_dim(p->dilation.w) ||
        p->padding.h > 65535 || p->padding.w > 65535) return 0;
    /* Transposed/upscaled convolution is deliberately left to NMSIS. */
    if (upscale && (upscale->h != 1 || upscale->w != 1)) return 0;
    if ((uint64_t)f->h * f->w * f->c > 65535u) return 0;
    reduction = (uint32_t)f->h * (uint32_t)f->w * (uint32_t)f->c;
    input_batch = (uint64_t)in->h * in->w * in->c;
    output_batch = (uint64_t)out->h * out->w * out->c;
    weights_size = (uint64_t)out->c * reduction;
    /* Bound these before multiplying by batch count (which is signed s32). */
    if (input_batch > UINT32_MAX || output_batch > UINT32_MAX) return 0;
    /* Check the entire batch/group sequence before any START. No pointer
     * truncation and no partially executed layer followed by software retry. */
    if (!nn_conv_address(input, input_batch * (uint32_t)in->n) ||
        !nn_conv_address(output, output_batch * (uint32_t)in->n) ||
        !nn_conv_address(filter, weights_size) ||
        !nn_conv_address(q->multiplier, (uint64_t)out->c * 4u) ||
        !nn_conv_address(q->shift, (uint64_t)out->c * 4u) ||
        (bias && !nn_conv_address(bias, (uint64_t)out->c * 4u))) return 0;
    c.input_base = (uint32_t)(uintptr_t)input;
    c.filter_base = (uint32_t)(uintptr_t)filter;
    c.output_base = (uint32_t)(uintptr_t)output;
    c.bias_base = (uint32_t)(uintptr_t)bias;
    c.multiplier_base = (uint32_t)(uintptr_t)q->multiplier;
    c.shift_base = (uint32_t)(uintptr_t)q->shift;
    c.input_h = (uint32_t)in->h; c.input_w = (uint32_t)in->w;
    c.input_c = (uint32_t)in->c; c.group_c = (uint32_t)f->c;
    c.kernel_h = (uint32_t)f->h; c.kernel_w = (uint32_t)f->w;
    c.output_h = (uint32_t)out->h; c.output_w = (uint32_t)out->w;
    c.output_channels = group_outputs; c.dst_row_stride = (uint32_t)out->c;
    c.stride_h = (uint32_t)p->stride.h; c.stride_w = (uint32_t)p->stride.w;
    c.dilation_h = (uint32_t)p->dilation.h; c.dilation_w = (uint32_t)p->dilation.w;
    c.pad_top = (uint32_t)p->padding.h; c.pad_left = (uint32_t)p->padding.w;
    c.input_offset = p->input_offset; c.output_offset = p->output_offset;
    c.activation_min = p->activation.min; c.activation_max = p->activation.max;
    c.dataflow_mode = DSA_NN_CONV_DATAFLOW_MODE;
    if (dsa_conv_s8_validate(&c) != DSA_SUCCESS) return 0;
    {
        const uint32_t required_caps = DSA_CONV_CAP_S8 | DSA_CONV_CAP_NARROW_READ |
            (DSA_NN_CONV_DATAFLOW_MODE == 1 ? DSA_CONV_CAP_IS : 0u);
        if ((dsa_conv_capabilities() & required_caps) != required_caps) return 0;
    }
    /* Only channel parameters are inspected on the CPU; no activation/window
     * expansion or filter dot product occurs here. This conservative bound
     * ensures agreement with the repository's s32 integer RNE quantization. */
    lo = -128 + p->input_offset; hi = 127 + p->input_offset;
    if (lo < 0) lo = -lo;
    if (hi < 0) hi = -hi;
    bound = (uint64_t)(lo > hi ? lo : hi) * 128u * reduction;
    for (oc = 0; oc < (uint32_t)out->c; ++oc) {
        int32_t shift = q->shift[oc];
        int64_t abs_bias = bias ? bias[oc] : 0;
        uint64_t channel_bound;
        if (abs_bias < 0) abs_bias = -abs_bias;
        if (shift < -31 || shift > 30 || q->multiplier[oc] < 0) return 0;
        channel_bound = bound + (uint64_t)abs_bias;
        if (channel_bound > INT32_MAX) return 0;
    }
#if DSA_NN_POINTWISE_DIRECT
    if (groups == 1u && f->h == 1 && f->w == 1 &&
        p->stride.h == 1 && p->stride.w == 1 &&
        p->dilation.h == 1 && p->dilation.w == 1 &&
        p->padding.h == 0 && p->padding.w == 0 &&
        in->h == out->h && in->w == out->w &&
        (uint64_t)out->h * out->w <= 65535u) {
        dsa_matmul_config_t direct;
        if (dsa_reg_read(NPU_REG_STATUS) & (1u << 1)) {
            *status = RISCV_NMSIS_NN_NO_IMPL_ERROR;
            return 1;
        }
        dsa_matmul_config_init(&direct);
        direct.rhs_ptr = filter;
        direct.bias_ptr = bias;
        direct.K = (uint32_t)out->h * (uint32_t)out->w;
        direct.N = (uint32_t)in->c;
        direct.M = (uint32_t)out->c;
        direct.lhs_row_stride = direct.rhs_row_stride = (uint32_t)in->c;
        direct.dst_row_stride = (uint32_t)out->c;
        direct.quant_mode = DSA_QUANT_PER_CHANNEL;
        direct.dst_mult_ptr = q->multiplier;
        direct.dst_shift_ptr = q->shift;
        direct.lhs_offset = p->input_offset;
        direct.dst_offset = p->output_offset;
        direct.act_min = p->activation.min;
        direct.act_max = p->activation.max;
        direct.dataflow_mode = (dsa_dataflow_mode_t)DSA_NN_CONV_DATAFLOW_MODE;
        for (batch = 0u; batch < (uint32_t)in->n; ++batch) {
            direct.lhs_ptr = input + batch * input_batch;
            direct.dst_ptr = output + batch * output_batch;
            if (dsa_matmul_execute(&direct) != DSA_SUCCESS) {
                *status = RISCV_NMSIS_NN_NO_IMPL_ERROR;
                return 1;
            }
        }
        *status = RISCV_NMSIS_NN_SUCCESS;
        return 1;
    }
#endif
    for (batch = 0; batch < (uint32_t)in->n; ++batch) {
        c.input_base = (uint32_t)((uintptr_t)input + batch * input_batch);
        for (group = 0; group < groups; ++group) {
            uint32_t first_channel = group * group_outputs;
            uint32_t result;
            c.group_offset = group * (uint32_t)f->c;
            c.filter_base = (uint32_t)((uintptr_t)filter + (uint64_t)first_channel * reduction);
            c.output_base = (uint32_t)((uintptr_t)output + batch * output_batch + first_channel);
            c.bias_base = bias ? (uint32_t)((uintptr_t)bias + first_channel * 4u) : 0u;
            c.multiplier_base = (uint32_t)((uintptr_t)q->multiplier + first_channel * 4u);
            c.shift_base = (uint32_t)((uintptr_t)q->shift + first_channel * 4u);
            result = dsa_conv_s8_execute(&c);
            if (result != DSA_SUCCESS) {
                *status = RISCV_NMSIS_NN_NO_IMPL_ERROR;
                return 1;
            }
        }
    }
    *status = RISCV_NMSIS_NN_SUCCESS;
    return 1;
#endif
}

/* All public accelerated entry points share the ordinary NMSIS dispatcher.
 * Its probe runs before software im2col; unsupported hardware/configurations
 * use the original software kernels with their original scratch requirements.
 */
riscv_nmsis_nn_status riscv_convolve_s8_acc(
    const nmsis_nn_context *ctx, const nmsis_nn_conv_params *p,
    const nmsis_nn_per_channel_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *f, const int8_t *filter,
    const nmsis_nn_dims *bd, const int32_t *bias,
    const nmsis_nn_dims *upscale, const nmsis_nn_dims *out, int8_t *output)
{
    return riscv_convolve_s8(ctx, p, q, in, input, f, filter, bd, bias, upscale, out, output);
}

#define DSA_CONV_FORWARD(name, target) \
riscv_nmsis_nn_status name( \
    const nmsis_nn_context *ctx, const nmsis_nn_conv_params *p, \
    const nmsis_nn_per_channel_quant_params *q, \
    const nmsis_nn_dims *in, const int8_t *input, \
    const nmsis_nn_dims *f, const int8_t *filter, \
    const nmsis_nn_dims *bd, const int32_t *bias, \
    const nmsis_nn_dims *out, int8_t *output) \
{ return target(ctx, p, q, in, input, f, filter, bd, bias, out, output); }

DSA_CONV_FORWARD(riscv_convolve_1x1_s8_acc, riscv_convolve_1x1_s8)
DSA_CONV_FORWARD(riscv_convolve_1x1_s8_fast_acc, riscv_convolve_1x1_s8_fast)
DSA_CONV_FORWARD(riscv_convolve_wrapper_s8_acc, riscv_convolve_wrapper_s8)

int32_t riscv_convolve_s8_get_buffer_size_acc(const nmsis_nn_dims *in,
                                            const nmsis_nn_dims *f)
{
    return riscv_convolve_s8_get_buffer_size(in, f);
}

int32_t riscv_convolve_wrapper_s8_get_buffer_size_acc(
    const nmsis_nn_conv_params *p, const nmsis_nn_dims *in,
    const nmsis_nn_dims *f, const nmsis_nn_dims *out)
{
    /* Reserve the ordinary fallback scratch even when the hardware path will
     * not touch it. Geometry alone cannot predict capability/numeric fallback. */
    (void)p; (void)out;
    return riscv_convolve_s8_get_buffer_size(in, f);
}
