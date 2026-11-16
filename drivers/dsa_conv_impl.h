/* SPDX-License-Identifier: Apache-2.0
 * Included by the standalone and NMSIS dsa_accel.c implementations, which are
 * alternative build targets. Keeps their Conv ABI identical without changing
 * their existing GEMM C structure layouts.
 */
#ifndef DSA_CONV_IMPL_H
#define DSA_CONV_IMPL_H

static int dsa_conv_dim(uint32_t value)
{
    return value != 0u && value <= 65535u;
}

static int dsa_conv_span(uint32_t base, uint64_t bytes)
{
    return base != 0u && bytes != 0u && (uint64_t)base + bytes <= UINT32_MAX;
}

static uint32_t dsa_conv_pair(uint32_t first, uint32_t second)
{
    return first | (second << 16);
}

uint32_t dsa_conv_capabilities(void)
{
    uint32_t caps;
    if (dsa_reg_read(NPU_REG_ID) != 0x4e505531u ||
        dsa_reg_read(NPU_REG_CONFIG_ABI) != 2u) {
        return 0u;
    }
    caps = dsa_reg_read(NPU_REG_CONV_CAPS);
    return (caps >> 16) == DSA_CONV_CAP_VERSION ? caps : 0u;
}

uint32_t dsa_conv_s8_validate(const dsa_conv_s8_config_t *c)
{
    uint64_t n, rows, input_bytes, stride, filter_bytes;
    dsa_schedule_t schedule;
    dsa_matrix_limits_t limits;
    if (!c) return DSA_ERR_NULL_PTR;
    if (!dsa_conv_dim(c->input_h) || !dsa_conv_dim(c->input_w) ||
        !dsa_conv_dim(c->input_c) || !dsa_conv_dim(c->group_c) ||
        !dsa_conv_dim(c->kernel_h) || !dsa_conv_dim(c->kernel_w) ||
        !dsa_conv_dim(c->output_h) || !dsa_conv_dim(c->output_w) ||
        !dsa_conv_dim(c->stride_h) || !dsa_conv_dim(c->stride_w) ||
        !dsa_conv_dim(c->dilation_h) || !dsa_conv_dim(c->dilation_w) ||
        !dsa_conv_dim(c->output_channels) || c->group_offset > 65535u ||
        (uint64_t)c->group_offset + c->group_c > c->input_c ||
        c->pad_top > 65535u || c->pad_left > 65535u ||
        c->dst_row_stride < c->output_channels || c->bypass_cache > 1u ||
        c->dataflow_mode > DSA_SCHEDULE_AUTO || c->rhs_tile_packed > 1u ||
        c->input_offset < -127 || c->input_offset > 128 ||
        c->output_offset < -128 || c->output_offset > 127 ||
        c->activation_min < -128 || c->activation_max > 127 ||
        c->activation_min > c->activation_max) return DSA_ERR_INVALID_DIM;
    n = (uint64_t)c->kernel_h * c->kernel_w * c->group_c;
    rows = (uint64_t)c->output_h * c->output_w;
    input_bytes = (uint64_t)c->input_h * c->input_w * c->input_c;
    stride = ((n + DSA_TILE_SIZE - 1u) / DSA_TILE_SIZE) * DSA_TILE_SIZE * 2u;
    filter_bytes = c->rhs_tile_packed ?
        dsa_matrix_packed_bytes(c->output_channels,(uint32_t)n,1u):n*c->output_channels;
    /* Conservative NMSIS s8 contract; the scalar reference uses a u16 column
     * count, and the hardware uses s32 accumulation. Larger reductions fall
     * back instead of silently truncating either implementation's counters. */
    if (n > 65535u || rows > UINT32_MAX || stride > UINT32_MAX ||
        !dsa_conv_span(c->input_base, input_bytes) ||
        !dsa_conv_span(c->filter_base, filter_bytes) ||
        (c->rhs_tile_packed && (c->filter_base&3u)) ||
        !dsa_conv_span(c->output_base,
                       (rows - 1u) * c->dst_row_stride + c->output_channels) ||
        !dsa_conv_span(c->multiplier_base, (uint64_t)c->output_channels * 4u) ||
        !dsa_conv_span(c->shift_base, (uint64_t)c->output_channels * 4u) ||
        ((c->multiplier_base | c->shift_base | c->bias_base) & 3u) ||
        (c->bias_base && !dsa_conv_span(c->bias_base, (uint64_t)c->output_channels * 4u)))
        return DSA_ERR_INVALID_DIM;
    dsa_matrix_default_limits(&limits);
    limits.flags=DSA_MATRIX_CAP_RHS_TILE_PACKED | DSA_MATRIX_CAP_IS_SUPPORTED;
    if (dsa_conv_plan(c,&limits,1u,&schedule)!=DSA_SUCCESS)
        return DSA_ERR_INVALID_DIM;
    return DSA_SUCCESS;
}

uint32_t dsa_conv_s8_execute(const dsa_conv_s8_config_t *c)
{
    gempact_tiling_t tiling;
    dsa_schedule_t schedule;
    dsa_matrix_limits_t limits;
    uint32_t status, ctrl, result, n, rows, stride, caps;
    uint32_t timeout = DSA_MATMUL_TIMEOUT;
    status = dsa_conv_s8_validate(c);
    if (status != DSA_SUCCESS) return status;
    caps = dsa_conv_capabilities();
    if ((caps & (DSA_CONV_CAP_S8 | DSA_CONV_CAP_NARROW_READ)) !=
        (DSA_CONV_CAP_S8 | DSA_CONV_CAP_NARROW_READ)) return DSA_ERR_UNSUPPORTED;
    if (c->dataflow_mode==DSA_SCHEDULE_IS && !(caps & DSA_CONV_CAP_IS)) return DSA_ERR_UNSUPPORTED;
    if (dsa_reg_read(NPU_REG_STATUS) & (1u << 1)) return DSA_ERR_BUSY;
    n = c->kernel_h * c->kernel_w * c->group_c;
    rows = c->output_h * c->output_w;
    stride = ((n + DSA_TILE_SIZE - 1u) / DSA_TILE_SIZE) * DSA_TILE_SIZE * 2u;
    dsa_matrix_query(&limits);
    status=dsa_conv_plan(c,&limits,(caps&DSA_CONV_CAP_IS)!=0u,&schedule);
    if (status!=DSA_SUCCESS) return status;
    tiling=schedule.tiling;

    dsa_reg_write(NPU_REG_LHS_BASE, c->input_base);
    dsa_reg_write(NPU_REG_RHS_BASE, c->filter_base);
    dsa_reg_write(NPU_REG_DST_BASE, c->output_base);
    dsa_reg_write(NPU_REG_BIAS_BASE, c->bias_base);
    dsa_reg_write(NPU_REG_K, rows);
    dsa_reg_write(NPU_REG_N, n);
    dsa_reg_write(NPU_REG_M, c->output_channels);
    dsa_reg_write(NPU_REG_LHS_STRIDE_B, stride);
    dsa_reg_write(NPU_REG_RHS_STRIDE_B, n);
    dsa_reg_write(NPU_REG_DST_STRIDE_B, c->dst_row_stride);
    dsa_reg_write(NPU_REG_LHS_ZP, 0u); /* frontend already added input_offset */
    dsa_reg_write(NPU_REG_RHS_ZP, 0u);
    dsa_reg_write(NPU_REG_DST_ZP, (uint32_t)c->output_offset);
    dsa_reg_write(NPU_REG_Q_MULT, c->multiplier_base);
    dsa_reg_write(NPU_REG_Q_SHIFT, c->shift_base);
    dsa_reg_write(NPU_REG_ACT_MIN, (uint32_t)c->activation_min);
    dsa_reg_write(NPU_REG_ACT_MAX, (uint32_t)c->activation_max);
    dsa_reg_write(NPU_REG_IA_REUSE, tiling.ia_reuse);
    dsa_reg_write(NPU_REG_W_REUSE, tiling.w_reuse);
    dsa_reg_write(NPU_REG_ROW_GROUPS, tiling.row_groups);
    dsa_reg_write(NPU_REG_ROW_TAIL_TILES, tiling.row_tail_tiles);
    dsa_reg_write(NPU_REG_COL_GROUPS, tiling.col_groups);
    dsa_reg_write(NPU_REG_COL_TAIL_TILES, tiling.col_tail_tiles);
    dsa_reg_write(NPU_REG_DATAFLOW, schedule.dataflow_mode);
    dsa_reg_write(NPU_REG_CONV_INPUT_BASE, c->input_base);
    dsa_reg_write(NPU_REG_CONV_INPUT_HW, dsa_conv_pair(c->input_h, c->input_w));
    dsa_reg_write(NPU_REG_CONV_CHANNELS, dsa_conv_pair(c->input_c, c->group_c));
    dsa_reg_write(NPU_REG_CONV_GROUP_OFFSET, c->group_offset);
    dsa_reg_write(NPU_REG_CONV_KERNEL_HW, dsa_conv_pair(c->kernel_h, c->kernel_w));
    dsa_reg_write(NPU_REG_CONV_OUTPUT_HW, dsa_conv_pair(c->output_h, c->output_w));
    dsa_reg_write(NPU_REG_CONV_STRIDE_HW, dsa_conv_pair(c->stride_h, c->stride_w));
    dsa_reg_write(NPU_REG_CONV_DILATION_HW, dsa_conv_pair(c->dilation_h, c->dilation_w));
    dsa_reg_write(NPU_REG_CONV_PADDING_HW, dsa_conv_pair(c->pad_top, c->pad_left));
    dsa_reg_write(NPU_REG_CONV_INPUT_OFFSET, (uint32_t)c->input_offset);
    dsa_reg_write(NPU_REG_STATUS, 1u << 2);
    /* INT16 IA -> existing INT8 output pipeline, not the separate 16x8 mode. */
    ctrl = (1u << 0) | (1u << 1) | (1u << 2) | (1u << 4) | NPU_CTRL_HW_CONV;
    if (schedule.dataflow_mode) ctrl |= 1u << 3;
    if (c->rhs_tile_packed) ctrl |= NPU_CTRL_RHS_TILE_PACKED;
    if (c->bypass_cache) ctrl |= NPU_CTRL_CONV_BYPASS;
    dsa_memory_barrier();
    dsa_reg_write(NPU_REG_CTRL, ctrl);
    do {
        status = dsa_reg_read(NPU_REG_STATUS);
        if (status & (1u << 2)) break;
    } while (--timeout != 0u);
    /* A timeout does not cancel DMA. Leave status intact for diagnosis and do
     * not launch a software fallback; the caller must reset/quiesce the NPU. */
    if (timeout == 0u) return DSA_ERR_TIMEOUT;
    if (status & (3u << 3)) {
        result = (status >> 3) & 3u;
        dsa_reg_write(NPU_REG_STATUS, 1u << 2);
        return result;
    }
    dsa_memory_barrier();
    result = dsa_reg_read(NPU_REG_WB_DATA);
    dsa_reg_write(NPU_REG_STATUS, 1u << 2);
    dsa_memory_barrier();
    return result;
}
#endif
