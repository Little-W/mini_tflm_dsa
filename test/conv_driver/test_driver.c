#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "dsa_accel.h"
#ifdef TEST_NMSIS
#include <sys/mman.h>
#include "riscv_nnfunctions.h"
#endif

static uint32_t regs[64], snapshots[64][64];
static unsigned starts, writes, polls;
static uint32_t caps;
static int active, busy_before, error_mode;

void dsa_mmio_write(uint32_t addr, uint32_t value)
{
    unsigned reg = (addr - DSA_MMIO_BASE) / 4u;
    assert(addr >= DSA_MMIO_BASE && reg < 64u && !(addr & 3u));
    writes++;
    if (reg == NPU_REG_STATUS / 4u) { active = 0; return; }
    regs[reg] = value;
    if (reg == NPU_REG_CTRL / 4u && (value & 1u)) {
        assert(starts < 64u);
        memcpy(snapshots[starts++], regs, sizeof regs);
        active = 1;
    }
}
uint32_t dsa_mmio_read(uint32_t addr)
{
    unsigned reg = (addr - DSA_MMIO_BASE) / 4u;
    assert(addr >= DSA_MMIO_BASE && reg < 64u && !(addr & 3u));
    if (reg == NPU_REG_ID / 4u) return 0x4e505531u;
    if (reg == NPU_REG_CONFIG_ABI / 4u) return 2u;
    if (reg == NPU_REG_CONV_CAPS / 4u) return caps;
    if (reg == NPU_REG_STATUS / 4u) {
        polls++;
        if (busy_before || (active && error_mode == 2)) return 2u;
        if (active) return 4u | (error_mode == 1 ? 3u << 3 : 0u);
        return 1u;
    }
    if (reg == NPU_REG_WB_DATA / 4u) return 0u;
    return regs[reg];
}
static void reset_mock(void)
{
    memset(regs, 0, sizeof regs); memset(snapshots, 0, sizeof snapshots);
    starts = writes = polls = 0; active = busy_before = error_mode = 0;
    caps = 0x00010007u;
}
static dsa_conv_s8_config_t config(void)
{
    dsa_conv_s8_config_t c = {0};
    c.input_base = 0x1003; c.filter_base = 0x2001; c.output_base = 0x3003;
    c.bias_base = 0x4000; c.multiplier_base = 0x5000; c.shift_base = 0x6000;
    c.input_h = 9; c.input_w = 11; c.input_c = c.group_c = 3;
    c.kernel_h = 3; c.kernel_w = 3; c.output_h = 9; c.output_w = 11;
    c.stride_h = c.stride_w = c.dilation_h = c.dilation_w = 1;
    c.pad_top = c.pad_left = 1; c.output_channels = c.dst_row_stride = 7;
    c.input_offset = 17; c.output_offset = -9;
    c.activation_min = -120; c.activation_max = 115;
    return c;
}
static void test_low_level(void)
{
    dsa_conv_s8_config_t c = config(), bad;
    reset_mock();
    assert(dsa_conv_s8_execute(&c) == DSA_SUCCESS && starts == 1);
    assert(regs[NPU_REG_K/4] == 99 && regs[NPU_REG_N/4] == 27 && regs[NPU_REG_M/4] == 7);
    assert(regs[NPU_REG_RHS_STRIDE_B/4] == 27 && regs[NPU_REG_DST_STRIDE_B/4] == 7);
    assert(regs[NPU_REG_LHS_STRIDE_B/4] == ((27u+DSA_TILE_SIZE-1u)/DSA_TILE_SIZE)*DSA_TILE_SIZE*2u);
    assert(regs[NPU_REG_LHS_ZP/4] == 0 && regs[NPU_REG_CONV_INPUT_OFFSET/4] == 17);
    assert(regs[NPU_REG_CONV_INPUT_HW/4] == ((11u << 16) | 9u));
    assert(regs[NPU_REG_CTRL/4] == 0x57u); /* no IS or 16x8-output bit */
    reset_mock(); c.dataflow_mode = 1;
    assert(dsa_conv_s8_execute(&c) == DSA_SUCCESS && starts == 1);
    assert(regs[NPU_REG_CTRL/4] == 0x5fu && regs[NPU_REG_DATAFLOW/4] == 1u);
    assert(regs[NPU_REG_K/4] == 99 && regs[NPU_REG_N/4] == 27 && regs[NPU_REG_M/4] == 7);
    assert(regs[NPU_REG_LHS_BASE/4] == c.input_base && regs[NPU_REG_RHS_BASE/4] == c.filter_base);
#if DSA_TILE_SIZE == 16u && DSA_IA_CACHE_BLOCKS == 4u && DSA_PS_FRAME_COUNT == 16u && DSA_PS_POOL_BYTES == 0u
    /* IS streams Cout rows and stations output-position columns: 1 x 7 tiles. */
    assert(regs[NPU_REG_IA_REUSE/4] == 1u && regs[NPU_REG_W_REUSE/4] == 4u);
    assert(regs[NPU_REG_ROW_GROUPS/4] == 1u && regs[NPU_REG_ROW_TAIL_TILES/4] == 1u);
    assert(regs[NPU_REG_COL_GROUPS/4] == 2u && regs[NPU_REG_COL_TAIL_TILES/4] == 3u);
#endif
    reset_mock(); caps = 0x00010003u;
    assert(dsa_conv_s8_execute(&c) == DSA_ERR_UNSUPPORTED && !writes && !starts);
    c.dataflow_mode = 0;
    assert(dsa_conv_s8_execute(&c) == DSA_SUCCESS && starts == 1); /* old WS-only capability */
    reset_mock(); c.bypass_cache = 1;
    assert(dsa_conv_s8_execute(&c) == DSA_SUCCESS && regs[NPU_REG_CTRL/4] == 0xd7u);
    reset_mock(); caps = 0;
    assert(dsa_conv_s8_execute(&c) == DSA_ERR_UNSUPPORTED && !writes && !starts);
    reset_mock(); caps = 0x20003;
    assert(dsa_conv_s8_execute(&c) == DSA_ERR_UNSUPPORTED && !writes);
    reset_mock(); busy_before = 1;
    assert(dsa_conv_s8_execute(&c) == DSA_ERR_BUSY && !writes && !starts);
    reset_mock(); error_mode = 1;
    assert(dsa_conv_s8_execute(&c) == 3u && starts == 1);
    reset_mock(); error_mode = 2;
    assert(dsa_conv_s8_execute(&c) == DSA_ERR_TIMEOUT && starts == 1 && active);
    reset_mock();
    assert(dsa_conv_s8_execute(NULL) == DSA_ERR_NULL_PTR && !writes);
    bad = c; bad.input_base = 0xffffff00u;
    assert(dsa_conv_s8_execute(&bad) == DSA_ERR_INVALID_DIM && !writes);
    bad = c; bad.stride_h = 0;
    assert(dsa_conv_s8_execute(&bad) == DSA_ERR_INVALID_DIM && !writes);
    bad = c; bad.group_offset = 1;
    assert(dsa_conv_s8_execute(&bad) == DSA_ERR_INVALID_DIM && !writes);
    bad = c; bad.input_offset = -128;
    assert(dsa_conv_s8_execute(&bad) == DSA_ERR_INVALID_DIM && !writes);
    bad = c; bad.multiplier_base |= 1;
    assert(dsa_conv_s8_execute(&bad) == DSA_ERR_INVALID_DIM && !writes);
    bad = c; bad.output_base = 0xffffffc0u;
    assert(dsa_conv_s8_execute(&bad) == DSA_ERR_INVALID_DIM && !writes);
    bad = c; bad.kernel_h = bad.kernel_w = 65535;
    assert(dsa_conv_s8_execute(&bad) == DSA_ERR_INVALID_DIM && !writes);
    bad = c; bad.dataflow_mode = 2;
    assert(dsa_conv_s8_execute(&bad) == DSA_ERR_INVALID_DIM && !writes);
    /* Existing GEMM must clear Conv/bypass mode on a following command. */
    reset_mock();
    assert(dsa_conv_s8_execute(&c) == DSA_SUCCESS);
    dsa_matmul_config_t gemm;
    dsa_matmul_config_init(&gemm);
#ifdef TEST_NMSIS
    gemm.lhs_ptr = (const void *)(uintptr_t)0x1000;
    gemm.rhs_ptr = (const void *)(uintptr_t)0x2000;
    gemm.dst_ptr = (void *)(uintptr_t)0x3000;
#else
    gemm.lhs_ptr = 0x1000; gemm.rhs_ptr = 0x2000; gemm.dst_ptr = 0x3000;
#endif
    gemm.K = 3; gemm.N = 5; gemm.M = 7;
    gemm.lhs_row_stride = gemm.rhs_row_stride = gemm.dst_row_stride = 8;
    gemm.dataflow_mode = DSA_DATAFLOW_IS;
    assert(dsa_matmul_execute(&gemm) == DSA_SUCCESS && starts == 2);
    assert((snapshots[1][NPU_REG_CTRL/4] & (NPU_CTRL_HW_CONV | NPU_CTRL_CONV_BYPASS)) == 0);
    puts("CONV_MMIO_DRIVER_PASS (register protocol; not RTL execution)");
}

#ifdef TEST_NMSIS
static void *page(int prot)
{
    void *p = mmap(NULL, 4096, prot, MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    assert(p != MAP_FAILED && (uintptr_t)p <= UINT32_MAX - 4096u);
    return p;
}
static void test_dispatch(void)
{
    int8_t *input = page(PROT_NONE), *filter = page(PROT_NONE), *output = page(PROT_NONE);
    int32_t *mult = page(PROT_READ | PROT_WRITE), *shift = page(PROT_READ | PROT_WRITE);
    int32_t *bias = page(PROT_READ | PROT_WRITE);
    nmsis_nn_dims in = {2,3,4,6}, f = {1,3,2,2}, out = {2,3,4,9}, bd = {1,1,1,9};
    nmsis_nn_conv_params p = {0};
    nmsis_nn_per_channel_quant_params q = {mult, shift};
    riscv_nmsis_nn_status status;
    p.stride.h = p.stride.w = p.dilation.h = p.dilation.w = 1;
    p.padding.h = p.padding.w = 1; p.input_offset = 17; p.output_offset = -3;
    p.activation.min = -120; p.activation.max = 120;
    for (unsigned i=0;i<9;++i) { mult[i]=1073741824; shift[i]=-3; bias[i]=(int)i-4; }
    reset_mock();
    /* PROT_NONE activation/filter/output and NULL scratch guarantee that the
     * real CPU call path cannot read windows, multiply data, or write output. */
    assert(riscv_convolve_wrapper_s8_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS);
    assert(starts == 6);
    for (unsigned b=0;b<2;++b) for(unsigned g=0;g<3;++g) {
        uint32_t *r = snapshots[b*3+g];
        assert(r[NPU_REG_CONV_INPUT_BASE/4] == (uintptr_t)input + b*72u);
        assert(r[NPU_REG_RHS_BASE/4] == (uintptr_t)filter + g*36u);
        assert(r[NPU_REG_DST_BASE/4] == (uintptr_t)output + b*108u + g*3u);
        assert(r[NPU_REG_BIAS_BASE/4] == (uintptr_t)bias + g*12u);
        assert(r[NPU_REG_Q_MULT/4] == (uintptr_t)mult + g*12u);
        assert(r[NPU_REG_Q_SHIFT/4] == (uintptr_t)shift + g*12u);
        assert(r[NPU_REG_CONV_GROUP_OFFSET/4] == g*2u);
        assert(r[NPU_REG_N/4] == 12 && r[NPU_REG_K/4] == 12 && r[NPU_REG_M/4] == 3);
        assert(r[NPU_REG_DST_STRIDE_B/4] == 9);
    }
    reset_mock();
    assert(riscv_convolve_s8(NULL,&p,&q,&in,input,&f,filter,&bd,NULL,NULL,&out,output) == RISCV_NMSIS_NN_SUCCESS);
    assert(starts == 6 && regs[NPU_REG_BIAS_BASE/4] == 0);
    reset_mock();
    assert(riscv_convolve_s8_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,NULL,&out,output) == RISCV_NMSIS_NN_SUCCESS && starts == 6);
    reset_mock(); error_mode = 1;
    assert(riscv_convolve_wrapper_s8_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_NO_IMPL_ERROR && starts == 1);
    reset_mock(); error_mode = 2;
    assert(riscv_convolve_wrapper_s8_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_NO_IMPL_ERROR && starts == 1 && active);
    reset_mock(); busy_before = 1;
    assert(riscv_convolve_wrapper_s8_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_NO_IMPL_ERROR && starts == 0);
    reset_mock(); caps = 0;
    assert(riscv_convolve_s8_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,NULL,&out,output) == RISCV_NMSIS_NN_ARG_ERROR && !starts);
    reset_mock(); shift[0] = 30;
    assert(!riscv_convolve_s8_try_dsa(&p,&q,&in,input,&f,filter,bias,NULL,&out,output,&status) && !starts);
    shift[0] = -3;
    reset_mock(); f.c = 0;
    assert(riscv_convolve_s8_try_dsa(&p,&q,&in,input,&f,filter,bias,NULL,&out,output,&status) && status == RISCV_NMSIS_NN_ARG_ERROR && !starts);
    f.c = 2;
    reset_mock(); in.h = 65536;
    assert(!riscv_convolve_s8_try_dsa(&p,&q,&in,input,&f,filter,bias,NULL,&out,output,&status) && !starts && !writes);
    in.h = 3; p.stride.h = 65536;
    assert(!riscv_convolve_s8_try_dsa(&p,&q,&in,input,&f,filter,bias,NULL,&out,output,&status) && !starts && !writes);
    p.stride.h = 1; p.padding.w = 65536;
    assert(!riscv_convolve_s8_try_dsa(&p,&q,&in,input,&f,filter,bias,NULL,&out,output,&status) && !starts && !writes);
    p.padding.w = 1;
    /* 1x1/direct fast/direct 1xN and standard wrapper all share the probe. */
    in.n = out.n = 1; in.h = out.h = 1; in.c = f.c = 4; out.c = 3;
    f.h = f.w = 1; p.padding.h = p.padding.w = 0;
    reset_mock();
    assert(riscv_convolve_1x1_s8(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS && starts == 1);
    reset_mock();
    assert(riscv_convolve_1x1_s8_fast(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS && starts == 1);
    reset_mock();
    assert(riscv_convolve_1x1_s8_fast_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS && starts == 1);
    reset_mock();
    assert(riscv_convolve_1x1_s8_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS && starts == 1);
    reset_mock();
    assert(riscv_convolve_1_x_n_s8(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS && starts == 1);
    reset_mock();
    assert(riscv_convolve_wrapper_s8(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS && starts == 1);
    /* Real NMSIS software fallback when capability is absent. */
    assert(mprotect(input,4096,PROT_READ|PROT_WRITE)==0);
    assert(mprotect(filter,4096,PROT_READ|PROT_WRITE)==0);
    assert(mprotect(output,4096,PROT_READ|PROT_WRITE)==0);
    in.w = out.w = 1; in.c = f.c = 2; out.c = 1;
    input[0] = 3; input[1] = -2; filter[0] = 4; filter[1] = -1;
    bias[0] = 2; mult[0] = 1073741824; shift[0] = 0;
    p.input_offset = 0; p.output_offset = 0;
    reset_mock(); caps = 0;
    assert(riscv_convolve_wrapper_s8_acc(NULL,&p,&q,&in,input,&f,filter,&bd,bias,&out,output) == RISCV_NMSIS_NN_SUCCESS);
    assert(output[0] == 8 && !starts && !writes);
    for (unsigned i=0;i<6;++i) {
        void *ptrs[] = {input,filter,output,mult,shift,bias};
        assert(munmap(ptrs[i],4096)==0);
    }
    puts("NMSIS_CONV_DISPATCH_PASS (PROT_NONE input/filter/output, NULL scratch, real CPU entry points)");
}
#endif
int main(void)
{
    test_low_level();
#ifdef TEST_NMSIS
    test_dispatch();
#endif
    return 0;
}
