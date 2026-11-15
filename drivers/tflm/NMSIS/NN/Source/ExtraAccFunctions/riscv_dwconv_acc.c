/* SPDX-License-Identifier: Apache-2.0 */
#include <stdint.h>
#include "dsa_accel.h"
#include "riscv_nnfunctions.h"

#if DSA_NN_DW_POOL_ENABLE
static int dw_pool_nn_dim(int32_t value)
{
    return value > 0 && value <= 65535;
}

static int dw_pool_nn_address(const void *pointer, uint64_t bytes)
{
    return pointer && (uintptr_t)pointer <= UINT32_MAX && bytes &&
           (uint64_t)(uintptr_t)pointer + bytes < (UINT64_C(1) << 32);
}

static int dw_pool_nn_separate(const void *a, uint64_t a_bytes,
                               const void *b, uint64_t b_bytes)
{
    return (uint64_t)(uintptr_t)a + a_bytes <= (uintptr_t)b ||
           (uint64_t)(uintptr_t)b + b_bytes <= (uintptr_t)a;
}

static int dw_pool_nn_capable(uint32_t required, uint32_t taps)
{
    const uint32_t caps = dsa_dw_pool_capabilities();
    return (caps & required) == required && ((caps >> 8) & 0xffu) &&
           taps <= ((caps >> 16) & 0xffu);
}

static int dw_pool_nn_run_batches(dsa_dw_pool_config_t *config,
                                 uint32_t batches, uint64_t input_batch,
                                 uint64_t output_batch,
                                 riscv_nmsis_nn_status *status)
{
    const uint32_t input_base = config->input_base;
    const uint32_t output_base = config->output_base;
    for (uint32_t batch = 0u; batch < batches; ++batch) {
        uint32_t result;
        config->input_base = (uint32_t)((uint64_t)input_base + batch * input_batch);
        config->output_base = (uint32_t)((uint64_t)output_base + batch * output_batch);
        result = dsa_dw_pool_execute(config);
        if (result != DSA_SUCCESS) {
            if (!batch && result == DSA_ERR_UNSUPPORTED) return 0;
            *status = RISCV_NMSIS_NN_NO_IMPL_ERROR;
            return 1;
        }
    }
    *status = RISCV_NMSIS_NN_SUCCESS;
    return 1;
}
#endif

int riscv_depthwise_conv_s8_try_dsa(
    const nmsis_nn_dw_conv_params *p,
    const nmsis_nn_per_channel_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *filter_dims, const int8_t *filter,
    const int32_t *bias, const nmsis_nn_dims *out, int8_t *output,
    riscv_nmsis_nn_status *status)
{
#if !DSA_NN_DW_POOL_ENABLE
    (void)p; (void)q; (void)in; (void)input; (void)filter_dims; (void)filter;
    (void)bias; (void)out; (void)output; (void)status;
    return 0;
#else
    dsa_dw_pool_config_t c;
    uint64_t input_batch, output_batch, taps, parameters;
    if (!status) return 0;
    *status = RISCV_NMSIS_NN_ARG_ERROR;
    if (!p || !q || !in || !filter_dims || !out || !input || !filter ||
        !output || !q->multiplier || !q->shift) return 1;
    if (in->n <= 0 || out->n != in->n || in->h <= 0 || in->w <= 0 ||
        in->c <= 0 || out->h <= 0 || out->w <= 0 || out->c <= 0 ||
        filter_dims->h <= 0 || filter_dims->w <= 0 || p->ch_mult <= 0 ||
        (int64_t)in->c * p->ch_mult != out->c ||
        p->stride.h <= 0 || p->stride.w <= 0 ||
        p->dilation.h <= 0 || p->dilation.w <= 0 ||
        p->padding.h < 0 || p->padding.w < 0 ||
        p->input_offset < -127 || p->input_offset > 128 ||
        p->output_offset < -128 || p->output_offset > 127 ||
        p->activation.min < -128 || p->activation.max > 127 ||
        p->activation.min > p->activation.max) return 1;
    if (p->ch_mult != 1 || !dw_pool_nn_dim(in->h) ||
        !dw_pool_nn_dim(in->w) || !dw_pool_nn_dim(in->c) ||
        !dw_pool_nn_dim(out->h) || !dw_pool_nn_dim(out->w) ||
        !dw_pool_nn_dim(filter_dims->h) || !dw_pool_nn_dim(filter_dims->w) ||
        !dw_pool_nn_dim(p->stride.h) || !dw_pool_nn_dim(p->stride.w) ||
        !dw_pool_nn_dim(p->dilation.h) || !dw_pool_nn_dim(p->dilation.w) ||
        p->padding.h > 65535 || p->padding.w > 65535) return 0;

    taps = (uint64_t)filter_dims->h * filter_dims->w;
    input_batch = (uint64_t)in->h * in->w * in->c;
    output_batch = (uint64_t)out->h * out->w * out->c;
    parameters = (uint64_t)out->c * 4u;
    if (taps > DSA_DW_POOL_MAX_TAPS || input_batch > UINT32_MAX ||
        output_batch > UINT32_MAX) return 0;
    if (!dw_pool_nn_address(input, input_batch * (uint32_t)in->n) ||
        !dw_pool_nn_address(output, output_batch * (uint32_t)in->n) ||
        !dw_pool_nn_address(filter, taps * (uint32_t)out->c) ||
        !dw_pool_nn_address(q->multiplier, parameters) ||
        !dw_pool_nn_address(q->shift, parameters) ||
        (bias && !dw_pool_nn_address(bias, parameters))) return 0;
    if (!dw_pool_nn_separate(input, input_batch * (uint32_t)in->n,
                             output, output_batch * (uint32_t)in->n) ||
        !dw_pool_nn_separate(filter, taps * (uint32_t)out->c,
                             output, output_batch * (uint32_t)in->n) ||
        !dw_pool_nn_separate(q->multiplier, parameters,
                             output, output_batch * (uint32_t)in->n) ||
        !dw_pool_nn_separate(q->shift, parameters,
                             output, output_batch * (uint32_t)in->n) ||
        (bias && !dw_pool_nn_separate(bias, parameters,
                                      output, output_batch * (uint32_t)in->n))) return 0;

    dsa_dw_pool_config_init(&c);
    c.operation = DSA_DW_OP_DW_S8;
    c.input_base = (uint32_t)(uintptr_t)input;
    c.rhs_base = (uint32_t)(uintptr_t)filter;
    c.output_base = (uint32_t)(uintptr_t)output;
    c.bias_base = (uint32_t)(uintptr_t)bias;
    c.multiplier_base = (uint32_t)(uintptr_t)q->multiplier;
    c.shift_base = (uint32_t)(uintptr_t)q->shift;
    c.input_h = (uint32_t)in->h; c.input_w = (uint32_t)in->w;
    c.input_c = (uint32_t)in->c;
    c.kernel_h = (uint32_t)filter_dims->h; c.kernel_w = (uint32_t)filter_dims->w;
    c.output_h = (uint32_t)out->h; c.output_w = (uint32_t)out->w;
    c.stride_h = (uint32_t)p->stride.h; c.stride_w = (uint32_t)p->stride.w;
    c.dilation_h = (uint32_t)p->dilation.h; c.dilation_w = (uint32_t)p->dilation.w;
    c.pad_top = (uint32_t)p->padding.h; c.pad_left = (uint32_t)p->padding.w;
    c.input_offset = p->input_offset; c.output_offset = p->output_offset;
    c.activation_min = p->activation.min; c.activation_max = p->activation.max;
    if (dsa_dw_pool_validate(&c) != DSA_SUCCESS ||
        !dw_pool_nn_capable(DSA_DW_POOL_CAP_DW_S8, (uint32_t)taps)) return 0;
    /* Only dimensions and addresses are inspected here. The engine loads
     * tensor data, bias, multipliers and shifts through DMA. */
    return dw_pool_nn_run_batches(&c, (uint32_t)in->n, input_batch, output_batch, status);
#endif
}

int riscv_pool_s8_try_dsa(
    uint32_t operation, const nmsis_nn_pool_params *p,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *filter_dims,
    const nmsis_nn_dims *out, int8_t *output,
    riscv_nmsis_nn_status *status)
{
#if !DSA_NN_DW_POOL_ENABLE
    (void)operation; (void)p; (void)in; (void)input;
    (void)filter_dims; (void)out; (void)output; (void)status;
    return 0;
#else
    dsa_dw_pool_config_t c;
    uint64_t input_batch, output_batch, taps;
    int64_t last_y, last_x;
    if (!status) return 0;
    *status = RISCV_NMSIS_NN_ARG_ERROR;
    if (!p || !in || !filter_dims || !out || !input || !output ||
        operation < DSA_DW_OP_AVGPOOL_S8 || operation > DSA_DW_OP_MINPOOL_S8)
        return 1;
    if (in->n <= 0 || out->n != in->n || in->h <= 0 || in->w <= 0 ||
        in->c <= 0 || out->h <= 0 || out->w <= 0 || out->c != in->c ||
        filter_dims->h <= 0 || filter_dims->w <= 0 ||
        p->stride.h <= 0 || p->stride.w <= 0 ||
        p->padding.h < 0 || p->padding.w < 0 ||
        p->activation.min < -128 || p->activation.max > 127 ||
        p->activation.min > p->activation.max) return 1;
    last_y = (int64_t)(out->h - 1) * p->stride.h - p->padding.h;
    last_x = (int64_t)(out->w - 1) * p->stride.w - p->padding.w;
    if (p->padding.h >= filter_dims->h || p->padding.w >= filter_dims->w ||
        last_y >= in->h || last_x >= in->w) return 1;
    if (!dw_pool_nn_dim(in->h) || !dw_pool_nn_dim(in->w) ||
        !dw_pool_nn_dim(in->c) || !dw_pool_nn_dim(out->h) ||
        !dw_pool_nn_dim(out->w) || !dw_pool_nn_dim(filter_dims->h) ||
        !dw_pool_nn_dim(filter_dims->w) || !dw_pool_nn_dim(p->stride.h) ||
        !dw_pool_nn_dim(p->stride.w) || p->padding.h > 65535 ||
        p->padding.w > 65535) return 0;
    taps = (uint64_t)filter_dims->h * filter_dims->w;
    input_batch = (uint64_t)in->h * in->w * in->c;
    output_batch = (uint64_t)out->h * out->w * out->c;
    if (taps > DSA_DW_POOL_MAX_TAPS || input_batch > UINT32_MAX ||
        output_batch > UINT32_MAX) return 0;
    if (!dw_pool_nn_address(input, input_batch * (uint32_t)in->n) ||
        !dw_pool_nn_address(output, output_batch * (uint32_t)in->n) ||
        !dw_pool_nn_separate(input, input_batch * (uint32_t)in->n,
                             output, output_batch * (uint32_t)in->n)) return 0;

    dsa_dw_pool_config_init(&c);
    c.operation = operation;
    c.input_base = (uint32_t)(uintptr_t)input;
    c.output_base = (uint32_t)(uintptr_t)output;
    c.input_h = (uint32_t)in->h; c.input_w = (uint32_t)in->w;
    c.input_c = (uint32_t)in->c;
    c.kernel_h = (uint32_t)filter_dims->h; c.kernel_w = (uint32_t)filter_dims->w;
    c.output_h = (uint32_t)out->h; c.output_w = (uint32_t)out->w;
    c.stride_h = (uint32_t)p->stride.h; c.stride_w = (uint32_t)p->stride.w;
    c.pad_top = (uint32_t)p->padding.h; c.pad_left = (uint32_t)p->padding.w;
    c.activation_min = p->activation.min; c.activation_max = p->activation.max;
    if (dsa_dw_pool_validate(&c) != DSA_SUCCESS ||
        !dw_pool_nn_capable(DSA_DW_POOL_CAP_POOL_S8, (uint32_t)taps)) return 0;
    return dw_pool_nn_run_batches(&c, (uint32_t)in->n, input_batch, output_batch, status);
#endif
}

riscv_nmsis_nn_status riscv_depthwise_conv_s8_acc(
    const nmsis_nn_context *ctx, const nmsis_nn_dw_conv_params *p,
    const nmsis_nn_per_channel_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *filter_dims, const int8_t *filter,
    const nmsis_nn_dims *bias_dims, const int32_t *bias,
    const nmsis_nn_dims *out, int8_t *output)
{
    return riscv_depthwise_conv_wrapper_s8(ctx, p, q, in, input,
                                           filter_dims, filter, bias_dims, bias, out, output);
}

riscv_nmsis_nn_status riscv_depthwise_conv_wrapper_s8_acc(
    const nmsis_nn_context *ctx, const nmsis_nn_dw_conv_params *p,
    const nmsis_nn_per_channel_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *filter_dims, const int8_t *filter,
    const nmsis_nn_dims *bias_dims, const int32_t *bias,
    const nmsis_nn_dims *out, int8_t *output)
{
    return riscv_depthwise_conv_wrapper_s8(ctx, p, q, in, input,
                                           filter_dims, filter, bias_dims, bias, out, output);
}

int32_t riscv_depthwise_conv_wrapper_s8_get_buffer_size_acc(
    const nmsis_nn_dw_conv_params *p, const nmsis_nn_dims *in,
    const nmsis_nn_dims *filter_dims, const nmsis_nn_dims *out)
{
    return riscv_depthwise_conv_wrapper_s8_get_buffer_size(p, in, filter_dims, out);
}
