/* SPDX-License-Identifier: Apache-2.0 */
#include <stdint.h>
#include <stdlib.h>
#include "dsa_accel.c"
#include "dsa_ps_bound.h"

void dsa_mmio_write(uint32_t address, uint32_t value)
{
    (void)address;
    (void)value;
    abort();
}

uint32_t dsa_mmio_read(uint32_t address)
{
    switch (address - DSA_MMIO_BASE) {
    case NPU_REG_ID: return 0x4e505531u;
    case NPU_REG_CONFIG_ABI: return 2u;
    case NPU_REG_MATRIX_CAPS: return (DENSE_SWEEP_SIZE << 24) |
        (DENSE_SWEEP_PS_FRAME_COUNT << 16) | (DENSE_SWEEP_IA_CACHE_BLOCKS << 8) | 7u;
    case NPU_REG_MATRIX_PS_ROWS: return DENSE_SWEEP_MATRIX_PS_ROWS;
    case NPU_REG_MATRIX_OUTPUT_BANKS: return DENSE_SWEEP_MATRIX_OUTPUT_BANKS;
    case NPU_REG_DMA_MAX_BYTES: return DENSE_SWEEP_DMA_MAX_BYTES;
    case NPU_REG_AXI_DATA_BITS: return DENSE_SWEEP_BUS_WIDTH;
    case NPU_REG_CONV_CAPS: return (DSA_CONV_CAP_VERSION << 16) | 7u;
    case NPU_REG_PS_CAPS: return DENSE_SWEEP_PS_CAPS;
    case NPU_REG_PS_POOL_BYTES: return DENSE_SWEEP_PS_POOL_BYTES;
    case NPU_REG_IA_CACHE_BYTES: return DENSE_SWEEP_IA_CACHE_BYTES;
    case NPU_REG_IM2COL_CACHE_BYTES: return DENSE_SWEEP_IM2COL_CACHE_BYTES;
    case NPU_REG_SHARED_TOTAL_BYTES: return DENSE_SWEEP_SHARED_TOTAL_BYTES;
    case NPU_REG_SHARED_BANK_BYTES: return DENSE_SWEEP_SHARED_BANK_BYTES;
    case NPU_REG_IA_BANK_MASK: return DENSE_SWEEP_SHARED_IA_BANK_MASK;
    case NPU_REG_PS_DIRECTORY_ROWS: return DENSE_SWEEP_PS_DIRECTORY_ROWS;
    default: return 0u;
    }
}

/* 按生产测试台的 64 个配置字生成调度参数，输出字段顺序由 Python 调用端定义。 */
int operator_schedule(const uint32_t *cfg, const void *weights,
                      uint32_t weight_bytes, uint64_t *output)
{
    dsa_matrix_limits_t limits;
    dsa_schedule_config_t c;
    dsa_schedule_t p;
    uint32_t i = 0u;
    uint64_t expected = cfg[29] & 2u ?
        (uint64_t)((cfg[5]+15u)/16u)*((cfg[4]+15u)/16u)*256u :
        (uint64_t)cfg[5]*cfg[4];
    if (!weights || expected != weight_bytes) return 0;
    dsa_matrix_query(&limits);
    dsa_schedule_init(&c, cfg[3], cfg[4], cfg[5], 16u,
                      limits.ia_cache_blocks, limits.ps_frame_count);
    dsa_schedule_set_limits(&c, &limits);
    c.flow = DSA_SCHEDULE_AUTO;
    c.lhs_bytes = cfg[12] ? 2u : 1u;
    c.lhs_stride = cfg[18];
    c.rhs_stride = cfg[19];
    c.output_stride = cfg[20];
    c.lhs_address = cfg[14];
    c.rhs_address = cfg[15];
    c.output_address = cfg[17];
    c.lhs_tile_packed = cfg[29] & 1u;
    c.rhs_tile_packed = (cfg[29] >> 1) & 1u;
    c.has_bias = cfg[16] != 0u;
    c.per_channel = cfg[13];
    c.spatial = cfg[32];
    c.source_s8 = 1u;
    c.compact_mode_mask = 3u;
    c.ps_literal_bytes = dsa_ps_bound_s8(weights, c.cols, c.depth,
        c.rhs_stride, c.rhs_tile_packed, 0, 0);
    if (c.spatial) {
        c.im2col.input_bytes = cfg[34]*cfg[35]*cfg[36];
        c.im2col.input_channels = cfg[36];
        c.im2col.group_channels = cfg[37];
        c.im2col.kernel_h = cfg[39];
        c.im2col.kernel_w = cfg[40];
        c.im2col.stride_w = cfg[44];
        c.im2col.source_bytes = 1u;
        c.im2col.cache_bytes = limits.im2col_cache_bytes;
        c.im2col_input_width = cfg[35];
        c.im2col_output_width = cfg[42];
        c.im2col_stride_h = cfg[43];
    }
    if (!dsa_schedule_cached_plan(&c, &p)) return 0;
#define WRITE(field) output[i++] = p.field
    WRITE(tiling.ia_reuse); WRITE(tiling.w_reuse);
    WRITE(tiling.row_groups); WRITE(tiling.row_tail_tiles);
    WRITE(tiling.col_groups); WRITE(tiling.col_tail_tiles);
    WRITE(dataflow_mode); WRITE(candidates); WRITE(estimated_cycles);
    WRITE(read_words); WRITE(read_requests); WRITE(write_words);
    WRITE(write_requests); WRITE(compute_cycles); WRITE(ps_payload_bytes);
    WRITE(ps_control); WRITE(ia_bank_count); WRITE(ia_cache_bytes);
    WRITE(ps_pool_bytes); WRITE(frame_rows); WRITE(predicted_resident_frames);
    WRITE(read_beats); WRITE(write_beats); WRITE(memory_policy_valid);
#undef WRITE
    output[i++] = c.ps_literal_bytes;
    return i == 25u;
}
