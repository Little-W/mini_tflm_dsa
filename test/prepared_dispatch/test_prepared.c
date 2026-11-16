/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include "dsa_accel.h"
#include "dsa_prepared.h"

static uint32_t registers[64], saved[64];
static uint32_t starts, writes, reads, active, busy, error_mode, matrix_reads;
static uint32_t conv_caps = 0x00010007u, vector_caps = 0x0131083fu;
static uint8_t *constants;
static uint32_t weights, bias, multiplier, shift;
static unsigned checks;
#define CHECK(expression) do { ++checks; assert(expression); } while (0)

void dsa_mmio_write(uint32_t address, uint32_t value)
{
    const uint32_t offset = address - DSA_MMIO_BASE;
    CHECK(address >= DSA_MMIO_BASE && offset < sizeof(registers) && !(offset & 3u));
    ++writes;
    if (offset == NPU_REG_STATUS) { active = 0u; return; }
    registers[offset / 4u] = value;
    if (offset == NPU_REG_CTRL && (value & 1u)) { ++starts; active = 1u; }
}

uint32_t dsa_mmio_read(uint32_t address)
{
    const uint32_t offset = address - DSA_MMIO_BASE;
    ++reads;
    if (offset == NPU_REG_MATRIX_CAPS || offset == NPU_REG_MATRIX_PS_ROWS ||
        offset == NPU_REG_MATRIX_OUTPUT_BANKS) ++matrix_reads;
    if (offset == NPU_REG_ID) return 0x4e505531u;
    if (offset == NPU_REG_CONFIG_ABI) return 2u;
    if (offset == NPU_REG_CONV_CAPS) return conv_caps;
    if (offset == NPU_REG_VECTOR_CAPS) return vector_caps;
    if (offset == NPU_REG_POOL_MAX_TAPS) return 256u;
    if (offset == NPU_REG_STATUS) {
        if (busy || (active && error_mode == 2u)) return 2u;
        return active ? 4u | (error_mode == 1u ? 3u << 3 : 0u) : 1u;
    }
    if (offset == NPU_REG_WB_DATA) return error_mode == 3u ? 7u : 0u;
    return registers[offset / 4u];
}

static void reset_device(void)
{
    memset(registers, 0, sizeof(registers));
    starts = writes = reads = active = busy = error_mode = matrix_reads = 0u;
}

static dsa_conv_s8_config_t conv_config(void)
{
    dsa_conv_s8_config_t c = {0};
    c.input_base = 0x20000003u; c.output_base = 0x21000005u;
    c.filter_base = weights; c.bias_base = bias;
    c.multiplier_base = multiplier; c.shift_base = shift;
    c.input_h = 9u; c.input_w = 11u; c.input_c = c.group_c = 8u;
    c.kernel_h = c.kernel_w = 3u; c.output_h = 9u; c.output_w = 11u;
    c.stride_h = c.stride_w = c.dilation_h = c.dilation_w = 1u;
    c.pad_top = c.pad_left = 1u;
    c.output_channels = c.dst_row_stride = 32u;
    c.input_offset = 17; c.output_offset = -9;
    c.activation_min = -120; c.activation_max = 115;
    return c;
}

static dsa_vector_config_t spatial_config(uint32_t operation)
{
    dsa_vector_config_t c = {0};
    c.operation = operation;
    c.input_base = 0x20000003u; c.output_base = 0x21000005u;
    c.input_h = 9u; c.input_w = 11u; c.input_c = 32u;
    c.kernel_h = c.kernel_w = 3u; c.output_h = 9u; c.output_w = 11u;
    c.stride_h = c.stride_w = c.dilation_h = c.dilation_w = 1u;
    c.pad_top = c.pad_left = 1u;
    c.activation_min = -120; c.activation_max = 115;
    if (operation == DSA_VECTOR_OP_DW_S8) {
        c.rhs_base = weights; c.bias_base = bias;
        c.multiplier_base = multiplier; c.shift_base = shift;
        c.input_offset = 17; c.output_offset = -9;
    }
    return c;
}

static void verify_bindings(const dsa_prepared_t *p)
{
    const uint32_t old_starts = starts;
    CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0x22000007u,
                              (void *)(uintptr_t)0x23000009u) == DSA_SUCCESS);
    CHECK(starts == old_starts + 1u);
    CHECK(registers[NPU_REG_LHS_BASE / 4u] == 0x22000007u);
    CHECK(registers[NPU_REG_DST_BASE / 4u] == 0x23000009u);
    if (p->spatial) CHECK(registers[NPU_REG_CONV_INPUT_BASE / 4u] == 0x22000007u);
    CHECK(dsa_prepared_execute(p, NULL, (void *)(uintptr_t)0x23000009u) == DSA_ERR_NULL_PTR);
    CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0xfffffff0u,
                              (void *)(uintptr_t)0x23000009u) == DSA_ERR_INVALID_DIM);
    CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0x22000007u,
                              (void *)(uintptr_t)0xfffffff0u) == DSA_ERR_INVALID_DIM);
    CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0x22000007u,
                              (void *)(uintptr_t)0x22000008u) == DSA_ERR_INVALID_DIM);
    if (p->readonly_count) {
        CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0x22000007u,
                                  (void *)(uintptr_t)weights) == DSA_ERR_INVALID_DIM);
        CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0x22000007u,
                                  (void *)(uintptr_t)(weights - p->output_bytes + 1u)) == DSA_ERR_INVALID_DIM);
    }
    CHECK(starts == old_starts + 1u);
    busy = 1u;
    CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0x22000007u,
                              (void *)(uintptr_t)0x23000009u) == DSA_ERR_BUSY);
    CHECK(starts == old_starts + 1u);
    busy = 0u;
    for (error_mode = 1u; error_mode <= 3u; ++error_mode) {
        const uint32_t wanted = error_mode == 1u ? 3u : error_mode == 2u ? DSA_ERR_TIMEOUT : 7u;
        CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0x22000007u,
                                  (void *)(uintptr_t)0x23000009u) == wanted);
        active = 0u;
    }
    error_mode = 0u;
    CHECK(starts == old_starts + 4u);
    CHECK(mprotect(constants, 65536u, PROT_NONE) == 0);
    CHECK(dsa_prepared_execute(p, (const void *)(uintptr_t)0x22000007u,
                              (void *)(uintptr_t)0x23000009u) == DSA_SUCCESS);
    CHECK(mprotect(constants, 65536u, PROT_READ | PROT_WRITE) == 0);
}

static void test_conv(void)
{
    dsa_prepared_t prepared;
    dsa_conv_s8_config_t c = conv_config();
    for (unsigned flow = 0u; flow < 2u; ++flow) {
        c.dataflow_mode = flow;
        reset_device();
        CHECK(dsa_conv_s8_execute(&c) == DSA_SUCCESS);
        memcpy(saved, registers, sizeof(saved));
        reset_device();
        c.input_base = c.output_base = 0u;
        CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_SUCCESS);
        CHECK(writes == 0u && starts == 0u && prepared.valid == DSA_PREPARED_VALID);
        CHECK(dsa_prepared_execute(&prepared, (const void *)(uintptr_t)0x20000003u,
                                  (void *)(uintptr_t)0x21000005u) == DSA_SUCCESS);
        CHECK(memcmp(saved, registers, sizeof(saved)) == 0);
        verify_bindings(&prepared);
        c.input_base = 0x20000003u; c.output_base = 0x21000005u;
    }
    ((int32_t *)(uintptr_t)shift)[31] = 31;
    CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_ERR_INVALID_DIM);
    CHECK(prepared.valid == 0u);
    CHECK(dsa_prepared_execute(&prepared, (const void *)(uintptr_t)c.input_base,
                              (void *)(uintptr_t)c.output_base) == DSA_ERR_INVALID_DIM);
    ((int32_t *)(uintptr_t)shift)[31] = -8;
    ((int32_t *)(uintptr_t)bias)[31] = INT32_MAX;
    CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_ERR_INVALID_DIM);
    ((int32_t *)(uintptr_t)bias)[31] = 0;
    ((int32_t *)(uintptr_t)multiplier)[0] = -1;
    CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_ERR_INVALID_DIM);
    ((int32_t *)(uintptr_t)multiplier)[0] = 1 << 30;
    c.input_h = 0u;
    CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_ERR_INVALID_DIM);
    c = conv_config(); c.multiplier_base += 1u;
    CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_ERR_INVALID_DIM);
}

static void test_spatial(void)
{
    dsa_prepared_t prepared;
    for (uint32_t operation = DSA_VECTOR_OP_DW_S8;
         operation <= DSA_VECTOR_OP_MINPOOL_S8; ++operation) {
        dsa_vector_config_t c = spatial_config(operation);
        reset_device();
        CHECK(dsa_vector_execute(&c) == DSA_SUCCESS);
        memcpy(saved, registers, sizeof(saved));
        reset_device();
        c.input_base = c.output_base = 0u;
        CHECK(dsa_prepare_spatial_s8(&prepared, &c) == DSA_SUCCESS);
        CHECK(writes == 0u && starts == 0u);
        CHECK(dsa_prepared_execute(&prepared, (const void *)(uintptr_t)0x20000003u,
                                  (void *)(uintptr_t)0x21000005u) == DSA_SUCCESS);
        CHECK(memcmp(saved, registers, sizeof(saved)) == 0);
        verify_bindings(&prepared);
    }
    dsa_vector_config_t pool = spatial_config(DSA_VECTOR_OP_AVGPOOL_S8);
    pool.input_h = pool.kernel_h = 25u;
    pool.input_w = pool.kernel_w = 5u;
    pool.output_h = pool.output_w = 1u;
    pool.pad_top = pool.pad_left = 0u;
    CHECK(dsa_prepare_spatial_s8(&prepared, &pool) == DSA_SUCCESS);
    vector_caps &= ~DSA_VECTOR_CAP_LARGE_POOL;
    CHECK(dsa_prepare_spatial_s8(&prepared, &pool) == DSA_ERR_UNSUPPORTED);
    CHECK(prepared.valid == 0u);
    vector_caps |= DSA_VECTOR_CAP_LARGE_POOL;
    pool.input_h = pool.input_w = pool.kernel_h = pool.kernel_w = 8u;
    CHECK(dsa_prepare_spatial_s8(&prepared, &pool) == DSA_SUCCESS);
    pool.pad_top = 8u;
    CHECK(dsa_prepare_spatial_s8(&prepared, &pool) == DSA_ERR_INVALID_DIM);
    pool = spatial_config(DSA_VECTOR_OP_DW_S8);
    pool.input_h = pool.input_w = pool.input_c = 65535u;
    CHECK(dsa_prepare_spatial_s8(&prepared, &pool) == DSA_ERR_INVALID_DIM);
    pool = spatial_config(DSA_VECTOR_OP_DW_S8);
    ((int32_t *)(uintptr_t)shift)[2] = -32;
    CHECK(dsa_prepare_spatial_s8(&prepared, &pool) == DSA_ERR_INVALID_DIM);
    ((int32_t *)(uintptr_t)shift)[2] = -8;
}

static void test_matmul(void)
{
    dsa_prepared_t prepared;
    for (uint32_t channel_quant = 0u; channel_quant < 2u; ++channel_quant) {
        dsa_matmul_config_t normal;
        dsa_prepared_matmul_s8_config_t c = {0};
        dsa_matmul_config_init(&normal);
#ifdef TEST_NMSIS
        normal.lhs_ptr = (const void *)(uintptr_t)0x20000003u;
        normal.rhs_ptr = (const void *)(uintptr_t)weights;
        normal.dst_ptr = (void *)(uintptr_t)0x21000005u;
        normal.bias_ptr = (const void *)(uintptr_t)bias;
        normal.dst_mult_ptr = (const int32_t *)(uintptr_t)multiplier;
        normal.dst_shift_ptr = (const int32_t *)(uintptr_t)shift;
#else
        normal.lhs_ptr = 0x20000003u; normal.rhs_ptr = weights;
        normal.dst_ptr = 0x21000005u; normal.bias_ptr = bias;
        normal.dst_mult_ptr = multiplier; normal.dst_shift_ptr = shift;
#endif
        normal.K = c.rows = 3u; normal.N = c.depth = 17u; normal.M = c.channels = 32u;
        normal.lhs_row_stride = c.input_stride = 19u;
        normal.rhs_row_stride = c.filter_stride = 21u;
        normal.dst_row_stride = c.output_stride = 35u;
        normal.quant_mode = channel_quant ? DSA_QUANT_PER_CHANNEL : DSA_QUANT_PER_TENSOR;
        c.per_channel = channel_quant;
        normal.dataflow_mode = DSA_DATAFLOW_WS;
        c.dataflow_mode = DSA_SCHEDULE_WS;
        normal.lhs_offset = c.input_offset = 17; normal.rhs_offset = c.filter_offset = -2;
        normal.dst_offset = c.output_offset = -9;
        normal.act_min = c.activation_min = -120; normal.act_max = c.activation_max = 115;
        normal.dst_mult = c.multiplier = 1 << 30; normal.dst_shift = c.shift = -8;
        c.filter_base = weights; c.bias_base = bias;
        c.multiplier_base = multiplier; c.shift_base = shift;
        reset_device();
        CHECK(dsa_matmul_execute(&normal) == DSA_SUCCESS);
        memcpy(saved, registers, sizeof(saved));
        reset_device();
        CHECK(dsa_prepare_matmul_s8(&prepared, &c) == DSA_SUCCESS);
        CHECK(writes == 0u && starts == 0u);
        CHECK(dsa_prepared_execute(&prepared, (const void *)(uintptr_t)0x20000003u,
                                  (void *)(uintptr_t)0x21000005u) == DSA_SUCCESS);
        CHECK(memcmp(saved, registers, sizeof(saved)) == 0);
        verify_bindings(&prepared);
        dsa_prepared_invalidate(&prepared);
        CHECK(dsa_prepared_execute(&prepared, (const void *)(uintptr_t)0x20000003u,
                                  (void *)(uintptr_t)0x21000005u) == DSA_ERR_INVALID_DIM);
        c.depth = 65536u;
        CHECK(dsa_prepare_matmul_s8(&prepared, &c) == DSA_ERR_INVALID_DIM);
    }
}

static void test_pointwise(void)
{
    dsa_prepared_t prepared, expected;
    dsa_conv_s8_config_t c = conv_config();
    dsa_prepared_matmul_s8_config_t matrix = {0};
    c.kernel_h = c.kernel_w = 1u;
    c.pad_top = c.pad_left = 0u;
    matrix.filter_base = weights; matrix.bias_base = bias;
    matrix.multiplier_base = multiplier; matrix.shift_base = shift;
    matrix.rows = c.output_h * c.output_w;
    matrix.depth = matrix.input_stride = matrix.filter_stride = c.input_c;
    matrix.channels = c.output_channels;
    matrix.output_stride = c.dst_row_stride;
    matrix.per_channel = 1u;
    matrix.input_offset = c.input_offset; matrix.output_offset = c.output_offset;
    matrix.activation_min = c.activation_min; matrix.activation_max = c.activation_max;
    for (uint32_t flow = 0u; flow < 2u; ++flow) {
        c.dataflow_mode = matrix.dataflow_mode = flow;
        CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_SUCCESS);
        CHECK(dsa_prepare_matmul_s8(&expected, &matrix) == DSA_SUCCESS);
        CHECK(prepared.ctrl == expected.ctrl && prepared.spatial == 0u);
        CHECK((prepared.ctrl & (NPU_CTRL_HW_CONV | (1u << 1))) == 0u);
        reset_device();
        CHECK(dsa_prepared_execute(&prepared, (void *)(uintptr_t)c.input_base,
                                  (void *)(uintptr_t)c.output_base) == DSA_SUCCESS);
        memcpy(saved, registers, sizeof(saved));
        reset_device();
        CHECK(dsa_prepared_execute(&expected, (void *)(uintptr_t)c.input_base,
                                  (void *)(uintptr_t)c.output_base) == DSA_SUCCESS);
        CHECK(memcmp(saved, registers, sizeof(saved)) == 0);
    }
    c.stride_h = 2u;
    CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_SUCCESS);
    CHECK((prepared.ctrl & NPU_CTRL_HW_CONV) != 0u);
    c.stride_h = 1u; c.group_c /= 2u;
    CHECK(dsa_prepare_conv_s8(&prepared, &c) == DSA_SUCCESS);
    CHECK((prepared.ctrl & NPU_CTRL_HW_CONV) != 0u);
}

static void test_add(void)
{
    dsa_prepared_add_s8_t prepared;
    dsa_vector_config_t normal = {0};
    const int8_t *first = (const int8_t *)(uintptr_t)0x20000003u;
    const int8_t *second = (const int8_t *)(uintptr_t)0x21000005u;
    int8_t *output = (int8_t *)(uintptr_t)0x22000007u;
    normal.operation = DSA_VECTOR_OP_ADD_S8;
    normal.input_base = (uint32_t)(uintptr_t)first;
    normal.rhs_base = (uint32_t)(uintptr_t)second;
    normal.output_base = (uint32_t)(uintptr_t)output;
    normal.length = 259u;
    normal.add.input1_offset = -9; normal.add.input2_offset = 17;
    normal.add.input1_multiplier = normal.add.input2_multiplier = 1 << 30;
    normal.add.input1_shift = -2; normal.add.input2_shift = -3;
    normal.add.left_shift = 20;
    normal.add.output_multiplier = 1234567890;
    normal.add.output_shift = -18;
    normal.output_offset = -2;
    normal.activation_min = -111; normal.activation_max = 117;
    reset_device();
    CHECK(dsa_vector_execute(&normal) == DSA_SUCCESS);
    memcpy(saved, registers, sizeof(saved));
    reset_device();
    CHECK(dsa_prepare_add_s8(&prepared, normal.length, &normal.add,
                             normal.output_offset, normal.activation_min,
                             normal.activation_max) == DSA_SUCCESS);
    CHECK(writes == 0u && starts == 0u);
    CHECK(dsa_prepared_add_s8_execute(&prepared, first, second, output) == DSA_SUCCESS);
    CHECK(memcmp(saved, registers, sizeof(saved)) == 0);
    CHECK(dsa_prepared_add_s8_execute(&prepared, second, first, output) == DSA_SUCCESS);
    CHECK(registers[NPU_REG_LHS_BASE / 4u] == (uint32_t)(uintptr_t)second);
    CHECK(registers[NPU_REG_RHS_BASE / 4u] == (uint32_t)(uintptr_t)first);
    CHECK(dsa_prepared_add_s8_execute(&prepared, first, first, output) == DSA_SUCCESS);
    const uint32_t old_starts = starts;
    CHECK(dsa_prepared_add_s8_execute(&prepared, first, second, (int8_t *)first) == DSA_ERR_INVALID_DIM);
    CHECK(dsa_prepared_add_s8_execute(&prepared, first, second, (int8_t *)second + 1) == DSA_ERR_INVALID_DIM);
    CHECK(dsa_prepared_add_s8_execute(&prepared, first,
        (const int8_t *)(uintptr_t)0xfffffff0u, output) == DSA_ERR_INVALID_DIM);
    CHECK(dsa_prepared_add_s8_execute(&prepared, first, second,
        (int8_t *)(uintptr_t)0xfffffff0u) == DSA_ERR_INVALID_DIM);
    CHECK(dsa_prepared_add_s8_execute(&prepared, NULL, second, output) == DSA_ERR_NULL_PTR);
    CHECK(starts == old_starts);
    busy = 1u;
    CHECK(dsa_prepared_add_s8_execute(&prepared, first, second, output) == DSA_ERR_BUSY);
    CHECK(starts == old_starts);
    busy = 0u;
    for (error_mode = 1u; error_mode <= 3u; ++error_mode) {
        const uint32_t wanted = error_mode == 1u ? 3u : error_mode == 2u ? DSA_ERR_TIMEOUT : 7u;
        CHECK(dsa_prepared_add_s8_execute(&prepared, first, second, output) == wanted);
        active = 0u;
    }
    error_mode = 0u;
    vector_caps &= ~DSA_VECTOR_CAP_ADD_S8;
    CHECK(dsa_prepare_add_s8(&prepared, normal.length, &normal.add,
                             normal.output_offset, normal.activation_min,
                             normal.activation_max) == DSA_ERR_UNSUPPORTED);
    CHECK(prepared.valid == 0u);
    vector_caps |= DSA_VECTOR_CAP_ADD_S8;
    normal.add.input1_shift = 1;
    CHECK(dsa_prepare_add_s8(&prepared, normal.length, &normal.add,
                             normal.output_offset, normal.activation_min,
                             normal.activation_max) == DSA_ERR_INVALID_DIM);
    CHECK(prepared.valid == 0u);
}

static void test_matrix_planning(void)
{
    dsa_matrix_limits_t limits;
    dsa_schedule_t schedule;
    dsa_matmul_config_t matrix;
    dsa_prepared_matmul_s8_config_t c = {0};
    dsa_prepared_t prepared;
    uint32_t queries;
    reset_device();
    registers[NPU_REG_MATRIX_CAPS/4u] = 7u | (8u<<8) | (16u<<16) | (16u<<24);
    registers[NPU_REG_MATRIX_PS_ROWS/4u] = 799u;
    registers[NPU_REG_MATRIX_OUTPUT_BANKS/4u] = 32u | (4u<<16);
    registers[NPU_REG_DMA_MAX_BYTES/4u] = 64u;
    dsa_matrix_query(&limits);
    CHECK(limits.flags==7u && limits.tile_size==16u && limits.ia_cache_blocks==8u);
    CHECK(limits.ps_frame_count==16u && limits.ps_storage_rows==799u);
    CHECK(limits.output_banks_s8==32u && limits.output_banks_s16==4u);
    CHECK(limits.dma_max_bytes==64u);
    dsa_matmul_config_init(&matrix);
    matrix.K=64u;matrix.N=576u;matrix.M=64u;
    matrix.lhs_row_stride=matrix.rhs_row_stride=576u;matrix.dst_row_stride=64u;
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_SUCCESS);
    CHECK(schedule.dataflow_mode==DSA_DATAFLOW_WS);
    CHECK(schedule.tiling.ia_reuse==4u && schedule.tiling.w_reuse==4u);
    matrix.K=1024u;matrix.N=144u;matrix.M=16u;
    matrix.lhs_row_stride=matrix.rhs_row_stride=144u;matrix.dst_row_stride=16u;
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_SUCCESS);
    CHECK(schedule.dataflow_mode==DSA_DATAFLOW_IS);
    CHECK(schedule.tiling.ia_reuse==1u && schedule.tiling.w_reuse==16u);
    matrix.dataflow_mode=DSA_DATAFLOW_WS;
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_SUCCESS);
    CHECK(schedule.dataflow_mode==DSA_DATAFLOW_WS);
    matrix.K=64u;matrix.N=64u;matrix.M=64u;
    matrix.lhs_dtype=DSA_DTYPE_S16;matrix.out_dtype=DSA_DTYPE_S16;
    matrix.lhs_row_stride=128u;matrix.rhs_row_stride=64u;matrix.dst_row_stride=128u;
    matrix.dataflow_mode=DSA_DATAFLOW_AUTO;
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_SUCCESS);
    CHECK(schedule.dataflow_mode==DSA_DATAFLOW_WS && schedule.tiling.ia_reuse<=4u);
    matrix.lhs_tile_packed=matrix.rhs_tile_packed=1u;
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_SUCCESS);
    limits.flags=0u;
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_ERR_UNSUPPORTED);
    c.filter_base=weights;c.bias_base=bias;c.rows=17u;c.depth=17u;c.channels=17u;
    c.input_stride=c.filter_stride=17u;c.output_stride=17u;
    c.dataflow_mode=DSA_SCHEDULE_AUTO;c.rhs_tile_packed=1u;
    c.multiplier=1<<30;c.shift=-4;c.activation_min=-128;c.activation_max=127;
    CHECK(dsa_prepare_matmul_s8(&prepared,&c)==DSA_SUCCESS);
    CHECK(prepared.ctrl & NPU_CTRL_RHS_TILE_PACKED);
    CHECK(prepared.source_filter_base==weights);
    CHECK(prepared.readonly[0].end-prepared.readonly[0].begin==1024u);
    queries=matrix_reads;
    CHECK(dsa_prepared_execute(&prepared,(const void *)(uintptr_t)0x22000000u,
                              (void *)(uintptr_t)0x23000000u)==DSA_SUCCESS);
    CHECK(matrix_reads==queries);
    c.lhs_tile_packed=1u;
    CHECK(dsa_prepare_matmul_s8(&prepared,&c)==DSA_SUCCESS);
    CHECK(prepared.input_bytes==1024u);
    CHECK(dsa_prepared_execute(&prepared,(const void *)(uintptr_t)0x22000001u,
                              (void *)(uintptr_t)0x23000000u)==DSA_ERR_INVALID_DIM);
    registers[NPU_REG_MATRIX_CAPS/4u]=0u;
    CHECK(dsa_prepare_matmul_s8(&prepared,&c)==DSA_ERR_UNSUPPORTED);
    CHECK(prepared.valid==0u);
    dsa_matrix_query(&limits);
    CHECK(limits.flags==(DSA_ENABLE_IS_MODE ? DSA_MATRIX_CAP_IS_SUPPORTED:0u) &&
          limits.ia_cache_blocks==DSA_IA_CACHE_BLOCKS &&
          limits.ps_frame_count==DSA_PS_FRAME_COUNT && limits.tile_size==DSA_TILE_SIZE);
}

static void test_is_capability(void)
{
    dsa_matrix_limits_t limits;
    dsa_schedule_t schedule;
    dsa_matmul_config_t matrix;
    dsa_prepared_matmul_s8_config_t c = {0};
    dsa_prepared_t prepared;
    dsa_conv_s8_config_t conv = conv_config();
    reset_device();
    dsa_matmul_config_init(&matrix);
    matrix.K=1024u;matrix.N=144u;matrix.M=16u;
    matrix.lhs_row_stride=matrix.rhs_row_stride=144u;matrix.dst_row_stride=16u;
    c.filter_base=weights;c.bias_base=bias;c.rows=1024u;c.depth=144u;c.channels=16u;
    c.input_stride=c.filter_stride=144u;c.output_stride=16u;
    c.dataflow_mode=DSA_SCHEDULE_AUTO;
    c.multiplier=1<<30;c.shift=-4;c.activation_min=-128;c.activation_max=127;
    registers[NPU_REG_MATRIX_CAPS/4u]=3u|(8u<<8)|(16u<<16)|(16u<<24);
    registers[NPU_REG_MATRIX_PS_ROWS/4u]=799u;
    registers[NPU_REG_MATRIX_OUTPUT_BANKS/4u]=32u|(4u<<16);
    dsa_matrix_query(&limits);
    CHECK((limits.flags&DSA_MATRIX_CAP_IS_SUPPORTED)==0u);
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_SUCCESS);
    CHECK(schedule.dataflow_mode==DSA_DATAFLOW_WS);
    CHECK(dsa_prepare_matmul_s8(&prepared,&c)==DSA_SUCCESS);
    CHECK((prepared.ctrl&(1u << 3))==0u);
    matrix.dataflow_mode=DSA_DATAFLOW_IS;c.dataflow_mode=DSA_SCHEDULE_IS;
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_ERR_UNSUPPORTED);
    CHECK(dsa_prepare_matmul_s8(&prepared,&c)==DSA_ERR_UNSUPPORTED);
    CHECK(prepared.valid==0u && starts==0u);
    conv.dataflow_mode=DSA_SCHEDULE_AUTO;
    CHECK(dsa_prepare_conv_s8(&prepared,&conv)==DSA_SUCCESS);
    CHECK((prepared.ctrl&(1u << 3))==0u);
    conv.dataflow_mode=DSA_SCHEDULE_IS;
    CHECK(dsa_prepare_conv_s8(&prepared,&conv)==DSA_ERR_UNSUPPORTED);
    CHECK(prepared.valid==0u && starts==0u);
    registers[NPU_REG_MATRIX_CAPS/4u]|=DSA_MATRIX_CAP_IS_SUPPORTED;
    dsa_matrix_query(&limits);
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_SUCCESS);
    CHECK(schedule.dataflow_mode==DSA_DATAFLOW_IS);
    CHECK(dsa_prepare_matmul_s8(&prepared,&c)==DSA_SUCCESS);
    CHECK(prepared.ctrl&(1u << 3));
    registers[NPU_REG_MATRIX_CAPS/4u]=0u;
    dsa_matrix_query(&limits);
    CHECK(((limits.flags&DSA_MATRIX_CAP_IS_SUPPORTED)!=0u)==(DSA_ENABLE_IS_MODE!=0));
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==
          (DSA_ENABLE_IS_MODE ? DSA_SUCCESS:DSA_ERR_UNSUPPORTED));
    CHECK(dsa_prepare_matmul_s8(&prepared,&c)==
          (DSA_ENABLE_IS_MODE ? DSA_SUCCESS:DSA_ERR_UNSUPPORTED));
    matrix.dataflow_mode=DSA_DATAFLOW_AUTO;c.dataflow_mode=DSA_SCHEDULE_AUTO;
    CHECK(dsa_matmul_plan(&matrix,&limits,&schedule)==DSA_SUCCESS);
    CHECK(schedule.dataflow_mode==(DSA_ENABLE_IS_MODE ? DSA_DATAFLOW_IS:DSA_DATAFLOW_WS));
    CHECK(dsa_prepare_matmul_s8(&prepared,&c)==DSA_SUCCESS);
    CHECK(((prepared.ctrl&(1u << 3))!=0u)==(DSA_ENABLE_IS_MODE!=0));
}

int main(void)
{
    constants = mmap(NULL, 65536u, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    CHECK(constants != MAP_FAILED && (uintptr_t)constants <= UINT32_MAX - 65536u);
    weights = (uint32_t)(uintptr_t)constants;
    bias = weights + 32768u; multiplier = weights + 36864u; shift = weights + 40960u;
    for (unsigned channel = 0; channel < 256u; ++channel) {
        ((int32_t *)(uintptr_t)multiplier)[channel] = 1 << 30;
        ((int32_t *)(uintptr_t)shift)[channel] = -8;
    }
    if (!DSA_ENABLE_IS_MODE) {
        test_is_capability(); test_matrix_planning();
    } else {
        test_conv(); test_spatial(); test_matmul(); test_pointwise(); test_add();
        test_matrix_planning(); test_is_capability();
    }
    CHECK(munmap(constants, 65536u) == 0);
    printf("PREPARED_DISPATCH_PASS checks=%u descriptor_bytes=%zu\n", checks, sizeof(dsa_prepared_t));
    return 0;
}
