/* SPDX-License-Identifier: Apache-2.0 */
#include <limits.h>
#include <stdint.h>
#include "dsa_accel.h"
#include "riscv_nnfunctions.h"

#ifndef DSA_NN_CONV_DATAFLOW_MODE
#define DSA_NN_CONV_DATAFLOW_MODE 0
#endif
#if DSA_NN_CONV_DATAFLOW_MODE != 0 && DSA_NN_CONV_DATAFLOW_MODE != 1
#error "DSA_NN_CONV_DATAFLOW_MODE must be 0 (WS) or 1 (IS)"
#endif

#if DSA_NN_VECTOR_ENABLE
static int vector_engine_nn_dim(int32_t value)
{
    return value > 0 && value <= 65535;
}

static int vector_engine_nn_address(const void *pointer, uint64_t bytes)
{
    return pointer && (uintptr_t)pointer <= UINT32_MAX && bytes &&
           (uint64_t)(uintptr_t)pointer + bytes < (UINT64_C(1) << 32);
}

static int vector_engine_nn_separate(const void *a, uint64_t a_bytes,
                               const void *b, uint64_t b_bytes)
{
    return (uint64_t)(uintptr_t)a + a_bytes <= (uintptr_t)b ||
           (uint64_t)(uintptr_t)b + b_bytes <= (uintptr_t)a;
}

static int vector_engine_nn_capable(uint32_t required, uint32_t taps)
{
    const uint32_t caps = dsa_vector_capabilities();
    const uint32_t limit = (required == DSA_VECTOR_CAP_POOL_S8 && (caps & DSA_VECTOR_CAP_LARGE_POOL))
        ? dsa_reg_read(NPU_REG_POOL_MAX_TAPS) : ((caps >> 16) & 0xffu);
    return (caps & required) == required && ((caps >> 8) & 0xffu) && taps <= limit;
}

static int vector_engine_nn_run_batches(dsa_vector_config_t *config,
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
        result = dsa_vector_execute(config);
        if (result != DSA_SUCCESS) {
            if (!batch && result == DSA_ERR_UNSUPPORTED) return 0;
            *status = RISCV_NMSIS_NN_NO_IMPL_ERROR;
            return 1;
        }
    }
    *status = RISCV_NMSIS_NN_SUCCESS;
    return 1;
}

static int vector_engine_nn_run_single_input_conv(
    const nmsis_nn_context *ctx, const nmsis_nn_dw_conv_params *p,
    const nmsis_nn_per_channel_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *filter_dims, const int8_t *filter,
    const int32_t *bias, const nmsis_nn_dims *out, int8_t *output,
    uint64_t input_batch, uint64_t output_batch, uint32_t taps,
    riscv_nmsis_nn_status *status)
{
    dsa_conv_s8_config_t c = {0};
    const uint32_t channels = (uint32_t)out->c;
    const uint32_t weight_bytes = taps * channels;
    const uint64_t parameter_bytes = channels * 4u;
    const uint64_t input_bytes = input_batch * (uint32_t)in->n;
    const uint64_t output_bytes = output_batch * (uint32_t)in->n;
    const uint32_t required_caps = DSA_CONV_CAP_S8 | DSA_CONV_CAP_NARROW_READ |
        (DSA_NN_CONV_DATAFLOW_MODE ? DSA_CONV_CAP_IS : 0u);
    int64_t lo, hi;
    uint64_t bound;
    int8_t *converted;
    if (!ctx || ctx->size < (int32_t)weight_bytes ||
        !vector_engine_nn_address(ctx->buf, weight_bytes)) return 0;
    converted = (int8_t *)ctx->buf;
    if (!vector_engine_nn_separate(converted, weight_bytes, input, input_bytes) ||
        !vector_engine_nn_separate(converted, weight_bytes, filter, weight_bytes) ||
        !vector_engine_nn_separate(converted, weight_bytes, output, output_bytes) ||
        !vector_engine_nn_separate(converted, weight_bytes, q->multiplier, parameter_bytes) ||
        !vector_engine_nn_separate(converted, weight_bytes, q->shift, parameter_bytes) ||
        (bias && !vector_engine_nn_separate(converted, weight_bytes, bias, parameter_bytes)) ||
        !vector_engine_nn_separate(converted, weight_bytes, ctx, sizeof(*ctx)) ||
        !vector_engine_nn_separate(converted, weight_bytes, p, sizeof(*p)) ||
        !vector_engine_nn_separate(converted, weight_bytes, q, sizeof(*q)) ||
        !vector_engine_nn_separate(converted, weight_bytes, in, sizeof(*in)) ||
        !vector_engine_nn_separate(converted, weight_bytes, filter_dims, sizeof(*filter_dims)) ||
        !vector_engine_nn_separate(converted, weight_bytes, out, sizeof(*out)) ||
        !vector_engine_nn_separate(converted, weight_bytes, status, sizeof(*status))) return 0;

    c.input_base = (uint32_t)(uintptr_t)input;
    c.filter_base = (uint32_t)(uintptr_t)converted;
    c.output_base = (uint32_t)(uintptr_t)output;
    c.bias_base = (uint32_t)(uintptr_t)bias;
    c.multiplier_base = (uint32_t)(uintptr_t)q->multiplier;
    c.shift_base = (uint32_t)(uintptr_t)q->shift;
    c.input_h = (uint32_t)in->h; c.input_w = (uint32_t)in->w;
    c.input_c = c.group_c = 1u;
    c.kernel_h = (uint32_t)filter_dims->h; c.kernel_w = (uint32_t)filter_dims->w;
    c.output_h = (uint32_t)out->h; c.output_w = (uint32_t)out->w;
    c.output_channels = c.dst_row_stride = channels;
    c.stride_h = (uint32_t)p->stride.h; c.stride_w = (uint32_t)p->stride.w;
    c.dilation_h = (uint32_t)p->dilation.h; c.dilation_w = (uint32_t)p->dilation.w;
    c.pad_top = (uint32_t)p->padding.h; c.pad_left = (uint32_t)p->padding.w;
    c.input_offset = p->input_offset; c.output_offset = p->output_offset;
    c.activation_min = p->activation.min; c.activation_max = p->activation.max;
    c.dataflow_mode = DSA_NN_CONV_DATAFLOW_MODE;
    if (dsa_conv_s8_validate(&c) != DSA_SUCCESS ||
        !vector_engine_nn_capable(DSA_VECTOR_CAP_DW_S8, taps) ||
        (dsa_conv_capabilities() & required_caps) != required_caps) return 0;

    /* Bound s32 accumulation and left shifts before reading or writing the
     * conversion buffer. The channel parameters retain NMSIS requantization. */
    lo = -128 + p->input_offset; hi = 127 + p->input_offset;
    if (lo < 0) lo = -lo;
    if (hi < 0) hi = -hi;
    bound = (uint64_t)(lo > hi ? lo : hi) * 128u * taps;
    for (uint32_t oc = 0u; oc < channels; ++oc) {
        const int32_t shift = q->shift[oc];
        int64_t abs_bias = bias ? bias[oc] : 0;
        uint64_t channel_bound;
        if (abs_bias < 0) abs_bias = -abs_bias;
        if (shift < -31 || shift > 30 || q->multiplier[oc] < 0) return 0;
        channel_bound = bound + (uint64_t)abs_bias;
        if (channel_bound > INT32_MAX) return 0;
    }
    if (dsa_reg_read(NPU_REG_STATUS) & (1u << 1)) {
        *status = RISCV_NMSIS_NN_NO_IMPL_ERROR;
        return 1;
    }

    /* Source layout is [KH, KW, Cout]; Conv consumes [Cout, KH, KW, 1].
     * Convert once and share the bounded buffer across all batches. */
    for (uint32_t oc = 0u; oc < channels; ++oc)
        for (uint32_t tap = 0u; tap < taps; ++tap)
            converted[oc * taps + tap] = filter[tap * channels + oc];
    for (uint32_t batch = 0u; batch < (uint32_t)in->n; ++batch) {
        c.input_base = (uint32_t)((uint64_t)(uintptr_t)input + batch * input_batch);
        c.output_base = (uint32_t)((uint64_t)(uintptr_t)output + batch * output_batch);
        if (dsa_conv_s8_execute(&c) != DSA_SUCCESS) {
            *status = RISCV_NMSIS_NN_NO_IMPL_ERROR;
            return 1;
        }
    }
    *status = RISCV_NMSIS_NN_SUCCESS;
    return 1;
}
#endif

int riscv_depthwise_conv_s8_try_dsa(
    const nmsis_nn_context *ctx,
    const nmsis_nn_dw_conv_params *p,
    const nmsis_nn_per_channel_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *filter_dims, const int8_t *filter,
    const int32_t *bias, const nmsis_nn_dims *out, int8_t *output,
    riscv_nmsis_nn_status *status)
{
#if !DSA_NN_VECTOR_ENABLE
    (void)ctx; (void)p; (void)q; (void)in; (void)input; (void)filter_dims; (void)filter;
    (void)bias; (void)out; (void)output; (void)status;
    return 0;
#else
    dsa_vector_config_t c;
    uint64_t input_batch, output_batch, taps, parameters;
    if (!dsa_nn_accelerator_enabled(DSA_NN_ACCEL_DW) || !status) return 0;
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
    if ((p->ch_mult != 1 &&
         !riscv_depthwise_conv_s8_dsa_buffer_size(p, in, filter_dims, out)) ||
        !vector_engine_nn_dim(in->h) ||
        !vector_engine_nn_dim(in->w) || !vector_engine_nn_dim(in->c) ||
        !vector_engine_nn_dim(out->h) || !vector_engine_nn_dim(out->w) ||
        !vector_engine_nn_dim(filter_dims->h) || !vector_engine_nn_dim(filter_dims->w) ||
        !vector_engine_nn_dim(p->stride.h) || !vector_engine_nn_dim(p->stride.w) ||
        !vector_engine_nn_dim(p->dilation.h) || !vector_engine_nn_dim(p->dilation.w) ||
        p->padding.h > 65535 || p->padding.w > 65535) return 0;

    taps = (uint64_t)filter_dims->h * filter_dims->w;
    input_batch = (uint64_t)in->h * in->w * in->c;
    output_batch = (uint64_t)out->h * out->w * out->c;
    parameters = (uint64_t)out->c * 4u;
    if (taps > DSA_DW_MAX_TAPS || input_batch > UINT32_MAX ||
        output_batch > UINT32_MAX) return 0;
    if (!vector_engine_nn_address(input, input_batch * (uint32_t)in->n) ||
        !vector_engine_nn_address(output, output_batch * (uint32_t)in->n) ||
        !vector_engine_nn_address(filter, taps * (uint32_t)out->c) ||
        !vector_engine_nn_address(q->multiplier, parameters) ||
        !vector_engine_nn_address(q->shift, parameters) ||
        (bias && !vector_engine_nn_address(bias, parameters))) return 0;
    if (!vector_engine_nn_separate(input, input_batch * (uint32_t)in->n,
                             output, output_batch * (uint32_t)in->n) ||
        !vector_engine_nn_separate(filter, taps * (uint32_t)out->c,
                             output, output_batch * (uint32_t)in->n) ||
        !vector_engine_nn_separate(q->multiplier, parameters,
                             output, output_batch * (uint32_t)in->n) ||
        !vector_engine_nn_separate(q->shift, parameters,
                             output, output_batch * (uint32_t)in->n) ||
        (bias && !vector_engine_nn_separate(bias, parameters,
                                      output, output_batch * (uint32_t)in->n))) return 0;

    if (p->ch_mult != 1)
        return vector_engine_nn_run_single_input_conv(ctx, p, q, in, input,
            filter_dims, filter, bias, out, output, input_batch, output_batch,
            (uint32_t)taps, status);

    dsa_vector_config_init(&c);
    c.operation = DSA_VECTOR_OP_DW_S8;
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
    if (dsa_vector_validate(&c) != DSA_SUCCESS ||
        !vector_engine_nn_capable(DSA_VECTOR_CAP_DW_S8, (uint32_t)taps)) return 0;
    /* Only dimensions and addresses are inspected here. The engine loads
     * tensor data, bias, multipliers and shifts through DMA. */
    return vector_engine_nn_run_batches(&c, (uint32_t)in->n, input_batch, output_batch, status);
#endif
}

int riscv_pool_s8_try_dsa(
    uint32_t operation, const nmsis_nn_pool_params *p,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *filter_dims,
    const nmsis_nn_dims *out, int8_t *output,
    riscv_nmsis_nn_status *status)
{
#if !DSA_NN_VECTOR_ENABLE
    (void)operation; (void)p; (void)in; (void)input;
    (void)filter_dims; (void)out; (void)output; (void)status;
    return 0;
#else
    dsa_vector_config_t c;
    uint64_t input_batch, output_batch, taps;
    int64_t last_y, last_x;
    if (!dsa_nn_accelerator_enabled(DSA_NN_ACCEL_POOL) || !status) return 0;
    *status = RISCV_NMSIS_NN_ARG_ERROR;
    if (!p || !in || !filter_dims || !out || !input || !output ||
        operation < DSA_VECTOR_OP_AVGPOOL_S8 || operation > DSA_VECTOR_OP_MINPOOL_S8)
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
    if (!vector_engine_nn_dim(in->h) || !vector_engine_nn_dim(in->w) ||
        !vector_engine_nn_dim(in->c) || !vector_engine_nn_dim(out->h) ||
        !vector_engine_nn_dim(out->w) || !vector_engine_nn_dim(filter_dims->h) ||
        !vector_engine_nn_dim(filter_dims->w) || !vector_engine_nn_dim(p->stride.h) ||
        !vector_engine_nn_dim(p->stride.w) || p->padding.h > 65535 ||
        p->padding.w > 65535) return 0;
    taps = (uint64_t)filter_dims->h * filter_dims->w;
    input_batch = (uint64_t)in->h * in->w * in->c;
    output_batch = (uint64_t)out->h * out->w * out->c;
    if (taps > DSA_POOL_MAX_TAPS || input_batch > UINT32_MAX ||
        output_batch > UINT32_MAX) return 0;
    if (!vector_engine_nn_address(input, input_batch * (uint32_t)in->n) ||
        !vector_engine_nn_address(output, output_batch * (uint32_t)in->n) ||
        !vector_engine_nn_separate(input, input_batch * (uint32_t)in->n,
                             output, output_batch * (uint32_t)in->n)) return 0;

    dsa_vector_config_init(&c);
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
    if (dsa_vector_validate(&c) != DSA_SUCCESS ||
        !vector_engine_nn_capable(DSA_VECTOR_CAP_POOL_S8, (uint32_t)taps)) return 0;
    return vector_engine_nn_run_batches(&c, (uint32_t)in->n, input_batch, output_batch, status);
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
