/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include "dsa_accel.h"
#ifdef TEST_NMSIS
#include "riscv_nnfunctions.h"
#endif

static uint32_t regs[128];
static uint32_t starts, writes, polls, complete_after, failure_start;
static uint32_t start_input[16], start_output[16];
static int active, stall;
static unsigned checks;
#define CHECK(condition) do { ++checks; assert(condition); } while (0)

static void reset_device(void)
{
    memset(regs, 0, sizeof(regs));
    regs[NPU_REG_ID / 4] = 0x4e505531u;
    regs[NPU_REG_CONFIG_ABI / 4] = 2u;
    regs[NPU_REG_DW_POOL_CAPS / 4] = 0x0131040fu;
    regs[NPU_REG_STATUS / 4] = 1u;
    starts = writes = polls = failure_start = 0u;
    complete_after = 1u;
    active = stall = 0;
}

void dsa_mmio_write(uint32_t address, uint32_t data)
{
    const uint32_t offset = address - DSA_MMIO_BASE;
    CHECK(offset < sizeof(regs) && !(offset & 3u));
    ++writes;
    if (offset == NPU_REG_STATUS) {
        regs[offset / 4] &= ~(data & (1u << 2));
        return;
    }
    regs[offset / 4] = data;
    if (offset == NPU_REG_CTRL && (data & 1u)) {
        CHECK(!active && starts < 16u);
        start_input[starts] = regs[NPU_REG_LHS_BASE / 4];
        start_output[starts] = regs[NPU_REG_DST_BASE / 4];
        ++starts;
        polls = 0u;
        active = 1;
        regs[NPU_REG_STATUS / 4] = 1u << 1;
    }
}

uint32_t dsa_mmio_read(uint32_t address)
{
    const uint32_t offset = address - DSA_MMIO_BASE;
    CHECK(offset < sizeof(regs) && !(offset & 3u));
    if (offset == NPU_REG_STATUS && active && !stall && ++polls >= complete_after) {
        const uint32_t error = starts == failure_start ? 2u : 0u;
        active = 0;
        regs[offset / 4] = 1u | (1u << 2) | (error << 3);
        regs[NPU_REG_WB_DATA / 4] = error;
    }
    return regs[offset / 4];
}

static dsa_dw_pool_config_t image_config(void)
{
    dsa_dw_pool_config_t c;
    dsa_dw_pool_config_init(&c);
    c.input_base = 0x10003u; c.rhs_base = 0x20001u; c.output_base = 0x40003u;
    c.bias_base = 0x30000u; c.multiplier_base = 0x31000u; c.shift_base = 0x32000u;
    c.input_h = 4u; c.input_w = 5u; c.input_c = 3u;
    c.kernel_h = c.kernel_w = 3u;
    c.output_h = 4u; c.output_w = 5u;
    c.pad_top = c.pad_left = 1u;
    c.input_offset = 17; c.output_offset = -4;
    return c;
}

static void expect_invalid(dsa_dw_pool_config_t c)
{
    reset_device();
    CHECK(dsa_dw_pool_validate(&c) == DSA_ERR_INVALID_DIM);
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_INVALID_DIM);
    CHECK(!starts && !writes);
}

static void test_low_level(void)
{
    dsa_dw_pool_config_t c = image_config(), bad;
    reset_device();
    CHECK(dsa_dw_pool_capabilities() == 0x0131040fu);
    CHECK(dsa_dw_pool_validate(&c) == DSA_SUCCESS && !writes);
    CHECK(dsa_dw_pool_execute(&c) == DSA_SUCCESS && starts == 1u && !active);
    CHECK(regs[NPU_REG_CTRL / 4] == 0x115u);
    CHECK(regs[NPU_REG_DW_POOL_OP / 4] == DSA_DW_OP_DW_S8);
    CHECK(regs[NPU_REG_CONV_INPUT_BASE / 4] == c.input_base);
    CHECK(regs[NPU_REG_CONV_INPUT_HW / 4] == 0x00050004u);
    CHECK(regs[NPU_REG_CONV_CHANNELS / 4] == 0x00030003u);
    CHECK(regs[NPU_REG_CONV_INPUT_OFFSET / 4] == 17u);
    CHECK(regs[NPU_REG_DST_ZP / 4] == (uint32_t)-4);
    CHECK(!(regs[NPU_REG_STATUS / 4] & (1u << 2)));

    c.bias_base = 0u;
    CHECK(dsa_dw_pool_execute(&c) == DSA_SUCCESS && starts == 2u);
    c.bypass_cache = 1u;
    CHECK(dsa_dw_pool_execute(&c) == DSA_SUCCESS && regs[NPU_REG_CTRL / 4] == 0x195u);
    c = image_config();

    reset_device(); regs[NPU_REG_DW_POOL_CAPS / 4] = 0u;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);
    reset_device(); regs[NPU_REG_DW_POOL_CAPS / 4] = 0x0231040fu;
    CHECK(dsa_dw_pool_capabilities() == 0u);
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);
    reset_device(); regs[NPU_REG_DW_POOL_CAPS / 4] = 0x0131000fu;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);
    reset_device(); regs[NPU_REG_DW_POOL_CAPS / 4] = 0x0108040fu;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);
    reset_device(); regs[NPU_REG_ID / 4] = 0u;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);
    reset_device(); regs[NPU_REG_CONFIG_ABI / 4] = 1u;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);
    reset_device(); regs[NPU_REG_STATUS / 4] = 1u << 1;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_BUSY && !writes);
    reset_device(); failure_start = 1u;
    CHECK(dsa_dw_pool_execute(&c) == 2u && starts == 1u && !active);
    CHECK(!(regs[NPU_REG_STATUS / 4] & (1u << 2)));
    reset_device(); complete_after = 8u;
    CHECK(dsa_dw_pool_execute(&c) == DSA_SUCCESS && polls == 8u);
    reset_device(); stall = 1;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_TIMEOUT && starts == 1u && active);
    {
        const uint32_t previous_writes = writes;
        CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_BUSY && writes == previous_writes);
    }

    reset_device();
    CHECK(dsa_dw_pool_validate(NULL) == DSA_ERR_NULL_PTR);
    CHECK(dsa_dw_pool_execute(NULL) == DSA_ERR_NULL_PTR && !writes);
    bad = c; bad.operation = 9u; expect_invalid(bad);
    bad = c; bad.vector_s16 = 1u; expect_invalid(bad);
    bad = c; bad.input_h = 0u; expect_invalid(bad);
    bad = c; bad.input_c = 65536u; expect_invalid(bad);
    bad = c; bad.kernel_h = bad.kernel_w = 8u; expect_invalid(bad);
    bad = c; bad.stride_h = 0u; expect_invalid(bad);
    bad = c; bad.dilation_w = 0u; expect_invalid(bad);
    bad = c; bad.pad_top = 65536u; expect_invalid(bad);
    bad = c; bad.input_offset = -128; expect_invalid(bad);
    bad = c; bad.input_offset = 129; expect_invalid(bad);
    bad = c; bad.output_offset = 128; expect_invalid(bad);
    bad = c; bad.activation_min = 128; expect_invalid(bad);
    bad = c; bad.activation_max = -129; expect_invalid(bad);
    bad = c; bad.activation_min = 10; bad.activation_max = -10; expect_invalid(bad);
    bad = c; bad.multiplier_base = 0u; expect_invalid(bad);
    bad = c; bad.shift_base |= 1u; expect_invalid(bad);
    bad = c; bad.bias_base |= 2u; expect_invalid(bad);
    bad = c; bad.input_base = 0xfffffff0u; expect_invalid(bad);
    bad = c; bad.output_base = 0xfffffff0u; expect_invalid(bad);
    bad = c; bad.rhs_base = 0xfffffff0u; expect_invalid(bad);
    bad = c; bad.multiplier_base = 0xfffffffcu; expect_invalid(bad);
    bad = c; bad.output_base = c.input_base; expect_invalid(bad);
    bad = c; bad.output_base = c.input_base + 59u; expect_invalid(bad);
    bad = c; bad.output_base = c.rhs_base; expect_invalid(bad);
    bad = c; bad.output_base = c.multiplier_base + 8u; expect_invalid(bad);
    bad = c; bad.output_base = c.shift_base - 1u; expect_invalid(bad);
    bad = c; bad.output_base = c.bias_base; expect_invalid(bad);

    c = image_config(); c.input_offset = c.output_offset = 0;
    for (uint32_t operation = DSA_DW_OP_AVGPOOL_S8; operation <= DSA_DW_OP_MINPOOL_S8; ++operation) {
        c.operation = operation;
        reset_device();
        CHECK(dsa_dw_pool_execute(&c) == DSA_SUCCESS);
        CHECK(regs[NPU_REG_CTRL / 4] == 0x111u && regs[NPU_REG_DW_POOL_OP / 4] == operation);
    }
    bad = c; bad.pad_top = 3u; expect_invalid(bad);
    bad = c; bad.output_w = 8u; expect_invalid(bad);
    bad = c; bad.output_h = 7u; expect_invalid(bad);
    bad = c; bad.dilation_h = 2u; expect_invalid(bad);
    bad = c; bad.input_offset = 1; expect_invalid(bad);

    dsa_dw_pool_config_init(&c);
    c.input_base = 0x10000u; c.rhs_base = 0x20000u; c.output_base = 0x40000u; c.length = 17u;
    for (uint32_t wide = 0; wide <= 1u; ++wide) {
        c.vector_s16 = wide;
        for (uint32_t operation = DSA_DW_OP_SUM; operation <= DSA_DW_OP_HADAMARD; ++operation) {
            c.operation = operation;
            reset_device();
            CHECK(dsa_dw_pool_execute(&c) == DSA_SUCCESS);
            CHECK(regs[NPU_REG_DW_POOL_OP / 4] == (operation | (wide << 8)));
            CHECK(regs[NPU_REG_DW_POOL_LENGTH / 4] == 17u);
        }
    }
    bad = c; bad.length = 0u; expect_invalid(bad);
    bad = c; bad.length = 0xffffffffu; expect_invalid(bad);
    bad = c; bad.output_base |= 1u; expect_invalid(bad);
    bad = c; bad.input_base |= 1u; expect_invalid(bad);
    bad = c; bad.rhs_base |= 1u; expect_invalid(bad);
    bad = c; bad.rhs_base = 0u; expect_invalid(bad);
    bad = c; bad.output_base = c.input_base; expect_invalid(bad);
    bad = c; bad.output_base = c.rhs_base; expect_invalid(bad);
    c.operation = DSA_DW_OP_SUM; c.rhs_base = 0u;
    reset_device(); CHECK(dsa_dw_pool_execute(&c) == DSA_SUCCESS);
    reset_device(); regs[NPU_REG_DW_POOL_CAPS / 4] &= ~DSA_DW_POOL_CAP_VECTOR_S16;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);
    c.vector_s16 = 0u;
    reset_device(); regs[NPU_REG_DW_POOL_CAPS / 4] &= ~DSA_DW_POOL_CAP_VECTOR_S8;
    CHECK(dsa_dw_pool_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);

    /* DMA allocation end addresses fit the hardware's 32-bit range fields. */
    c.input_base = 0xfffffffeu; c.length = 1u;
    CHECK(dsa_dw_pool_validate(&c) == DSA_SUCCESS);
    c.length = 2u; expect_invalid(c);
}

#ifdef TEST_NMSIS
static void test_nmsis(void)
{
    int8_t *input = (int8_t *)(uintptr_t)0x10000u;
    int8_t *filter = (int8_t *)(uintptr_t)0x20000u;
    int32_t *bias = (int32_t *)(uintptr_t)0x30000u;
    int32_t *mult = (int32_t *)(uintptr_t)0x31000u;
    int32_t *shift = (int32_t *)(uintptr_t)0x32000u;
    int8_t *output = (int8_t *)(uintptr_t)0x40000u;
    nmsis_nn_dims in = {2, 4, 5, 3}, out = {2, 4, 5, 3}, f = {1, 3, 3, 3}, bd = {1, 1, 1, 3};
    nmsis_nn_context ctx = {0};
    nmsis_nn_dw_conv_params p = {17, -4, 1, {1, 1}, {1, 1}, {1, 1}, {-128, 127}};
    nmsis_nn_per_channel_quant_params q = {mult, shift};
    nmsis_nn_pool_params pp = {{1, 1}, {1, 1}, {-128, 127}};
    void *arena = mmap(input, 0x40000u, PROT_NONE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    CHECK(arena == input);
#if DSA_NN_DW_POOL_ENABLE
    reset_device();
    CHECK(riscv_depthwise_conv_wrapper_s8_acc(NULL, &p, &q, &in, input, &f, filter,
                                              &bd, bias, &out, output) == RISCV_NMSIS_NN_SUCCESS);
    CHECK(starts == 2u && start_input[1] == 0x10000u + 60u && start_output[1] == 0x40000u + 60u);
    reset_device();
    CHECK(riscv_depthwise_conv_s8(NULL, &p, &q, &in, input, &f, filter,
                                 &bd, NULL, &out, output) == RISCV_NMSIS_NN_SUCCESS && starts == 2u);
    reset_device();
    CHECK(riscv_avgpool_s8(NULL, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_SUCCESS && starts == 2u);
    reset_device();
    CHECK(riscv_max_pool_s8(NULL, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_SUCCESS && starts == 2u);
    reset_device(); failure_start = 2u;
    CHECK(riscv_depthwise_conv_wrapper_s8_acc(NULL, &p, &q, &in, input, &f, filter,
                                              &bd, bias, &out, output) == RISCV_NMSIS_NN_NO_IMPL_ERROR);
    CHECK(starts == 2u && !active);
    reset_device(); stall = 1;
    CHECK(riscv_avgpool_s8(NULL, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_NO_IMPL_ERROR);
    CHECK(starts == 1u && active);
    reset_device(); regs[NPU_REG_STATUS / 4] = 1u << 1;
    CHECK(riscv_max_pool_s8(NULL, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_NO_IMPL_ERROR);
    CHECK(!writes);
    {
        riscv_nmsis_nn_status status;
        reset_device();
        CHECK(!riscv_depthwise_conv_s8_try_dsa(&p, &q, &in,
               (const int8_t *)(uintptr_t)0xffffffe0u, &f, filter, bias, &out, output, &status));
        CHECK(!writes);
        CHECK(!riscv_depthwise_conv_s8_try_dsa(&p, &q, &in,
               input, &f, filter, bias, &out, input + 60, &status));
        CHECK(!writes);
        CHECK(!riscv_depthwise_conv_s8_try_dsa(&p, &q, &in,
               input, &f, filter, bias, &out, (int8_t *)bias - 60, &status));
        CHECK(!writes);
        CHECK(!riscv_pool_s8_try_dsa(DSA_DW_OP_AVGPOOL_S8, &pp, &in,
               input, &f, &out, input + 60, &status));
        CHECK(!writes);
        in.n = out.n = 1; p.ch_mult = 2; out.c = 6;
        CHECK(!riscv_depthwise_conv_s8_try_dsa(&p, &q, &in, input, &f, filter, bias, &out, output, &status));
        CHECK(!writes);
        out.c = in.c; p.ch_mult = 1; in.n = out.n = 2;
    }
    reset_device();
    CHECK(riscv_depthwise_conv_wrapper_s8_acc(NULL, &p, &q, &in, NULL, &f, filter,
                                              &bd, bias, &out, output) == RISCV_NMSIS_NN_ARG_ERROR);
    CHECK(!writes);
    pp.padding.w = 3;
    CHECK(riscv_avgpool_s8(NULL, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_ARG_ERROR && !writes);
    pp.padding.w = 1; out.w = 8;
    CHECK(riscv_max_pool_s8(NULL, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_ARG_ERROR && !writes);
#endif
    CHECK(mprotect(arena, 0x40000u, PROT_READ | PROT_WRITE) == 0);
    reset_device(); regs[NPU_REG_DW_POOL_CAPS / 4] = 0u;
    in = (nmsis_nn_dims){1, 1, 2, 2}; out = in; f = (nmsis_nn_dims){1, 1, 1, 2};
    p = (nmsis_nn_dw_conv_params){0, 1, 1, {1, 1}, {0, 0}, {1, 1}, {-128, 127}};
    input[0] = -3; input[1] = 4; input[2] = 6; input[3] = -5;
    filter[0] = 2; filter[1] = -3; bias[0] = 2; bias[1] = -2;
    mult[0] = mult[1] = 0x40000000; shift[0] = shift[1] = 1;
    memset(output, 0x55, 16);
    CHECK(riscv_depthwise_conv_wrapper_s8_acc(&ctx, &p, &q, &in, input, &f, filter,
                                              &bd, bias, &out, output) == RISCV_NMSIS_NN_SUCCESS);
    CHECK(output[0] == -3 && output[1] == -13 && output[2] == 15 && output[3] == 14);
    CHECK(!starts && !writes);
    CHECK(riscv_depthwise_conv_wrapper_s8_get_buffer_size_acc(&p, &in, &f, &out) ==
          riscv_depthwise_conv_wrapper_s8_get_buffer_size(&p, &in, &f, &out));

    reset_device();
    in = (nmsis_nn_dims){1, 1, 1, 1}; out = (nmsis_nn_dims){1, 1, 1, 2};
    p.ch_mult = 2; p.output_offset = 0;
    CHECK(riscv_depthwise_conv_wrapper_s8_acc(&ctx, &p, &q, &in, input, &f, filter,
                                              &bd, NULL, &out, output) == RISCV_NMSIS_NN_SUCCESS);
    CHECK(output[0] == -6 && output[1] == 9 && !starts && !writes);

    reset_device(); regs[NPU_REG_DW_POOL_CAPS / 4] = 0u;
    in = (nmsis_nn_dims){1, 1, 2, 1}; out = (nmsis_nn_dims){1, 1, 3, 1};
    f = (nmsis_nn_dims){1, 1, 2, 1};
    pp = (nmsis_nn_pool_params){{1, 1}, {1, 0}, {-128, 127}};
    input[0] = -3; input[1] = -7;
    CHECK(riscv_max_pool_s8(&ctx, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_SUCCESS);
    CHECK(output[0] == -3 && output[1] == -3 && output[2] == -7);
    CHECK(riscv_avgpool_s8(&ctx, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_SUCCESS);
    CHECK(output[0] == -3 && output[1] == -5 && output[2] == -7);
    pp.activation.min = -4; pp.activation.max = -2;
    CHECK(riscv_avgpool_s8(&ctx, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_SUCCESS);
    CHECK(output[0] == -3 && output[1] == -4 && output[2] == -4);
    pp.padding.w = 0; pp.activation.min = -128; pp.activation.max = 127; out.w = 1;
    input[0] = -1; input[1] = 0;
    CHECK(riscv_avgpool_s8(&ctx, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_SUCCESS && output[0] == -1);
    input[0] = 1;
    CHECK(riscv_avgpool_s8(&ctx, &pp, &in, input, &f, &out, output) == RISCV_NMSIS_NN_SUCCESS && output[0] == 1);
    CHECK(!starts && !writes);
    CHECK(munmap(arena, 0x40000u) == 0);
}
#endif

int main(void)
{
    test_low_level();
#ifdef TEST_NMSIS
    test_nmsis();
#endif
    printf("DW_POOL_DRIVER_PASS assertions=%u\n", checks);
    return 0;
}
