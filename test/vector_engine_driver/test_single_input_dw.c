/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include "dsa_accel.h"
#include "riscv_nnfunctions.h"

static uint32_t regs[128], reads, writes, starts, failure_start, failure_kind;
static uint32_t start_input[4], start_output[4], start_filter[4];
static unsigned checks, cases;
#define CHECK(x) do { ++checks; assert(x); } while (0)

static int32_t requantize(int32_t value, int32_t multiplier, int32_t shift,
                         int32_t offset, int32_t minimum, int32_t maximum)
{
    const int64_t product = (int64_t)value * multiplier;
    const int64_t divisor = INT64_C(1) << (31-shift);
    int64_t result = product / divisor;
    const int64_t remainder = product % divisor;
    const int64_t magnitude = remainder < 0 ? -remainder : remainder;
    if (magnitude > divisor-magnitude || (magnitude == divisor-magnitude && (result % 2)))
        result += product < 0 ? -1 : 1;
    result += offset;
    if (result < minimum) result = minimum;
    if (result > maximum) result = maximum;
    return result;
}

static void reset_device(void)
{
    memset(regs, 0, sizeof(regs));
    regs[NPU_REG_ID / 4] = 0x4e505531u;
    regs[NPU_REG_CONFIG_ABI / 4] = 2;
    regs[NPU_REG_CONV_CAPS / 4] = 0x00010007u;
    regs[NPU_REG_VECTOR_CAPS / 4] = 0x0131080fu;
    regs[NPU_REG_STATUS / 4] = 1;
    reads = writes = starts = failure_start = failure_kind = 0;
}

static void evaluate_conv_registers(void)
{
    const int8_t *input = (const int8_t *)(uintptr_t)regs[NPU_REG_CONV_INPUT_BASE / 4];
    const int8_t *filter = (const int8_t *)(uintptr_t)regs[NPU_REG_RHS_BASE / 4];
    int8_t *output = (int8_t *)(uintptr_t)regs[NPU_REG_DST_BASE / 4];
    const int32_t *bias = (const int32_t *)(uintptr_t)regs[NPU_REG_BIAS_BASE / 4];
    const int32_t *mult = (const int32_t *)(uintptr_t)regs[NPU_REG_Q_MULT / 4];
    const int32_t *shift = (const int32_t *)(uintptr_t)regs[NPU_REG_Q_SHIFT / 4];
    const int h = regs[NPU_REG_CONV_INPUT_HW / 4] & 65535;
    const int w = regs[NPU_REG_CONV_INPUT_HW / 4] >> 16;
    const int kh = regs[NPU_REG_CONV_KERNEL_HW / 4] & 65535;
    const int kw = regs[NPU_REG_CONV_KERNEL_HW / 4] >> 16;
    const int oh = regs[NPU_REG_CONV_OUTPUT_HW / 4] & 65535;
    const int ow = regs[NPU_REG_CONV_OUTPUT_HW / 4] >> 16;
    const int sh = regs[NPU_REG_CONV_STRIDE_HW / 4] & 65535;
    const int sw = regs[NPU_REG_CONV_STRIDE_HW / 4] >> 16;
    const int dh = regs[NPU_REG_CONV_DILATION_HW / 4] & 65535;
    const int dw = regs[NPU_REG_CONV_DILATION_HW / 4] >> 16;
    const int ph = regs[NPU_REG_CONV_PADDING_HW / 4] & 65535;
    const int pw = regs[NPU_REG_CONV_PADDING_HW / 4] >> 16;
    const int channels = regs[NPU_REG_M / 4];
    CHECK(regs[NPU_REG_CONV_CHANNELS / 4] == 0x00010001u);
    CHECK(regs[NPU_REG_CONV_GROUP_OFFSET / 4] == 0);
    CHECK(regs[NPU_REG_K / 4] == (uint32_t)(oh * ow));
    CHECK(regs[NPU_REG_N / 4] == (uint32_t)(kh * kw));
    CHECK(regs[NPU_REG_RHS_STRIDE_B / 4] == (uint32_t)(kh * kw));
    CHECK(regs[NPU_REG_DST_STRIDE_B / 4] == (uint32_t)channels);
    CHECK(regs[NPU_REG_RHS_ZP / 4] == 0);
    for (int y = 0; y < oh; ++y) for (int x = 0; x < ow; ++x)
        for (int oc = 0; oc < channels; ++oc) {
            int32_t sum = bias ? bias[oc] : 0;
            for (int ky = 0; ky < kh; ++ky) for (int kx = 0; kx < kw; ++kx) {
                const int iy = y * sh + ky * dh - ph;
                const int ix = x * sw + kx * dw - pw;
                if (iy >= 0 && iy < h && ix >= 0 && ix < w)
                    sum += (input[iy * w + ix] + (int32_t)regs[NPU_REG_CONV_INPUT_OFFSET / 4]) *
                           filter[(oc * kh + ky) * kw + kx];
            }
            output[(y * ow + x) * channels + oc] = (int8_t)requantize(sum, mult[oc], shift[oc],
                (int32_t)regs[NPU_REG_DST_ZP / 4], (int32_t)regs[NPU_REG_ACT_MIN / 4],
                (int32_t)regs[NPU_REG_ACT_MAX / 4]);
        }
}

void dsa_mmio_write(uint32_t address, uint32_t value)
{
    const uint32_t offset = address - DSA_MMIO_BASE;
    CHECK(offset < sizeof(regs) && !(offset & 3u));
    ++writes;
    if (offset == NPU_REG_STATUS) { regs[offset / 4] &= ~(value & 4u); return; }
    regs[offset / 4] = value;
    if (offset == NPU_REG_CTRL && (value & 1u)) {
        CHECK(starts < 4 && (value & NPU_CTRL_HW_CONV) && !(value & NPU_CTRL_VECTOR_ENGINE));
        start_input[starts] = regs[NPU_REG_CONV_INPUT_BASE / 4];
        start_output[starts] = regs[NPU_REG_DST_BASE / 4];
        start_filter[starts] = regs[NPU_REG_RHS_BASE / 4];
        ++starts;
        const int failed = starts == failure_start;
        if (!failed) evaluate_conv_registers();
        regs[NPU_REG_STATUS / 4] = failed && failure_kind == 1 ? 2u :
            5u | (failed && failure_kind == 0 ? 3u << DSA_STATUS_ERR_SHIFT : 0u);
        regs[NPU_REG_WB_DATA / 4] = failed && failure_kind == 2 ? 3 : 0;
    }
}

uint32_t dsa_mmio_read(uint32_t address)
{
    const uint32_t offset = address - DSA_MMIO_BASE;
    CHECK(offset < sizeof(regs) && !(offset & 3u));
    ++reads;
    return regs[offset / 4];
}

static void reference_dw(const nmsis_nn_dw_conv_params *p,
                         const nmsis_nn_per_channel_quant_params *q,
                         const nmsis_nn_dims *in, const int8_t *input,
                         const nmsis_nn_dims *f, const int8_t *filter,
                         const int32_t *bias, const nmsis_nn_dims *out, int8_t *output)
{
    for (int b = 0; b < in->n; ++b) for (int y = 0; y < out->h; ++y)
        for (int x = 0; x < out->w; ++x) for (int oc = 0; oc < out->c; ++oc) {
            int32_t sum = bias ? bias[oc] : 0;
            for (int ky = 0; ky < f->h; ++ky) for (int kx = 0; kx < f->w; ++kx) {
                const int iy = y * p->stride.h + ky * p->dilation.h - p->padding.h;
                const int ix = x * p->stride.w + kx * p->dilation.w - p->padding.w;
                if (iy >= 0 && iy < in->h && ix >= 0 && ix < in->w)
                    sum += (input[((b * in->h + iy) * in->w + ix) * in->c + oc / p->ch_mult] +
                            p->input_offset) * filter[(ky * f->w + kx) * out->c + oc];
            }
            output[((b * out->h + y) * out->w + x) * out->c + oc] = (int8_t)requantize(
                sum, q->multiplier[oc], q->shift[oc], p->output_offset, p->activation.min, p->activation.max);
        }
}

typedef riscv_nmsis_nn_status (*dw_entry)(const nmsis_nn_context *, const nmsis_nn_dw_conv_params *,
    const nmsis_nn_per_channel_quant_params *, const nmsis_nn_dims *, const int8_t *,
    const nmsis_nn_dims *, const int8_t *, const nmsis_nn_dims *, const int32_t *, const nmsis_nn_dims *, int8_t *);

int main(void)
{
    uint8_t *memory = mmap(NULL, 65536, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    CHECK(memory != MAP_FAILED && (uintptr_t)memory < UINT32_MAX - 65536u);
    int8_t *input = (int8_t *)memory, *filter = (int8_t *)(memory + 4096);
    int8_t *output = (int8_t *)(memory + 8192), *scratch = (int8_t *)(memory + 24577);
    int32_t *bias = (int32_t *)(memory + 12288), *mult = (int32_t *)(memory + 16384), *shift = (int32_t *)(memory + 20480);
    int8_t expected[2048], saved_filter[1024];
    nmsis_nn_context ctx = {scratch, 784};
    nmsis_nn_per_channel_quant_params q = {mult, shift};
    nmsis_nn_dims bd = {1, 1, 1, 16};
    const dw_entry entries[] = {riscv_depthwise_conv_s8, riscv_depthwise_conv_wrapper_s8,
        riscv_depthwise_conv_s8_acc, riscv_depthwise_conv_wrapper_s8_acc};
    for (int i = 0; i < 4096; ++i) input[i] = (int8_t)((i * 19) % 127 - 63);
    for (int i = 0; i < 1024; ++i) filter[i] = (int8_t)((i * 11) % 23 - 11);
    memcpy(saved_filter, filter, sizeof(saved_filter));
    for (int i = 0; i < 32; ++i) {
        bias[i] = 17 * i - 53; mult[i] = 0x50000000 + i * 71033; shift[i] = i % 5 - 3;
    }
    const int shapes[][11] = {
        {5,6,2,3,2,1,2,1,1,1,1}, {6,7,3,2,3,2,1,2,2,2,1},
        {5,5,3,3,8,1,1,1,1,1,1}, {8,8,7,7,16,2,2,1,1,3,3},
        {5,5,3,3,17,1,1,1,1,1,1}, {8,13,5,10,3,1,1,1,1,2,2}};
    for (unsigned shape = 0; shape < sizeof(shapes) / sizeof(shapes[0]); ++shape) {
        const int *v = shapes[shape];
        nmsis_nn_dims in = {2,v[0],v[1],1}, f = {1,v[2],v[3],v[4]};
        nmsis_nn_dw_conv_params p = {.input_offset=19,.output_offset=-7,.ch_mult=v[4],
            .stride={v[6],v[5]},.padding={v[10],v[9]},.dilation={v[8],v[7]},.activation={-101,109}};
        nmsis_nn_dims out = {2,(in.h + 2*p.padding.h - p.dilation.h*(f.h-1)-1)/p.stride.h+1,
            (in.w + 2*p.padding.w - p.dilation.w*(f.w-1)-1)/p.stride.w+1,p.ch_mult};
        const int count = out.n * out.h * out.w * out.c;
        const int weights = f.h * f.w * out.c;
        const int supported = DSA_NN_VECTOR_ENABLE && out.c <= 16 && f.h*f.w <= 49;
        const int32_t *selected_bias = shape % 2 ? NULL : bias;
        CHECK(count <= (int)sizeof(expected) && weights <= (int)sizeof(saved_filter));
        reference_dw(&p,&q,&in,input,&f,filter,selected_bias,&out,expected);
        for (uint32_t mask = 0; mask < 32; ++mask) for (unsigned entry = 0; entry < 4; ++entry) {
            dsa_nn_set_accelerators(mask);
            CHECK(riscv_depthwise_conv_wrapper_s8_get_buffer_size(&p,&in,&f,&out) == (supported ? weights : 0));
            CHECK(riscv_depthwise_conv_wrapper_s8_get_buffer_size_acc(&p,&in,&f,&out) == (supported ? weights : 0));
            CHECK(riscv_depthwise_conv_wrapper_s8_get_buffer_size_dsp(&p,&in,&f,&out) == (supported ? weights : 0));
            ctx.size = supported ? weights : 784;
            memset(scratch-1,0x6b,786); memset(output,0x55,2048); reset_device();
            CHECK(entries[entry](&ctx,&p,&q,&in,input,&f,filter,&bd,selected_bias,&out,output) == RISCV_NMSIS_NN_SUCCESS);
            CHECK(memcmp(output,expected,(size_t)count) == 0);
            CHECK(memcmp(filter,saved_filter,sizeof(saved_filter)) == 0);
            for (int i = count; i < 2048; ++i) CHECK(output[i] == 0x55);
            if (supported && (mask & DSA_NN_ACCEL_DW)) {
                CHECK(starts == 2 && reads && writes);
                CHECK(start_input[1]-start_input[0] == (uint32_t)(in.h*in.w));
                CHECK(start_output[1]-start_output[0] == (uint32_t)(out.h*out.w*out.c));
                CHECK(start_filter[0] == (uint32_t)(uintptr_t)scratch && start_filter[1] == start_filter[0]);
                for (int oc = 0; oc < out.c; ++oc) for (int tap = 0; tap < f.h*f.w; ++tap)
                    CHECK(scratch[oc*f.h*f.w+tap] == filter[tap*out.c+oc]);
                CHECK(scratch[-1] == 0x6b && scratch[weights] == 0x6b);
            } else {
                CHECK(!starts && !reads && !writes);
                for (int i = 0; i < 784; ++i) CHECK(scratch[i] == 0x6b);
            }
            ++cases;
        }
    }

#if DSA_NN_VECTOR_ENABLE
    dsa_nn_set_accelerators(DSA_NN_ACCEL_DW);
    nmsis_nn_dims in = {2,5,5,1}, f = {1,3,3,8}, out = {2,5,5,8};
    nmsis_nn_dw_conv_params p = {.input_offset=19,.output_offset=-7,.ch_mult=8,
        .stride={1,1},.padding={1,1},.dilation={1,1},.activation={-101,109}};
    reference_dw(&p,&q,&in,input,&f,filter,bias,&out,expected);
    for (int invalid = 0; invalid < 11; ++invalid) {
        ctx = (nmsis_nn_context){scratch,72}; reset_device();
        memset(scratch,0x6b,784); memset(output,0x55,2048);
        if (invalid == 0) ctx.size = 71;
        if (invalid == 1) ctx.buf = NULL;
        if (invalid == 2) ctx.size = -1;
        if (invalid == 3) ctx.buf = (void *)(uintptr_t)0xfffffff0u;
        if (invalid == 4) ctx.buf = filter;
        if (invalid == 5) ctx.buf = input;
        if (invalid == 6) ctx.buf = bias;
        if (invalid == 7) ctx.buf = mult;
        if (invalid == 8) ctx.buf = shift;
        if (invalid == 9) regs[NPU_REG_VECTOR_CAPS/4] = 0;
        if (invalid == 10) regs[NPU_REG_CONV_CAPS/4] = 0;
        CHECK(riscv_depthwise_conv_wrapper_s8_acc(&ctx,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS);
        CHECK(memcmp(output,expected,400) == 0 && !starts && !writes);
        CHECK(memcmp(filter,saved_filter,sizeof(saved_filter)) == 0);
        for (int i = 0; i < 784; ++i) CHECK(scratch[i] == 0x6b);
        ++cases;
    }
    ctx = (nmsis_nn_context){output,72}; reset_device();
    memset(output,0x55,2048);
    riscv_nmsis_nn_status status;
    CHECK(!riscv_depthwise_conv_s8_try_dsa(&ctx,&p,&q,&in,input,&f,filter,bias,&out,output,&status));
    CHECK(!starts && !reads && !writes);
    for (int i = 0; i < 2048; ++i) CHECK(output[i] == 0x55);
    ctx = (nmsis_nn_context){scratch,72};
    for (int invalid = 0; invalid < 4; ++invalid) {
        const int32_t saved_mult = mult[7], saved_shift = shift[7], saved_bias = bias[7];
        reset_device(); memset(scratch,0x6b,784);
        if (invalid == 0) mult[7] = -1;
        if (invalid == 1) shift[7] = -32;
        if (invalid == 2) shift[7] = 31;
        if (invalid == 3) bias[7] = INT32_MAX;
        CHECK(!riscv_depthwise_conv_s8_try_dsa(&ctx,&p,&q,&in,input,&f,filter,bias,&out,output,&status));
        CHECK(!starts && !writes);
        for (int i = 0; i < 784; ++i) CHECK(scratch[i] == 0x6b);
        mult[7] = saved_mult; shift[7] = saved_shift; bias[7] = saved_bias;
        ++cases;
    }
    reset_device(); regs[NPU_REG_STATUS/4] = 2; memset(scratch,0x6b,784);
    CHECK(riscv_depthwise_conv_wrapper_s8_acc(&ctx,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_NO_IMPL_ERROR);
    CHECK(!starts && !writes);
    for (int i = 0; i < 784; ++i) CHECK(scratch[i] == 0x6b);
    for (unsigned failure = 0; failure < 3; ++failure) for (unsigned batch = 1; batch <= 2; ++batch) {
        reset_device(); failure_kind = failure; failure_start = batch; memset(output,0x55,2048);
        CHECK(riscv_depthwise_conv_wrapper_s8_acc(&ctx,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_NO_IMPL_ERROR);
        CHECK(starts == batch);
        if (batch == 2) CHECK(memcmp(output,expected,200) == 0);
        for (unsigned i = (batch-1)*200; i < 2048; ++i) CHECK(output[i] == 0x55);
        ++cases;
    }
#endif
    CHECK(munmap(memory,65536) == 0);
    printf("NMSIS_SINGLE_INPUT_DW_PASS cases=%u checks=%u enabled=%u\n", cases, checks, DSA_NN_VECTOR_ENABLE);
    return 0;
}
