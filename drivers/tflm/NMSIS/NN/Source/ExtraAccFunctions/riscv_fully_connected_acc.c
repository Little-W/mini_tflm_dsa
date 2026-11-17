#include "riscv_nn_mat_mult_acc.h"
#include "riscv_nnfunctions.h"
#include "riscv_nnsupportfunctions.h"
#include <stdio.h>
#include <string.h>

#include "dsa_accel.h"

#if defined(DSA_SIM_INSTRUMENT)
volatile uint32_t dsa_sim_fc_call_count = 0;
#endif

#ifndef DSA_NN_FC_ENABLE
#define DSA_NN_FC_ENABLE 1
#endif

riscv_nmsis_nn_status riscv_fully_connected_s16_s32_bias_acc(
    const nmsis_nn_context *ctx, const nmsis_nn_fc_params *fc_params,
    const nmsis_nn_quant_params *quant_params,
    const nmsis_nn_dims *input_dims, const int16_t *input,
    const nmsis_nn_dims *filter_dims, const int8_t *kernel,
    const nmsis_nn_dims *bias_dims, const int32_t *bias,
    const nmsis_nn_dims *output_dims, int16_t *output)
{
    (void)ctx;
    (void)bias_dims;

#if defined(DSA_SIM_INSTRUMENT)
    ++dsa_sim_fc_call_count;
#endif

#if !DSA_NN_FC_ENABLE
    for (int32_t batch = 0; batch < input_dims->n; ++batch) {
        for (int32_t channel = 0; channel < output_dims->c; ++channel) {
            int64_t accumulator = bias ? bias[channel] : 0;
            for (int32_t col = 0; col < filter_dims->n; ++col)
                accumulator += ((int32_t)input[batch * filter_dims->n + col] + fc_params->input_offset) *
                               ((int32_t)kernel[channel * filter_dims->n + col] + fc_params->filter_offset);
            const int32_t index = quant_params->is_per_channel ? channel : 0;
            int32_t value = riscv_nn_requantize_s64(accumulator,
                REDUCE_MULTIPLIER(quant_params->multiplier[index]), quant_params->shift[index]);
            value = riscv_nn_add_s32_sat(value, fc_params->output_offset);
            output[batch * output_dims->c + channel] = (int16_t)MAX(fc_params->activation.min,
                                                                          MIN(fc_params->activation.max, value));
        }
    }
    return RISCV_NMSIS_NN_SUCCESS;
#else
    dsa_matmul_config_t cfg;
    dsa_matmul_config_init(&cfg);
    cfg.lhs_dtype = DSA_DTYPE_S16;
    cfg.rhs_dtype = DSA_DTYPE_S8;
    cfg.bias_dtype = DSA_DTYPE_S32;
    cfg.out_dtype = DSA_DTYPE_S16;
    cfg.dataflow_mode = DSA_DATAFLOW_WS;

    cfg.lhs_ptr = input;
    cfg.rhs_ptr = kernel;
    cfg.dst_ptr = output;
    cfg.bias_ptr = bias;

    cfg.K = (uint32_t)input_dims->n;
    cfg.N = (uint32_t)filter_dims->n;
    cfg.M = (uint32_t)output_dims->c;
    cfg.lhs_row_stride = cfg.N * sizeof(int16_t);
    cfg.rhs_row_stride = cfg.N * sizeof(int8_t);
    cfg.dst_row_stride = cfg.M * sizeof(int16_t);

    cfg.quant_mode = quant_params->is_per_channel ? DSA_QUANT_PER_CHANNEL
                                                  : DSA_QUANT_PER_TENSOR;
    cfg.lhs_offset = fc_params->input_offset;
    cfg.rhs_offset = fc_params->filter_offset;
    cfg.dst_offset = fc_params->output_offset;
    if (quant_params->is_per_channel) {
        cfg.dst_mult_ptr = quant_params->multiplier;
        cfg.dst_shift_ptr = quant_params->shift;
    } else {
        cfg.dst_mult = *quant_params->multiplier;
        cfg.dst_shift = *quant_params->shift;
    }
    cfg.act_min = fc_params->activation.min;
    cfg.act_max = fc_params->activation.max;

    return dsa_matmul_execute(&cfg) == DSA_SUCCESS
               ? RISCV_NMSIS_NN_SUCCESS
               : RISCV_NMSIS_NN_FAILURE;
#endif
}


#if DSA_NN_FC_ENABLE
static int fc_s8_address(const void *pointer, uint64_t bytes)
{
    return pointer && (uintptr_t)pointer <= UINT32_MAX && bytes &&
           (uint64_t)(uintptr_t)pointer + bytes < (UINT64_C(1) << 32);
}

static int fc_s8_separate(const void *a, uint64_t a_bytes,
                         const void *b, uint64_t b_bytes)
{
    return (uint64_t)(uintptr_t)a + a_bytes <= (uintptr_t)b ||
           (uint64_t)(uintptr_t)b + b_bytes <= (uintptr_t)a;
}

static int fc_s8_hardware_supported(
    const nmsis_nn_fc_params *p, const int32_t *mult, const int32_t *shift,
    int per_channel, const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *f, const int8_t *filter, const int32_t *bias,
    const nmsis_nn_dims *out, int8_t *output)
{
    const uint64_t input_bytes = (uint64_t)in->n * f->n;
    const uint64_t output_bytes = (uint64_t)in->n * out->c;
    const uint64_t weight_bytes = (uint64_t)f->n * out->c;
    const uint64_t parameter_bytes = (uint64_t)out->c * sizeof(int32_t);
    uint64_t bound;
    int64_t input_lo, input_hi, weight_lo, weight_hi;
    if (!dsa_nn_accelerator_enabled(DSA_NN_ACCEL_FC) ||
        in->n > 65535 || f->n > 65535 || out->c > 65535 ||
        !fc_s8_address(input, input_bytes) || !fc_s8_address(filter, weight_bytes) ||
        !fc_s8_address(output, output_bytes) ||
        !fc_s8_separate(input, input_bytes, output, output_bytes) ||
        !fc_s8_separate(filter, weight_bytes, output, output_bytes) ||
        (bias && (!fc_s8_address(bias, parameter_bytes) || ((uintptr_t)bias & 3u) ||
                  !fc_s8_separate(bias, parameter_bytes, output, output_bytes)))) return 0;
    if (per_channel && (!fc_s8_address(mult, parameter_bytes) ||
                        !fc_s8_address(shift, parameter_bytes) ||
                        (((uintptr_t)mult | (uintptr_t)shift) & 3u) ||
                        !fc_s8_separate(mult, parameter_bytes, output, output_bytes) ||
                        !fc_s8_separate(shift, parameter_bytes, output, output_bytes))) return 0;
    input_lo = -128 + p->input_offset;
    input_hi = 127 + p->input_offset;
    weight_lo = -128 + p->filter_offset;
    weight_hi = 127 + p->filter_offset;
    if (input_lo < 0) input_lo = -input_lo;
    if (input_hi < 0) input_hi = -input_hi;
    if (weight_lo < 0) weight_lo = -weight_lo;
    if (weight_hi < 0) weight_hi = -weight_hi;
    bound = (uint64_t)(input_lo > input_hi ? input_lo : input_hi) *
            (uint64_t)(weight_lo > weight_hi ? weight_lo : weight_hi) * f->n;
    for (int32_t channel = 0; channel < out->c; ++channel) {
        const int32_t index = per_channel ? channel : 0;
        int64_t magnitude = bias ? bias[channel] : 0;
        uint64_t total;
        if (mult[index] < 0 || shift[index] < -31 || shift[index] > 30) return 0;
        if (magnitude < 0) magnitude = -magnitude;
        total = bound + (uint64_t)magnitude;
        if (total > INT32_MAX) return 0;
    }
    return dsa_reg_read(NPU_REG_ID) == 0x4e505531u &&
           dsa_reg_read(NPU_REG_CONFIG_ABI) == 2u;
}
#endif

static riscv_nmsis_nn_status fc_s8_dispatch(
    const nmsis_nn_context *ctx, const nmsis_nn_fc_params *p,
    const int32_t *mult, const int32_t *shift, int per_channel,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *f, const int8_t *filter,
    const nmsis_nn_dims *bd, const int32_t *bias,
    const nmsis_nn_dims *out, int8_t *output)
{
    const nmsis_nn_context empty_context = {0};
    if (!p || !mult || !shift || !in || !f || !out || !input || !filter || !output ||
        in->n <= 0 || f->n <= 0 || out->c <= 0 ||
        p->input_offset < -127 || p->input_offset > 128 ||
        p->filter_offset < -127 || p->filter_offset > 128 ||
        p->output_offset < -128 || p->output_offset > 127 ||
        p->activation.min < -128 || p->activation.max > 127 ||
        p->activation.min > p->activation.max) return RISCV_NMSIS_NN_ARG_ERROR;
#if DSA_NN_FC_ENABLE
    if (fc_s8_hardware_supported(p, mult, shift, per_channel,
                                 in, input, f, filter, bias, out, output)) {
        dsa_matmul_config_t c;
        uint32_t result;
        if (dsa_reg_read(NPU_REG_STATUS) & (1u << 1)) return RISCV_NMSIS_NN_NO_IMPL_ERROR;
        dsa_matmul_config_init(&c);
        c.lhs_ptr = input; c.rhs_ptr = filter; c.dst_ptr = output; c.bias_ptr = bias;
        c.K = (uint32_t)in->n; c.N = (uint32_t)f->n; c.M = (uint32_t)out->c;
        c.lhs_row_stride = c.N; c.rhs_row_stride = c.N; c.dst_row_stride = c.M;
        c.quant_mode = per_channel ? DSA_QUANT_PER_CHANNEL : DSA_QUANT_PER_TENSOR;
        c.lhs_offset = p->input_offset; c.rhs_offset = p->filter_offset;
        c.dst_offset = p->output_offset;
        c.act_min = p->activation.min; c.act_max = p->activation.max;
        if (per_channel) { c.dst_mult_ptr = mult; c.dst_shift_ptr = shift; }
        else { c.dst_mult = mult[0]; c.dst_shift = shift[0]; }
        result = dsa_matmul_execute(&c);
        return result == DSA_SUCCESS ? RISCV_NMSIS_NN_SUCCESS : RISCV_NMSIS_NN_NO_IMPL_ERROR;
    }
#endif
    if (!ctx) ctx = &empty_context;
    if (per_channel) {
        const nmsis_nn_per_channel_quant_params q = {(int32_t *)mult, (int32_t *)shift};
        return riscv_fully_connected_per_channel_s8(ctx, p, &q, in, input, f, filter, bd, bias, out, output);
    } else {
        const nmsis_nn_per_tensor_quant_params q = {mult[0], shift[0]};
        return riscv_fully_connected_s8(ctx, p, &q, in, input, f, filter, bd, bias, out, output);
    }
}

riscv_nmsis_nn_status riscv_fully_connected_s8_acc(
    const nmsis_nn_context *ctx, const nmsis_nn_fc_params *p,
    const nmsis_nn_per_tensor_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *f, const int8_t *filter,
    const nmsis_nn_dims *bd, const int32_t *bias,
    const nmsis_nn_dims *out, int8_t *output)
{
    if (!q) return RISCV_NMSIS_NN_ARG_ERROR;
    return fc_s8_dispatch(ctx, p, &q->multiplier, &q->shift, 0,
                          in, input, f, filter, bd, bias, out, output);
}

riscv_nmsis_nn_status riscv_fully_connected_per_channel_s8_acc(
    const nmsis_nn_context *ctx, const nmsis_nn_fc_params *p,
    const nmsis_nn_per_channel_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *f, const int8_t *filter,
    const nmsis_nn_dims *bd, const int32_t *bias,
    const nmsis_nn_dims *out, int8_t *output)
{
    if (!q) return RISCV_NMSIS_NN_ARG_ERROR;
    return fc_s8_dispatch(ctx, p, q->multiplier, q->shift, 1,
                          in, input, f, filter, bd, bias, out, output);
}

riscv_nmsis_nn_status riscv_fully_connected_wrapper_s8_acc(
    const nmsis_nn_context *ctx, const nmsis_nn_fc_params *p,
    const nmsis_nn_quant_params *q,
    const nmsis_nn_dims *in, const int8_t *input,
    const nmsis_nn_dims *f, const int8_t *filter,
    const nmsis_nn_dims *bd, const int32_t *bias,
    const nmsis_nn_dims *out, int8_t *output)
{
    if (!q) return RISCV_NMSIS_NN_ARG_ERROR;
    return fc_s8_dispatch(ctx, p, q->multiplier, q->shift, q->is_per_channel,
                          in, input, f, filter, bd, bias, out, output);
}
