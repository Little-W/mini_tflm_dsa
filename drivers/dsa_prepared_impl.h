/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_PREPARED_IMPL_H
#define DSA_PREPARED_IMPL_H
#include "dsa_prepared.h"
#include "dsa_ps_bound.h"

#define DSA_PREPARED_START (1u << 0)
#define DSA_PREPARED_S16_INPUT (1u << 1)
#define DSA_PREPARED_PER_CHANNEL (1u << 2)
#define DSA_PREPARED_IS (1u << 3)
#define DSA_PREPARED_IRQ (1u << 4)
#define DSA_PREPARED_DONE (1u << 2)
#define DSA_PREPARED_ERROR_MASK (3u << 3)

void dsa_prepared_invalidate(dsa_prepared_t *p)
{
    if (p) p->valid = 0u;
}

static void dsa_prepared_begin(dsa_prepared_t *p, uint32_t input_bytes,
                               uint32_t output_bytes, uint32_t spatial)
{
    p->input_bytes = input_bytes;
    p->output_bytes = output_bytes;
    p->spatial = spatial;
    p->register_count = 0u;
    p->readonly_count = 0u;
    p->source_filter_base = 0u;
    p->memory_policy_valid = p->ps_control = p->ia_bank_count = 0u;
}

static void dsa_prepared_register(dsa_prepared_t *p, uint32_t offset,
                                  uint32_t value)
{
    if (offset == NPU_REG_RHS_BASE) p->source_filter_base = value;
    p->registers[p->register_count].offset = offset;
    p->registers[p->register_count++].value = value;
}

static int dsa_prepared_readonly(dsa_prepared_t *p, uint32_t base,
                                  uint64_t bytes, uint32_t alignment)
{
    if (!dsa_conv_span(base, bytes) || (base & (alignment - 1u))) return 0;
    p->readonly[p->readonly_count].begin = base;
    p->readonly[p->readonly_count++].end = base + (uint32_t)bytes;
    return 1;
}

static uint64_t dsa_prepared_abs(int64_t value)
{
    return (uint64_t)(value < 0 ? -value : value);
}

static uint64_t dsa_prepared_operand_bound(int32_t offset)
{
    const uint64_t lo = dsa_prepared_abs(-128 + (int64_t)offset);
    const uint64_t hi = dsa_prepared_abs(127 + (int64_t)offset);
    return lo > hi ? lo : hi;
}

static uint32_t dsa_prepared_ps_bound(const dsa_matrix_limits_t *limits,
    uint32_t weights, uint32_t channels, uint32_t depth, uint32_t stride,
    uint32_t packed, int32_t input_offset, int32_t weight_offset)
{
    const uint32_t required=DSA_PS_CAP_STORE|DSA_PS_CAP_FRAME_SCHEDULE|DSA_PS_CAP_LITERAL_BOUND;
    if ((limits->ps_caps>>24)!=DSA_PS_CAP_VERSION ||
        (limits->ps_caps&required)!=required ||
        (limits->ps_caps&DSA_PS_CAP_RAW_ONLY) || dsa_get_ps_force_raw()) return 0u;
    return dsa_ps_bound_s8((const void *)(uintptr_t)weights,channels,depth,stride,
                           packed,input_offset,weight_offset);
}

static int dsa_prepared_quantization(uint32_t channels, uint64_t bound,
                                     uint32_t bias_base, uint32_t mult_base,
                                     uint32_t shift_base, int per_channel,
                                     int32_t multiplier, int32_t shift)
{
    const int32_t *bias = (const int32_t *)(uintptr_t)bias_base;
    const int32_t *multipliers = (const int32_t *)(uintptr_t)mult_base;
    const int32_t *shifts = (const int32_t *)(uintptr_t)shift_base;
    uint32_t channel;
    for (channel = 0u; channel < channels; ++channel) {
        const int32_t m = per_channel ? multipliers[channel] : multiplier;
        const int32_t s = per_channel ? shifts[channel] : shift;
        if (m < 0 || s < -31 || s > 30 ||
            bound + (bias ? dsa_prepared_abs(bias[channel]) : 0u) > INT32_MAX)
            return 0;
    }
    return 1;
}

static void dsa_prepared_tiling(dsa_prepared_t *p, const gempact_tiling_t *t)
{
    dsa_prepared_register(p, NPU_REG_IA_REUSE, t->ia_reuse);
    dsa_prepared_register(p, NPU_REG_W_REUSE, t->w_reuse);
    dsa_prepared_register(p, NPU_REG_ROW_GROUPS, t->row_groups);
    dsa_prepared_register(p, NPU_REG_ROW_TAIL_TILES, t->row_tail_tiles);
    dsa_prepared_register(p, NPU_REG_COL_GROUPS, t->col_groups);
    dsa_prepared_register(p, NPU_REG_COL_TAIL_TILES, t->col_tail_tiles);
}

static void dsa_prepared_image(dsa_prepared_t *p, uint32_t ih, uint32_t iw,
    uint32_t ic, uint32_t gc, uint32_t go, uint32_t kh, uint32_t kw,
    uint32_t oh, uint32_t ow, uint32_t sh, uint32_t sw, uint32_t dh, uint32_t dw,
    uint32_t ph, uint32_t pw, int32_t offset)
{
    dsa_prepared_register(p, NPU_REG_CONV_INPUT_HW, dsa_conv_pair(ih, iw));
    dsa_prepared_register(p, NPU_REG_CONV_CHANNELS, dsa_conv_pair(ic, gc));
    dsa_prepared_register(p, NPU_REG_CONV_GROUP_OFFSET, go);
    dsa_prepared_register(p, NPU_REG_CONV_KERNEL_HW, dsa_conv_pair(kh, kw));
    dsa_prepared_register(p, NPU_REG_CONV_OUTPUT_HW, dsa_conv_pair(oh, ow));
    dsa_prepared_register(p, NPU_REG_CONV_STRIDE_HW, dsa_conv_pair(sh, sw));
    dsa_prepared_register(p, NPU_REG_CONV_DILATION_HW, dsa_conv_pair(dh, dw));
    dsa_prepared_register(p, NPU_REG_CONV_PADDING_HW, dsa_conv_pair(ph, pw));
    dsa_prepared_register(p, NPU_REG_CONV_INPUT_OFFSET, (uint32_t)offset);
}

uint32_t dsa_prepare_conv_s8(dsa_prepared_t *p, const dsa_conv_s8_config_t *c)
{
    dsa_conv_s8_config_t geometry;
    dsa_schedule_t schedule;
    dsa_matrix_limits_t limits;
    gempact_tiling_t tiling;
    uint32_t status, n, rows, caps, ps_literal_bytes;
    uint64_t input_bytes, output_bytes, filter_bytes;
    dsa_prepared_invalidate(p);
    if (!p || !c) return DSA_ERR_NULL_PTR;
    geometry = *c;
    geometry.input_base = geometry.output_base = 1u;
    status = dsa_conv_s8_validate(&geometry);
    if (status != DSA_SUCCESS) return status;
    n = c->kernel_h * c->kernel_w * c->group_c;
    rows = c->output_h * c->output_w;
#if DSA_NN_POINTWISE_DIRECT
    /* A contiguous pointwise convolution already has GEMM input layout.
     * The ordinary INT8 loader applies the input zero point during loading. */
    if (c->kernel_h == 1u && c->kernel_w == 1u &&
        c->stride_h == 1u && c->stride_w == 1u &&
        c->dilation_h == 1u && c->dilation_w == 1u &&
        c->pad_top == 0u && c->pad_left == 0u && c->group_offset == 0u &&
        c->group_c == c->input_c && c->output_h == c->input_h &&
        c->output_w == c->input_w && rows <= 65535u) {
        dsa_prepared_matmul_s8_config_t direct = {0};
        direct.filter_base = c->filter_base;
        direct.bias_base = c->bias_base;
        direct.multiplier_base = c->multiplier_base;
        direct.shift_base = c->shift_base;
        direct.rows = rows;
        direct.depth = direct.input_stride = direct.filter_stride = c->input_c;
        direct.channels = c->output_channels;
        direct.output_stride = c->dst_row_stride;
        direct.per_channel = 1u;
        direct.dataflow_mode = c->dataflow_mode;
        direct.rhs_tile_packed = c->rhs_tile_packed;
        direct.ia_reuse_num = c->ia_reuse_num;
        direct.w_reuse_num = c->w_reuse_num;
        direct.input_offset = c->input_offset;
        direct.output_offset = c->output_offset;
        direct.activation_min = c->activation_min;
        direct.activation_max = c->activation_max;
        return dsa_prepare_matmul_s8(p, &direct);
    }
#endif
    input_bytes = (uint64_t)c->input_h * c->input_w * c->input_c;
    output_bytes = (uint64_t)(rows - 1u) * c->dst_row_stride + c->output_channels;
    dsa_prepared_begin(p, (uint32_t)input_bytes, (uint32_t)output_bytes, 1u);
    filter_bytes=c->rhs_tile_packed ?
        dsa_matrix_packed_bytes(c->output_channels,n,1u):(uint64_t)n*c->output_channels;
    if (!dsa_prepared_readonly(p, c->filter_base, filter_bytes, c->rhs_tile_packed ? 4u:1u) ||
        !dsa_prepared_readonly(p, c->multiplier_base, c->output_channels * 4u, 4u) ||
        !dsa_prepared_readonly(p, c->shift_base, c->output_channels * 4u, 4u) ||
        (c->bias_base && !dsa_prepared_readonly(p, c->bias_base, c->output_channels * 4u, 4u)) ||
        !dsa_prepared_quantization(c->output_channels,
            dsa_prepared_operand_bound(c->input_offset) * 128u * n,
            c->bias_base, c->multiplier_base, c->shift_base, 1, 0, 0))
        return DSA_ERR_INVALID_DIM;
    caps = dsa_conv_capabilities();
    if ((caps & (DSA_CONV_CAP_S8 | DSA_CONV_CAP_NARROW_READ)) !=
        (DSA_CONV_CAP_S8 | DSA_CONV_CAP_NARROW_READ) ||
        (c->dataflow_mode==DSA_SCHEDULE_IS && !(caps & DSA_CONV_CAP_IS))) return DSA_ERR_UNSUPPORTED;
    dsa_matrix_query(&limits);
    ps_literal_bytes=dsa_prepared_ps_bound(&limits,c->filter_base,c->output_channels,n,n,
        c->rhs_tile_packed,c->input_offset,0);
    status=dsa_conv_plan_with_ps_bound(c,&limits,(caps&DSA_CONV_CAP_IS)!=0u,
        ps_literal_bytes,&schedule);
    if (status!=DSA_SUCCESS) return status;
    tiling=schedule.tiling;
    p->memory_policy_valid=schedule.memory_policy_valid;
    p->ps_control=schedule.ps_control;p->ia_bank_count=schedule.ia_bank_count;
    dsa_prepared_register(p, NPU_REG_RHS_BASE, c->filter_base);
    dsa_prepared_register(p, NPU_REG_BIAS_BASE, c->bias_base);
    dsa_prepared_register(p, NPU_REG_K, rows);
    dsa_prepared_register(p, NPU_REG_N, n);
    dsa_prepared_register(p, NPU_REG_M, c->output_channels);
    dsa_prepared_register(p, NPU_REG_LHS_STRIDE_B,
        ((n + DSA_TILE_SIZE - 1u) / DSA_TILE_SIZE) * DSA_TILE_SIZE * 2u);
    dsa_prepared_register(p, NPU_REG_RHS_STRIDE_B, n);
    dsa_prepared_register(p, NPU_REG_DST_STRIDE_B, c->dst_row_stride);
    dsa_prepared_register(p, NPU_REG_LHS_ZP, 0u);
    dsa_prepared_register(p, NPU_REG_RHS_ZP, 0u);
    dsa_prepared_register(p, NPU_REG_DST_ZP, (uint32_t)c->output_offset);
    dsa_prepared_register(p, NPU_REG_Q_MULT, c->multiplier_base);
    dsa_prepared_register(p, NPU_REG_Q_SHIFT, c->shift_base);
    dsa_prepared_register(p, NPU_REG_ACT_MIN, (uint32_t)c->activation_min);
    dsa_prepared_register(p, NPU_REG_ACT_MAX, (uint32_t)c->activation_max);
    dsa_prepared_tiling(p, &tiling);
    dsa_prepared_register(p, NPU_REG_DATAFLOW, schedule.dataflow_mode);
    dsa_prepared_image(p, c->input_h, c->input_w, c->input_c, c->group_c,
        c->group_offset, c->kernel_h, c->kernel_w, c->output_h, c->output_w,
        c->stride_h, c->stride_w, c->dilation_h, c->dilation_w,
        c->pad_top, c->pad_left, c->input_offset);
    p->ctrl = DSA_PREPARED_START | DSA_PREPARED_S16_INPUT | DSA_PREPARED_PER_CHANNEL |
              DSA_PREPARED_IRQ | NPU_CTRL_HW_CONV;
    if (schedule.dataflow_mode) p->ctrl |= DSA_PREPARED_IS;
    if (c->rhs_tile_packed) p->ctrl |= NPU_CTRL_RHS_TILE_PACKED;
    if (c->bypass_cache) p->ctrl |= NPU_CTRL_CONV_BYPASS;
    p->valid = DSA_PREPARED_VALID;
    return DSA_SUCCESS;
}

uint32_t dsa_prepare_spatial_s8(dsa_prepared_t *p, const dsa_vector_config_t *c)
{
    uint64_t input_bytes, output_bytes, taps;
    uint32_t caps, capacity;
    dsa_prepared_invalidate(p);
    if (!p || !c) return DSA_ERR_NULL_PTR;
    if (c->operation > DSA_VECTOR_OP_MINPOOL_S8 || c->vector_s16 ||
        c->bypass_cache > 1u || !dsa_vector_dim(c->input_h) ||
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
    if (!dsa_conv_span(1u, input_bytes) || !dsa_conv_span(1u, output_bytes) ||
        taps > (c->operation == DSA_VECTOR_OP_DW_S8 ? DSA_DW_MAX_TAPS : DSA_POOL_MAX_TAPS))
        return DSA_ERR_INVALID_DIM;
    dsa_prepared_begin(p, (uint32_t)input_bytes, (uint32_t)output_bytes, 1u);
    if (c->operation == DSA_VECTOR_OP_DW_S8) {
        if (c->input_offset < -127 || c->input_offset > 128 ||
            c->output_offset < -128 || c->output_offset > 127 ||
            !dsa_prepared_readonly(p, c->rhs_base, taps * c->input_c, 1u) ||
            !dsa_prepared_readonly(p, c->multiplier_base, c->input_c * 4u, 4u) ||
            !dsa_prepared_readonly(p, c->shift_base, c->input_c * 4u, 4u) ||
            (c->bias_base && !dsa_prepared_readonly(p, c->bias_base, c->input_c * 4u, 4u)) ||
            !dsa_prepared_quantization(c->input_c,
                dsa_prepared_operand_bound(c->input_offset) * 128u * taps,
                c->bias_base, c->multiplier_base, c->shift_base, 1, 0, 0))
            return DSA_ERR_INVALID_DIM;
    } else {
        const int64_t last_y = (int64_t)(c->output_h - 1u) * c->stride_h - c->pad_top;
        const int64_t last_x = (int64_t)(c->output_w - 1u) * c->stride_w - c->pad_left;
        if (c->input_offset || c->output_offset || c->dilation_h != 1u ||
            c->dilation_w != 1u || c->pad_top >= c->kernel_h ||
            c->pad_left >= c->kernel_w || last_y >= c->input_h || last_x >= c->input_w)
            return DSA_ERR_INVALID_DIM;
    }
    caps = dsa_vector_capabilities();
    capacity = (caps >> 16) & 0xffu;
    if (c->operation != DSA_VECTOR_OP_DW_S8 && (caps & DSA_VECTOR_CAP_LARGE_POOL))
        capacity = dsa_reg_read(NPU_REG_POOL_MAX_TAPS);
    if (!(caps & (c->operation == DSA_VECTOR_OP_DW_S8 ? DSA_VECTOR_CAP_DW_S8 : DSA_VECTOR_CAP_POOL_S8)) ||
        !((caps >> 8) & 0xffu) || taps > capacity) return DSA_ERR_UNSUPPORTED;
    dsa_prepared_register(p, NPU_REG_RHS_BASE, c->rhs_base);
    dsa_prepared_register(p, NPU_REG_BIAS_BASE, c->bias_base);
    dsa_prepared_register(p, NPU_REG_Q_MULT, c->multiplier_base);
    dsa_prepared_register(p, NPU_REG_Q_SHIFT, c->shift_base);
    dsa_prepared_register(p, NPU_REG_LHS_ZP, 0u);
    dsa_prepared_register(p, NPU_REG_RHS_ZP, 0u);
    dsa_prepared_register(p, NPU_REG_DST_ZP, (uint32_t)c->output_offset);
    dsa_prepared_register(p, NPU_REG_ACT_MIN, (uint32_t)c->activation_min);
    dsa_prepared_register(p, NPU_REG_ACT_MAX, (uint32_t)c->activation_max);
    dsa_prepared_register(p, NPU_REG_VECTOR_OP, c->operation);
    dsa_prepared_register(p, NPU_REG_VECTOR_LENGTH, c->length);
    dsa_prepared_image(p, c->input_h, c->input_w, c->input_c, c->input_c, 0u,
        c->kernel_h, c->kernel_w, c->output_h, c->output_w,
        c->stride_h, c->stride_w, c->dilation_h, c->dilation_w,
        c->pad_top, c->pad_left, c->input_offset);
    p->ctrl = DSA_PREPARED_START | DSA_PREPARED_IRQ | NPU_CTRL_VECTOR_ENGINE;
    if (c->operation == DSA_VECTOR_OP_DW_S8) p->ctrl |= DSA_PREPARED_PER_CHANNEL;
    if (c->bypass_cache) p->ctrl |= NPU_CTRL_CONV_BYPASS;
    p->valid = DSA_PREPARED_VALID;
    return DSA_SUCCESS;
}

uint32_t dsa_prepare_matmul_s8(dsa_prepared_t *p,
                             const dsa_prepared_matmul_s8_config_t *c)
{
    uint64_t input_bytes, output_bytes, weight_bytes;
    dsa_schedule_config_t planning;
    dsa_schedule_t schedule;
    dsa_matrix_limits_t limits;
    gempact_tiling_t tiling;
    dsa_prepared_invalidate(p);
    if (!p || !c) return DSA_ERR_NULL_PTR;
    if (!dsa_conv_dim(c->rows) || !dsa_conv_dim(c->depth) || !dsa_conv_dim(c->channels) ||
        c->input_stride < c->depth || c->filter_stride < c->depth ||
        c->output_stride < c->channels || c->per_channel > 1u || c->dataflow_mode > DSA_SCHEDULE_AUTO ||
        c->lhs_tile_packed > 1u || c->rhs_tile_packed > 1u ||
        c->input_offset < -127 || c->input_offset > 128 ||
        c->filter_offset < -127 || c->filter_offset > 128 ||
        c->output_offset < -128 || c->output_offset > 127 ||
        c->activation_min < -128 || c->activation_max > 127 ||
        c->activation_min > c->activation_max) return DSA_ERR_INVALID_DIM;
    input_bytes = c->lhs_tile_packed ? dsa_matrix_packed_bytes(c->rows,c->depth,1u):
        (uint64_t)(c->rows - 1u) * c->input_stride + c->depth;
    output_bytes = (uint64_t)(c->rows - 1u) * c->output_stride + c->channels;
    weight_bytes = c->rhs_tile_packed ? dsa_matrix_packed_bytes(c->channels,c->depth,1u):
        (uint64_t)(c->channels - 1u) * c->filter_stride + c->depth;
    if (!dsa_conv_span(1u, input_bytes) || !dsa_conv_span(1u, output_bytes))
        return DSA_ERR_INVALID_DIM;
    dsa_prepared_begin(p, (uint32_t)input_bytes, (uint32_t)output_bytes, 0u);
    if (!dsa_prepared_readonly(p, c->filter_base, weight_bytes, c->rhs_tile_packed ? 4u:1u) ||
        (c->bias_base && !dsa_prepared_readonly(p, c->bias_base, c->channels * 4u, 4u)) ||
        (c->per_channel &&
         (!dsa_prepared_readonly(p, c->multiplier_base, c->channels * 4u, 4u) ||
          !dsa_prepared_readonly(p, c->shift_base, c->channels * 4u, 4u))) ||
        !dsa_prepared_quantization(c->channels,
            dsa_prepared_operand_bound(c->input_offset) *
            dsa_prepared_operand_bound(c->filter_offset) * c->depth,
            c->bias_base, c->multiplier_base, c->shift_base, c->per_channel,
            c->multiplier, c->shift)) return DSA_ERR_INVALID_DIM;
    if (dsa_reg_read(NPU_REG_ID) != 0x4e505531u ||
        dsa_reg_read(NPU_REG_CONFIG_ABI) != 2u) return DSA_ERR_UNSUPPORTED;
    dsa_matrix_query(&limits);
    if ((c->lhs_tile_packed && !(limits.flags&DSA_MATRIX_CAP_LHS_TILE_PACKED)) ||
        (c->rhs_tile_packed && !(limits.flags&DSA_MATRIX_CAP_RHS_TILE_PACKED)) ||
        (c->dataflow_mode==DSA_SCHEDULE_IS && !(limits.flags&DSA_MATRIX_CAP_IS_SUPPORTED)))
        return DSA_ERR_UNSUPPORTED;
    dsa_schedule_init(&planning,c->rows,c->depth,c->channels,DSA_TILE_SIZE,
        limits.ia_cache_blocks,limits.ps_frame_count);
    dsa_schedule_set_limits(&planning,&limits);
    planning.flow=c->dataflow_mode;
    planning.requested_r=c->ia_reuse_num;planning.requested_w=c->w_reuse_num;
    planning.lhs_stride=c->input_stride;planning.rhs_stride=c->filter_stride;
    planning.output_stride=c->output_stride;planning.rhs_address=c->filter_base;
    planning.per_channel=c->per_channel;planning.has_bias=c->bias_base!=0u;
    planning.lhs_tile_packed=c->lhs_tile_packed;planning.rhs_tile_packed=c->rhs_tile_packed;
    planning.source_s8=1u;planning.lhs_offset=c->input_offset;planning.rhs_offset=c->filter_offset;
    planning.compact_mode_mask=3u;
    planning.ps_literal_bytes=dsa_prepared_ps_bound(&limits,c->filter_base,c->channels,c->depth,
        c->filter_stride,c->rhs_tile_packed,c->input_offset,c->filter_offset);
    if (!dsa_schedule_cached_plan(&planning,&schedule)) return DSA_ERR_INVALID_DIM;
    tiling=schedule.tiling;
    p->memory_policy_valid=schedule.memory_policy_valid;
    p->ps_control=schedule.ps_control;p->ia_bank_count=schedule.ia_bank_count;
    dsa_prepared_register(p, NPU_REG_RHS_BASE, c->filter_base);
    dsa_prepared_register(p, NPU_REG_BIAS_BASE, c->bias_base);
    dsa_prepared_register(p, NPU_REG_K, c->rows);
    dsa_prepared_register(p, NPU_REG_N, c->depth);
    dsa_prepared_register(p, NPU_REG_M, c->channels);
    dsa_prepared_register(p, NPU_REG_LHS_STRIDE_B, c->input_stride);
    dsa_prepared_register(p, NPU_REG_RHS_STRIDE_B, c->filter_stride);
    dsa_prepared_register(p, NPU_REG_DST_STRIDE_B, c->output_stride);
    dsa_prepared_register(p, NPU_REG_LHS_ZP, (uint32_t)c->input_offset);
    dsa_prepared_register(p, NPU_REG_RHS_ZP, (uint32_t)c->filter_offset);
    dsa_prepared_register(p, NPU_REG_DST_ZP, (uint32_t)c->output_offset);
    dsa_prepared_register(p, NPU_REG_Q_MULT, c->per_channel ? c->multiplier_base : (uint32_t)c->multiplier);
    dsa_prepared_register(p, NPU_REG_Q_SHIFT, c->per_channel ? c->shift_base : (uint32_t)c->shift);
    dsa_prepared_register(p, NPU_REG_ACT_MIN, (uint32_t)c->activation_min);
    dsa_prepared_register(p, NPU_REG_ACT_MAX, (uint32_t)c->activation_max);
    dsa_prepared_tiling(p, &tiling);
    p->ctrl = DSA_PREPARED_START | DSA_PREPARED_IRQ;
    if (c->per_channel) p->ctrl |= DSA_PREPARED_PER_CHANNEL;
    if (schedule.dataflow_mode) p->ctrl |= DSA_PREPARED_IS;
    if (c->lhs_tile_packed) p->ctrl |= NPU_CTRL_LHS_TILE_PACKED;
    if (c->rhs_tile_packed) p->ctrl |= NPU_CTRL_RHS_TILE_PACKED;
    p->valid = DSA_PREPARED_VALID;
    return DSA_SUCCESS;
}

/* Constructors emit one of three fixed register sequences. Constant MMIO
 * offsets let the CPU submit the validated values without decoding entries
 * or loading a loop counter from the descriptor after each volatile store. */
static void dsa_prepared_submit_registers(const dsa_prepared_t *p, uint32_t ctrl)
{
#if defined(__riscv) && !defined(DSA_MMIO_CUSTOM)
    uintptr_t register_base = DSA_MMIO_BASE;
    /* Keep one bank address in a register throughout the submission. */
    __asm__("" : "+r"(register_base));
#define DSA_PREPARED_WRITE(index, reg) \
    (*(volatile uint32_t *)(register_base + (reg)) = p->registers[index].value)
#else
#define DSA_PREPARED_WRITE(index, reg) dsa_reg_write(reg, p->registers[index].value)
#endif
    DSA_PREPARED_WRITE(0, NPU_REG_RHS_BASE);
    DSA_PREPARED_WRITE(1, NPU_REG_BIAS_BASE);
    if (ctrl & NPU_CTRL_VECTOR_ENGINE) {
        DSA_PREPARED_WRITE(2, NPU_REG_Q_MULT);
        DSA_PREPARED_WRITE(3, NPU_REG_Q_SHIFT);
        DSA_PREPARED_WRITE(4, NPU_REG_LHS_ZP);
        DSA_PREPARED_WRITE(5, NPU_REG_RHS_ZP);
        DSA_PREPARED_WRITE(6, NPU_REG_DST_ZP);
        DSA_PREPARED_WRITE(7, NPU_REG_ACT_MIN);
        DSA_PREPARED_WRITE(8, NPU_REG_ACT_MAX);
        DSA_PREPARED_WRITE(9, NPU_REG_VECTOR_OP);
        DSA_PREPARED_WRITE(10, NPU_REG_VECTOR_LENGTH);
        DSA_PREPARED_WRITE(11, NPU_REG_CONV_INPUT_HW);
        DSA_PREPARED_WRITE(12, NPU_REG_CONV_CHANNELS);
        DSA_PREPARED_WRITE(13, NPU_REG_CONV_GROUP_OFFSET);
        DSA_PREPARED_WRITE(14, NPU_REG_CONV_KERNEL_HW);
        DSA_PREPARED_WRITE(15, NPU_REG_CONV_OUTPUT_HW);
        DSA_PREPARED_WRITE(16, NPU_REG_CONV_STRIDE_HW);
        DSA_PREPARED_WRITE(17, NPU_REG_CONV_DILATION_HW);
        DSA_PREPARED_WRITE(18, NPU_REG_CONV_PADDING_HW);
        DSA_PREPARED_WRITE(19, NPU_REG_CONV_INPUT_OFFSET);
    } else {
        DSA_PREPARED_WRITE(2, NPU_REG_K);
        DSA_PREPARED_WRITE(3, NPU_REG_N);
        DSA_PREPARED_WRITE(4, NPU_REG_M);
        DSA_PREPARED_WRITE(5, NPU_REG_LHS_STRIDE_B);
        DSA_PREPARED_WRITE(6, NPU_REG_RHS_STRIDE_B);
        DSA_PREPARED_WRITE(7, NPU_REG_DST_STRIDE_B);
        DSA_PREPARED_WRITE(8, NPU_REG_LHS_ZP);
        DSA_PREPARED_WRITE(9, NPU_REG_RHS_ZP);
        DSA_PREPARED_WRITE(10, NPU_REG_DST_ZP);
        DSA_PREPARED_WRITE(11, NPU_REG_Q_MULT);
        DSA_PREPARED_WRITE(12, NPU_REG_Q_SHIFT);
        DSA_PREPARED_WRITE(13, NPU_REG_ACT_MIN);
        DSA_PREPARED_WRITE(14, NPU_REG_ACT_MAX);
        DSA_PREPARED_WRITE(15, NPU_REG_IA_REUSE);
        DSA_PREPARED_WRITE(16, NPU_REG_W_REUSE);
        DSA_PREPARED_WRITE(17, NPU_REG_ROW_GROUPS);
        DSA_PREPARED_WRITE(18, NPU_REG_ROW_TAIL_TILES);
        DSA_PREPARED_WRITE(19, NPU_REG_COL_GROUPS);
        DSA_PREPARED_WRITE(20, NPU_REG_COL_TAIL_TILES);
        if (ctrl & NPU_CTRL_HW_CONV) {
            DSA_PREPARED_WRITE(21, NPU_REG_DATAFLOW);
            DSA_PREPARED_WRITE(22, NPU_REG_CONV_INPUT_HW);
            DSA_PREPARED_WRITE(23, NPU_REG_CONV_CHANNELS);
            DSA_PREPARED_WRITE(24, NPU_REG_CONV_GROUP_OFFSET);
            DSA_PREPARED_WRITE(25, NPU_REG_CONV_KERNEL_HW);
            DSA_PREPARED_WRITE(26, NPU_REG_CONV_OUTPUT_HW);
            DSA_PREPARED_WRITE(27, NPU_REG_CONV_STRIDE_HW);
            DSA_PREPARED_WRITE(28, NPU_REG_CONV_DILATION_HW);
            DSA_PREPARED_WRITE(29, NPU_REG_CONV_PADDING_HW);
            DSA_PREPARED_WRITE(30, NPU_REG_CONV_INPUT_OFFSET);
        }
    }
#undef DSA_PREPARED_WRITE
}

uint32_t dsa_prepared_execute(const dsa_prepared_t *p, const void *input, void *output)
{
    const uintptr_t in = (uintptr_t)input, out = (uintptr_t)output;
    uint32_t i, end, status, result, ctrl, expected_registers, timeout = DSA_MATMUL_TIMEOUT;
    if (!p || !input || !output) return DSA_ERR_NULL_PTR;
    ctrl = p->ctrl;
    expected_registers = (ctrl & NPU_CTRL_VECTOR_ENGINE) ? 20u :
                         (ctrl & NPU_CTRL_HW_CONV) ? 31u : 21u;
    if (p->valid != DSA_PREPARED_VALID || p->register_count != expected_registers ||
        p->readonly_count > 4u) return DSA_ERR_INVALID_DIM;
    if (((ctrl & NPU_CTRL_LHS_TILE_PACKED) && (in&3u)) ||
        in > UINT32_MAX - p->input_bytes || out > UINT32_MAX - p->output_bytes ||
        (in < out + p->output_bytes && out < in + p->input_bytes)) return DSA_ERR_INVALID_DIM;
    end = (uint32_t)out + p->output_bytes;
    for (i = 0u; i < p->readonly_count; ++i)
        if (out < p->readonly[i].end && end > p->readonly[i].begin)
            return DSA_ERR_INVALID_DIM;
    if (dsa_reg_read(NPU_REG_STATUS) & (1u << 1)) return DSA_ERR_BUSY;
    if (p->memory_policy_valid && !(ctrl & NPU_CTRL_VECTOR_ENGINE)) {
        if (p->ia_bank_count) dsa_reg_write(NPU_REG_IA_BANKS,p->ia_bank_count);
        dsa_reg_write(NPU_REG_PS_CONTROL,p->ps_control);
    }
    dsa_prepared_submit_registers(p, ctrl);
    dsa_reg_write(NPU_REG_LHS_BASE, (uint32_t)in);
    dsa_reg_write(NPU_REG_DST_BASE, (uint32_t)out);
    if (p->spatial) dsa_reg_write(NPU_REG_CONV_INPUT_BASE, (uint32_t)in);
    dsa_reg_write(NPU_REG_STATUS, DSA_PREPARED_DONE);
    dsa_memory_barrier();
    dsa_reg_write(NPU_REG_CTRL, ctrl);
    do {
        status = dsa_reg_read(NPU_REG_STATUS);
        if (status & DSA_PREPARED_DONE) break;
    } while (--timeout != 0u);
    if (!timeout) return DSA_ERR_TIMEOUT;
    dsa_memory_barrier();
    result = (status & DSA_PREPARED_ERROR_MASK) ?
        (status & DSA_PREPARED_ERROR_MASK) >> 3 : dsa_reg_read(NPU_REG_WB_DATA);
    dsa_reg_write(NPU_REG_STATUS, DSA_PREPARED_DONE);
    dsa_memory_barrier();
    return result;
}

uint32_t dsa_prepare_add_s8(dsa_prepared_add_s8_t *p, uint32_t length,
                          const dsa_vector_add_params_t *quantization,
                          int32_t output_offset, int32_t activation_min,
                          int32_t activation_max)
{
    uint32_t caps;
    if (p) p->valid = 0u;
    if (!p || !quantization) return DSA_ERR_NULL_PTR;
    if (!length || length == UINT32_MAX ||
        !dsa_vector_add_quantization_valid(quantization, output_offset,
                                          activation_min, activation_max))
        return DSA_ERR_INVALID_DIM;
    caps = dsa_vector_capabilities();
    if (!(caps & DSA_VECTOR_CAP_ADD_S8) || !((caps >> 8) & 0xffu))
        return DSA_ERR_UNSUPPORTED;
    p->length = length;
    p->quantization = *quantization;
    p->output_offset = output_offset;
    p->activation_min = activation_min;
    p->activation_max = activation_max;
    p->valid = DSA_PREPARED_VALID;
    return DSA_SUCCESS;
}

uint32_t dsa_prepared_add_s8_execute(const dsa_prepared_add_s8_t *p,
                                   const int8_t *input1, const int8_t *input2,
                                   int8_t *output)
{
    const uintptr_t first = (uintptr_t)input1, second = (uintptr_t)input2;
    const uintptr_t out = (uintptr_t)output;
    uint32_t status, result, timeout = DSA_VECTOR_TIMEOUT;
    if (!p || !input1 || !input2 || !output) return DSA_ERR_NULL_PTR;
    if (p->valid != DSA_PREPARED_VALID || !p->length ||
        first > UINT32_MAX - p->length || second > UINT32_MAX - p->length ||
        out > UINT32_MAX - p->length ||
        (first < out + p->length && out < first + p->length) ||
        (second < out + p->length && out < second + p->length))
        return DSA_ERR_INVALID_DIM;
    if (dsa_reg_read(NPU_REG_STATUS) & (1u << 1)) return DSA_ERR_BUSY;
    dsa_reg_write(NPU_REG_LHS_BASE, (uint32_t)first);
    dsa_reg_write(NPU_REG_RHS_BASE, (uint32_t)second);
    dsa_reg_write(NPU_REG_DST_BASE, (uint32_t)out);
    dsa_reg_write(NPU_REG_BIAS_BASE, 0u);
    dsa_reg_write(NPU_REG_Q_MULT, (uint32_t)p->quantization.output_multiplier);
    dsa_reg_write(NPU_REG_Q_SHIFT, (uint32_t)p->quantization.output_shift);
    dsa_reg_write(NPU_REG_LHS_ZP, (uint32_t)p->quantization.input1_offset);
    dsa_reg_write(NPU_REG_RHS_ZP, (uint32_t)p->quantization.input2_offset);
    dsa_reg_write(NPU_REG_DST_ZP, (uint32_t)p->output_offset);
    dsa_reg_write(NPU_REG_ACT_MIN, (uint32_t)p->activation_min);
    dsa_reg_write(NPU_REG_ACT_MAX, (uint32_t)p->activation_max);
    dsa_reg_write(NPU_REG_VECTOR_OP, DSA_VECTOR_OP_ADD_S8);
    dsa_reg_write(NPU_REG_VECTOR_LENGTH, p->length);
    dsa_reg_write(NPU_REG_VECTOR_ADD_INPUT1_MULT,
                  (uint32_t)p->quantization.input1_multiplier);
    dsa_reg_write(NPU_REG_VECTOR_ADD_INPUT1_SHIFT,
                  (uint32_t)p->quantization.input1_shift);
    dsa_reg_write(NPU_REG_VECTOR_ADD_INPUT2_MULT,
                  (uint32_t)p->quantization.input2_multiplier);
    dsa_reg_write(NPU_REG_VECTOR_ADD_INPUT2_SHIFT,
                  (uint32_t)p->quantization.input2_shift);
    dsa_reg_write(NPU_REG_VECTOR_ADD_LEFT_SHIFT,
                  (uint32_t)p->quantization.left_shift);
    dsa_reg_write(NPU_REG_CONV_INPUT_BASE, (uint32_t)first);
    dsa_reg_write(NPU_REG_STATUS, DSA_PREPARED_DONE);
    dsa_memory_barrier();
    dsa_reg_write(NPU_REG_CTRL,
                  DSA_PREPARED_START | DSA_PREPARED_IRQ | NPU_CTRL_VECTOR_ENGINE);
    do {
        status = dsa_reg_read(NPU_REG_STATUS);
        if (status & DSA_PREPARED_DONE) break;
    } while (--timeout != 0u);
    if (!timeout) return DSA_ERR_TIMEOUT;
    dsa_memory_barrier();
    result = (status & DSA_PREPARED_ERROR_MASK) ?
        (status & DSA_PREPARED_ERROR_MASK) >> 3 : dsa_reg_read(NPU_REG_WB_DATA);
    dsa_reg_write(NPU_REG_STATUS, DSA_PREPARED_DONE);
    dsa_memory_barrier();
    return result;
}
#endif
