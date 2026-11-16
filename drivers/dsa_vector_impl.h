/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_VECTOR_IMPL_H
#define DSA_VECTOR_IMPL_H

#ifndef DSA_VECTOR_TIMEOUT
#ifdef DSA_DW_POOL_TIMEOUT
#define DSA_VECTOR_TIMEOUT DSA_DW_POOL_TIMEOUT
#else
#define DSA_VECTOR_TIMEOUT DSA_MATMUL_TIMEOUT
#endif
#endif

static int dsa_vector_dim(uint32_t value)
{
    return value != 0u && value <= 65535u;
}

static int dsa_vector_span(uint32_t base, uint64_t bytes)
{
    return base != 0u && bytes != 0u &&
           (uint64_t)base + bytes < (UINT64_C(1) << 32);
}

static int dsa_vector_separate(uint32_t a, uint64_t a_bytes,
                                uint32_t b, uint64_t b_bytes)
{
    return (uint64_t)a + a_bytes <= b || (uint64_t)b + b_bytes <= a;
}

static uint32_t dsa_vector_pair(uint32_t first, uint32_t second)
{
    return first | (second << 16);
}

void dsa_vector_config_init(dsa_vector_config_t *c)
{
    if (c) {
        const dsa_vector_config_t initial = {
            .stride_h = 1u, .stride_w = 1u,
            .dilation_h = 1u, .dilation_w = 1u,
            .activation_min = -128, .activation_max = 127
        };
        *c = initial;
    }
}

uint32_t dsa_vector_capabilities(void)
{
    uint32_t caps;
    if (dsa_reg_read(NPU_REG_ID) != 0x4e505531u ||
        dsa_reg_read(NPU_REG_CONFIG_ABI) != 2u) return 0u;
    caps = dsa_reg_read(NPU_REG_VECTOR_CAPS);
    return (caps >> 24) == DSA_VECTOR_CAP_VERSION ? caps : 0u;
}

uint32_t dsa_vector_validate(const dsa_vector_config_t *c)
{
    uint64_t input_bytes, output_bytes, taps, parameters;
    if (!c) return DSA_ERR_NULL_PTR;
    if (c->operation > DSA_VECTOR_OP_SOFTMAX_S8 || c->vector_s16 > 1u ||
        c->bypass_cache > 1u) return DSA_ERR_INVALID_DIM;

    if (c->operation == DSA_VECTOR_OP_SOFTMAX_S8) {
        if (c->vector_s16 || !c->length || (c->rhs_base & 3u) ||
            !dsa_vector_span(c->input_base, c->length) ||
            !dsa_vector_span(c->rhs_base, 1024u) ||
            !dsa_vector_span(c->output_base, c->length) ||
            !dsa_vector_separate(c->input_base, c->length, c->output_base, c->length) ||
            !dsa_vector_separate(c->rhs_base, 1024u, c->output_base, c->length))
            return DSA_ERR_INVALID_DIM;
        return DSA_SUCCESS;
    }

    if (c->operation == DSA_VECTOR_OP_ADD_S8) {
        if (c->vector_s16 || !c->length ||
            !dsa_vector_add_quantization_valid(&c->add, c->output_offset,
                                               c->activation_min, c->activation_max) ||
            !dsa_vector_span(c->input_base, c->length) ||
            !dsa_vector_span(c->rhs_base, c->length) ||
            !dsa_vector_span(c->output_base, c->length) ||
            !dsa_vector_separate(c->input_base, c->length, c->output_base, c->length) ||
            !dsa_vector_separate(c->rhs_base, c->length, c->output_base, c->length))
            return DSA_ERR_INVALID_DIM;
        return DSA_SUCCESS;
    }

    if (c->operation >= DSA_VECTOR_OP_SUM) {
        input_bytes = (uint64_t)c->length * (c->vector_s16 ? 2u : 1u);
        output_bytes = c->operation == DSA_VECTOR_OP_HADAMARD ?
                       (uint64_t)c->length * 4u : 4u;
        if (!c->length || !dsa_vector_span(c->input_base, input_bytes) ||
            !dsa_vector_span(c->output_base, output_bytes) ||
            !dsa_vector_separate(c->input_base, input_bytes, c->output_base, output_bytes) ||
            (c->output_base & 3u) ||
            (c->vector_s16 && (c->input_base & 1u))) return DSA_ERR_INVALID_DIM;
        if (c->operation >= DSA_VECTOR_OP_DOT &&
            (!dsa_vector_span(c->rhs_base, input_bytes) ||
             !dsa_vector_separate(c->rhs_base, input_bytes, c->output_base, output_bytes) ||
             (c->vector_s16 && (c->rhs_base & 1u)))) return DSA_ERR_INVALID_DIM;
        return DSA_SUCCESS;
    }

    if (c->vector_s16 || !dsa_vector_dim(c->input_h) ||
        !dsa_vector_dim(c->input_w) || !dsa_vector_dim(c->input_c) ||
        !dsa_vector_dim(c->kernel_h) || !dsa_vector_dim(c->kernel_w) ||
        !dsa_vector_dim(c->output_h) || !dsa_vector_dim(c->output_w) ||
        !dsa_vector_dim(c->stride_h) || !dsa_vector_dim(c->stride_w) ||
        !dsa_vector_dim(c->dilation_h) || !dsa_vector_dim(c->dilation_w) ||
        c->pad_top > 65535u || c->pad_left > 65535u ||
        c->activation_min < -128 || c->activation_max > 127 ||
        c->activation_min > c->activation_max) return DSA_ERR_INVALID_DIM;

    taps = (uint64_t)c->kernel_h * c->kernel_w;
    input_bytes = (uint64_t)c->input_h * c->input_w * c->input_c;
    output_bytes = (uint64_t)c->output_h * c->output_w * c->input_c;
    if (taps > (c->operation == DSA_VECTOR_OP_DW_S8 ? DSA_DW_MAX_TAPS : DSA_POOL_MAX_TAPS) ||
        !dsa_vector_span(c->input_base, input_bytes) ||
        !dsa_vector_span(c->output_base, output_bytes) ||
        !dsa_vector_separate(c->input_base, input_bytes, c->output_base, output_bytes))
        return DSA_ERR_INVALID_DIM;

    if (c->operation == DSA_VECTOR_OP_DW_S8) {
        parameters = (uint64_t)c->input_c * 4u;
        if (c->input_offset < -127 || c->input_offset > 128 ||
            c->output_offset < -128 || c->output_offset > 127 ||
            !dsa_vector_span(c->rhs_base, taps * c->input_c) ||
            !dsa_vector_span(c->multiplier_base, parameters) ||
            !dsa_vector_span(c->shift_base, parameters) ||
            !dsa_vector_separate(c->rhs_base, taps * c->input_c, c->output_base, output_bytes) ||
            !dsa_vector_separate(c->multiplier_base, parameters, c->output_base, output_bytes) ||
            !dsa_vector_separate(c->shift_base, parameters, c->output_base, output_bytes) ||
            ((c->multiplier_base | c->shift_base | c->bias_base) & 3u) ||
            (c->bias_base && (!dsa_vector_span(c->bias_base, parameters) ||
             !dsa_vector_separate(c->bias_base, parameters, c->output_base, output_bytes))))
            return DSA_ERR_INVALID_DIM;
    } else {
        /* With unit dilation and positive strides, checking the first and
         * final window in each axis also covers every intermediate window. */
        const int64_t last_y = (int64_t)(c->output_h - 1u) * c->stride_h - c->pad_top;
        const int64_t last_x = (int64_t)(c->output_w - 1u) * c->stride_w - c->pad_left;
        if (c->input_offset || c->output_offset || c->dilation_h != 1u ||
            c->dilation_w != 1u || c->pad_top >= c->kernel_h ||
            c->pad_left >= c->kernel_w || last_y >= c->input_h ||
            last_x >= c->input_w) return DSA_ERR_INVALID_DIM;
    }
    return DSA_SUCCESS;
}

uint32_t dsa_vector_execute(const dsa_vector_config_t *c)
{
    uint32_t status = dsa_vector_validate(c);
    uint32_t caps, required, ctrl, polls, result, tap_capacity;
    if (status != DSA_SUCCESS) return status;
    caps = dsa_vector_capabilities();
    required = c->operation == DSA_VECTOR_OP_SOFTMAX_S8 ? DSA_VECTOR_CAP_SOFTMAX_S8 :
               c->operation == DSA_VECTOR_OP_ADD_S8 ? DSA_VECTOR_CAP_ADD_S8 :
               c->operation == DSA_VECTOR_OP_DW_S8 ? DSA_VECTOR_CAP_DW_S8 :
               c->operation < DSA_VECTOR_OP_SUM ? DSA_VECTOR_CAP_POOL_S8 :
               c->vector_s16 ? DSA_VECTOR_CAP_VECTOR_S16 : DSA_VECTOR_CAP_VECTOR_S8;
    tap_capacity = (caps >> 16) & 0xffu;
    if (c->operation >= DSA_VECTOR_OP_AVGPOOL_S8 && c->operation <= DSA_VECTOR_OP_MINPOOL_S8 &&
        (caps & DSA_VECTOR_CAP_LARGE_POOL)) tap_capacity = dsa_reg_read(NPU_REG_POOL_MAX_TAPS);
    if (!(caps & required) || !((caps >> 8) & 0xffu) ||
        (c->operation < DSA_VECTOR_OP_SUM &&
         c->kernel_h * c->kernel_w > tap_capacity))
        return DSA_ERR_UNSUPPORTED;
    if (c->operation == DSA_VECTOR_OP_SOFTMAX_S8 &&
        c->length > dsa_reg_read(NPU_REG_SOFTMAX_MAX_DEPTH)) return DSA_ERR_UNSUPPORTED;
    if (dsa_reg_read(NPU_REG_STATUS) & (1u << 1)) return DSA_ERR_BUSY;

    dsa_reg_write(NPU_REG_LHS_BASE, c->input_base);
    dsa_reg_write(NPU_REG_RHS_BASE, c->rhs_base);
    dsa_reg_write(NPU_REG_DST_BASE, c->output_base);
    dsa_reg_write(NPU_REG_BIAS_BASE, c->bias_base);
    dsa_reg_write(NPU_REG_Q_MULT, c->operation == DSA_VECTOR_OP_ADD_S8 ?
                  (uint32_t)c->add.output_multiplier : c->multiplier_base);
    dsa_reg_write(NPU_REG_Q_SHIFT, c->operation == DSA_VECTOR_OP_ADD_S8 ?
                  (uint32_t)c->add.output_shift : c->shift_base);
    dsa_reg_write(NPU_REG_LHS_ZP, c->operation == DSA_VECTOR_OP_ADD_S8 ? (uint32_t)c->add.input1_offset : 0u);
    dsa_reg_write(NPU_REG_RHS_ZP, c->operation == DSA_VECTOR_OP_ADD_S8 ? (uint32_t)c->add.input2_offset : 0u);
    dsa_reg_write(NPU_REG_DST_ZP, (uint32_t)c->output_offset);
    dsa_reg_write(NPU_REG_ACT_MIN, (uint32_t)c->activation_min);
    dsa_reg_write(NPU_REG_ACT_MAX, (uint32_t)c->activation_max);
    dsa_reg_write(NPU_REG_VECTOR_OP,
                  c->operation | (c->vector_s16 ? DSA_VECTOR_VECTOR_S16 : 0u));
    dsa_reg_write(NPU_REG_VECTOR_LENGTH, c->length);
    if (c->operation == DSA_VECTOR_OP_ADD_S8) {
        dsa_reg_write(NPU_REG_VECTOR_ADD_INPUT1_MULT, (uint32_t)c->add.input1_multiplier);
        dsa_reg_write(NPU_REG_VECTOR_ADD_INPUT1_SHIFT, (uint32_t)c->add.input1_shift);
        dsa_reg_write(NPU_REG_VECTOR_ADD_INPUT2_MULT, (uint32_t)c->add.input2_multiplier);
        dsa_reg_write(NPU_REG_VECTOR_ADD_INPUT2_SHIFT, (uint32_t)c->add.input2_shift);
        dsa_reg_write(NPU_REG_VECTOR_ADD_LEFT_SHIFT, (uint32_t)c->add.left_shift);
    }
    dsa_reg_write(NPU_REG_CONV_INPUT_BASE, c->input_base);
    if (c->operation < DSA_VECTOR_OP_SUM) {
        dsa_reg_write(NPU_REG_CONV_INPUT_HW, dsa_vector_pair(c->input_h, c->input_w));
        dsa_reg_write(NPU_REG_CONV_CHANNELS, dsa_vector_pair(c->input_c, c->input_c));
        dsa_reg_write(NPU_REG_CONV_GROUP_OFFSET, 0u);
        dsa_reg_write(NPU_REG_CONV_KERNEL_HW, dsa_vector_pair(c->kernel_h, c->kernel_w));
        dsa_reg_write(NPU_REG_CONV_OUTPUT_HW, dsa_vector_pair(c->output_h, c->output_w));
        dsa_reg_write(NPU_REG_CONV_STRIDE_HW, dsa_vector_pair(c->stride_h, c->stride_w));
        dsa_reg_write(NPU_REG_CONV_DILATION_HW, dsa_vector_pair(c->dilation_h, c->dilation_w));
        dsa_reg_write(NPU_REG_CONV_PADDING_HW, dsa_vector_pair(c->pad_top, c->pad_left));
        dsa_reg_write(NPU_REG_CONV_INPUT_OFFSET, (uint32_t)c->input_offset);
    }

    dsa_reg_write(NPU_REG_STATUS, 1u << 2);
    ctrl = (1u << 0) | (1u << 4) | NPU_CTRL_VECTOR_ENGINE;
    if (c->operation == DSA_VECTOR_OP_DW_S8) ctrl |= 1u << 2;
    if (c->bypass_cache) ctrl |= NPU_CTRL_CONV_BYPASS;
    dsa_memory_barrier();
    dsa_reg_write(NPU_REG_CTRL, ctrl);
    for (polls = 0u; polls < DSA_VECTOR_TIMEOUT; ++polls) {
        status = dsa_reg_read(NPU_REG_STATUS);
        if (status & (1u << 2)) break;
    }
    if (polls == DSA_VECTOR_TIMEOUT) return DSA_ERR_TIMEOUT;
    dsa_memory_barrier();
    result = (status & (3u << 3)) ? ((status >> 3) & 3u) : dsa_reg_read(NPU_REG_WB_DATA);
    dsa_reg_write(NPU_REG_STATUS, 1u << 2);
    dsa_memory_barrier();
    return result;
}

#endif
