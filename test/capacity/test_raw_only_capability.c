#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "dsa_accel.h"

typedef struct {
    uint32_t ps_control, mode, r, w;
    uint32_t row_groups, row_tail, col_groups, col_tail;
    uint32_t ctrl;
} submitted_plan_t;

static uint32_t registers[128], starts, active;
static uint32_t hardware_caps, hardware_pool, hardware_ia;

uint32_t dsa_mmio_read(uint32_t address)
{
    switch (address - DSA_MMIO_BASE) {
    case NPU_REG_STATUS: return active ? 5u : 1u;
    case NPU_REG_ID: return 0x4e505531u;
    case NPU_REG_CONFIG_ABI: return 2u;
    case NPU_REG_MATRIX_CAPS: return (16u<<24)|(hardware_caps&0x00ff0000u)|((hardware_ia/512u)<<8)|7u;
    case NPU_REG_MATRIX_PS_ROWS: return 0u;
    case NPU_REG_MATRIX_OUTPUT_BANKS: return 8u|(8u<<16);
    case NPU_REG_PS_CAPS: return hardware_caps;
    case NPU_REG_PS_POOL_BYTES: return hardware_pool;
    case NPU_REG_IA_CACHE_BYTES: return hardware_ia;
    case NPU_REG_CONV_CAPS: return (DSA_CONV_CAP_VERSION << 16) | 7u;
    case NPU_REG_WB_DATA: return 0u;
    default: return registers[(address - DSA_MMIO_BASE) / 4u];
    }
}

void dsa_mmio_write(uint32_t address, uint32_t value)
{
    uint32_t offset = address - DSA_MMIO_BASE;
    registers[offset / 4u] = value;
    if (offset == NPU_REG_STATUS && (value & 4u)) active = 0u;
    if (offset == NPU_REG_CTRL && (value & 1u)) {
        assert(starts == 0u && active == 0u);
        ++starts;
        active = 1u;
    }
}

static submitted_plan_t execute(uint32_t operation, uint32_t mode,
                                uint32_t rows, uint32_t reduction, uint32_t cols,
                                uint32_t raw_only, uint32_t runtime_raw)
{
    uint32_t status;
    submitted_plan_t plan = {0};
    hardware_caps = (hardware_caps & ~DSA_PS_CAP_RAW_ONLY) |
                    (raw_only ? DSA_PS_CAP_RAW_ONLY : 0u);
    dsa_set_ps_force_raw(runtime_raw);
    memset(registers, 0, sizeof(registers));
    starts = active = 0u;
    if (operation == 2u) {
        dsa_conv_s8_config_t c = {0};
        c.input_base = 0x01000000; c.filter_base = 0x02000000;
        c.output_base = 0x04000000; c.bias_base = 0x03000000;
        c.multiplier_base = 0x03100000; c.shift_base = 0x03200000;
        c.input_h = c.output_h = rows; c.input_w = c.output_w = 1u;
        c.input_c = c.group_c = reduction; c.output_channels = cols;
        c.kernel_h = c.kernel_w = c.stride_h = c.stride_w = 1u;
        c.dilation_h = c.dilation_w = 1u; c.dst_row_stride = cols;
        c.input_offset = 128; c.activation_min = -128; c.activation_max = 127;
        c.dataflow_mode = mode;
        status = dsa_conv_s8_execute(&c);
    } else {
        dsa_matmul_config_t c;
        dsa_matmul_config_init(&c);
#ifdef POINTER_API
        c.lhs_ptr = (void *)(uintptr_t)0x01000000;
        c.rhs_ptr = (void *)(uintptr_t)0x02000000;
        c.dst_ptr = (void *)(uintptr_t)0x04000000;
        c.bias_ptr = (void *)(uintptr_t)0x03000000;
        c.dst_mult_ptr = (void *)(uintptr_t)0x03100000;
        c.dst_shift_ptr = (void *)(uintptr_t)0x03200000;
#else
        c.lhs_ptr = 0x01000000; c.rhs_ptr = 0x02000000;
        c.dst_ptr = 0x04000000; c.bias_ptr = 0x03000000;
        c.dst_mult_ptr = 0x03100000; c.dst_shift_ptr = 0x03200000;
#endif
        c.K = rows; c.N = reduction; c.M = cols;
        c.lhs_dtype = operation == 1u ? DSA_DTYPE_S16 : DSA_DTYPE_S8;
        c.out_dtype = DSA_DTYPE_S8;
        c.lhs_row_stride = reduction * (operation == 1u ? 2u : 1u);
        c.rhs_row_stride = reduction; c.dst_row_stride = cols;
        c.quant_mode = DSA_QUANT_PER_CHANNEL;
        c.dataflow_mode = (dsa_dataflow_mode_t)mode;
        c.lhs_offset = operation == 1u ? 0 : 128;
        status = dsa_matmul_execute(&c);
    }
    assert(status == DSA_SUCCESS && starts == 1u && active == 0u);
    plan.ps_control = registers[NPU_REG_PS_CONTROL / 4u];
    plan.mode = (registers[NPU_REG_CTRL / 4u] >> 3) & 1u;
    plan.r = registers[NPU_REG_IA_REUSE / 4u];
    plan.w = registers[NPU_REG_W_REUSE / 4u];
    plan.row_groups = registers[NPU_REG_ROW_GROUPS / 4u];
    plan.row_tail = registers[NPU_REG_ROW_TAIL_TILES / 4u];
    plan.col_groups = registers[NPU_REG_COL_GROUPS / 4u];
    plan.col_tail = registers[NPU_REG_COL_TAIL_TILES / 4u];
    plan.ctrl = registers[NPU_REG_CTRL / 4u];
    assert(mode == DSA_DATAFLOW_AUTO || plan.mode == mode);
    if (raw_only || runtime_raw || DSA_PS_FORCE_RAW) {
        uint32_t stream_rows = plan.mode ? cols : rows;
        uint32_t column_tiles = ((plan.mode ? rows : cols) + 15u) / 16u;
        uint32_t frame_rows = stream_rows < plan.r * 16u ? stream_rows : plan.r * 16u;
        uint32_t live = column_tiles < plan.w ? column_tiles : plan.w;
        assert(plan.ps_control & DSA_PS_CTRL_RAW);
        if (plan.ps_control&DSA_PS_CTRL_FRAME) {
            uint32_t slice=(plan.ps_control>>2)&3u;
            if (slice==1u && frame_rows>16u) frame_rows=16u;
            if (slice==2u && frame_rows>32u) frame_rows=32u;
            assert(reduction<=16u || (uint64_t)frame_rows*64u<=hardware_pool);
        } else assert(reduction<=16u || (uint64_t)frame_rows*live*64u<=hardware_pool);
    }
    return plan;
}

static void same_plan(submitted_plan_t left, submitted_plan_t right)
{
    assert(memcmp(&left, &right, sizeof(left)) == 0);
}

int main(void)
{
    const uint32_t pools[] = {4096u, 8192u, 12288u};
    const uint32_t shapes[][3] = {
        {125u, 64u, 64u}, {196u, 256u, 16u},
        {1u, 800u, 32u}, {65u, 9u, 127u}
    };
    uint32_t configurations = 0, submissions = 0, comparisons = 0, adaptive_plans = 0;
    assert(DSA_PS_FORCE_RAW == 0 && DSA_PS_ADAPTIVE_W != 0);
    hardware_ia = 2048u;
    for (uint32_t pool = 0; pool < 3u; ++pool)
    for (uint32_t frames = 8u; frames <= 16u; frames += 8u)
    for (uint32_t compact = 0; compact < 2u; ++compact)
    for (uint32_t operation = 0; operation < 3u; ++operation)
    for (uint32_t mode = 0; mode < 3u; ++mode)
    for (uint32_t shape = 0; shape < 4u; ++shape) {
        uint32_t rows = shapes[shape][0], reduction = shapes[shape][1], cols = shapes[shape][2];
        submitted_plan_t adaptive, raw, observed;
        hardware_pool = pools[pool];
        hardware_caps = (DSA_PS_CAP_VERSION << 24) | (frames << 16) |
                        DSA_PS_CAP_STORE | DSA_PS_CAP_FRAME_SCHEDULE |
                        (compact ? DSA_PS_CAP_IA_COMPACT : 0u);
        adaptive = execute(operation, mode, rows, reduction, cols, 0u, 0u);
        raw = execute(operation, mode, rows, reduction, cols, 0u, 1u);
        observed = execute(operation, mode, rows, reduction, cols, 1u, 0u);
        same_plan(observed, raw);
        observed = execute(operation, mode, rows, reduction, cols, 1u, 7u);
        same_plan(observed, raw);
        observed = execute(operation, mode, rows, reduction, cols, 1u, 0u);
        same_plan(observed, raw);
        observed = execute(operation, mode, rows, reduction, cols, 0u, 0u);
        same_plan(observed, adaptive);
        observed = execute(operation, mode, rows, reduction, cols, 0u, 1u);
        same_plan(observed, raw);
        adaptive_plans += (adaptive.ps_control & DSA_PS_CTRL_RAW) == 0u;
        ++configurations;
        submissions += 7u;
        comparisons += 5u;
    }
    assert(adaptive_plans > 0u);
    printf("{\"passed\":true,\"configurations\":%u,\"submissions\":%u,"
           "\"plan_comparisons\":%u,\"adaptive_plans\":%u,\"operations\":3,\"dataflows\":3}\n",
           configurations, submissions, comparisons, adaptive_plans);
    return 0;
}
