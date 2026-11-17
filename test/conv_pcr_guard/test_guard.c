/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "dsa_accel.h"
#include "gempact_tiling.h"
#ifdef TEST_NMSIS
#include <sys/mman.h>
#include <string.h>
#include "riscv_nnfunctions.h"
#endif

static unsigned reads, writes, starts, conv_available, active;

void dsa_mmio_write(uint32_t address, uint32_t value)
{
    ++writes;
    if (address == DSA_MMIO_BASE + NPU_REG_CTRL && (value & 1u)) {++starts;active=1u;}
    if (address == DSA_MMIO_BASE + NPU_REG_STATUS) active=0u;
}

uint32_t dsa_mmio_read(uint32_t address)
{
    ++reads;
    if (address == DSA_MMIO_BASE + NPU_REG_ID) return 0x4e505531u;
    if (address == DSA_MMIO_BASE + NPU_REG_CONFIG_ABI) return 2u;
    if (address == DSA_MMIO_BASE + NPU_REG_CONV_CAPS)
        return conv_available ? (DSA_CONV_CAP_VERSION<<16)|7u : 0u;
    if (address == DSA_MMIO_BASE + NPU_REG_STATUS) return active?5u:1u;
    if (address == DSA_MMIO_BASE + NPU_REG_MATRIX_CAPS) return (16u<<24)|(8u<<16)|(4u<<8)|7u;
    if (address == DSA_MMIO_BASE + NPU_REG_PS_CAPS) return (1u<<24)|(8u<<16)|7u;
    if (address == DSA_MMIO_BASE + NPU_REG_PS_POOL_BYTES) return 12288u;
    if (address == DSA_MMIO_BASE + NPU_REG_IA_CACHE_BYTES) return 2048u;
    return 0u;
}

static void low_level(void)
{
    dsa_conv_s8_config_t c = {0};
    gempact_tiling_t tiling;
    c.input_base = 0x10000; c.filter_base = 0x20000; c.output_base = 0x30000;
    c.bias_base = 0x40000; c.multiplier_base = 0x50000; c.shift_base = 0x60000;
    c.input_h = c.output_h = 1; c.input_w = c.output_w = 16;
    c.input_c = c.group_c = c.output_channels = c.dst_row_stride = 16;
    c.kernel_h = c.kernel_w = c.stride_h = c.stride_w = 1;
    c.dilation_h = c.dilation_w = 1;
    c.input_offset = 17; c.activation_min = -128; c.activation_max = 127;
    for (unsigned available=0u;available<2u;++available)
    for (unsigned mode=0u;mode<2u;++mode) {
        uint32_t validated,executed;
        conv_available=available;c.dataflow_mode=mode;
        reads=writes=starts=active=0u;
        assert(gempact_plan_capacity(16,16,16,4,8,0,0,mode,1,
                                    DSA_PS_POOL_BYTES,&tiling,0));
        validated=dsa_conv_s8_validate(&c);
        executed=dsa_conv_s8_execute(&c);
        assert(validated==DSA_SUCCESS);
        if (available) assert(executed==DSA_SUCCESS && starts==1u && writes>0u);
        else assert(executed==DSA_ERR_UNSUPPORTED && reads==3u && writes==0u && starts==0u);
        printf("CONV_CAPABILITY_CASE available=%u mode=%u validate=%u execute=%u reads=%u writes=%u starts=%u\n",
               available,mode,validated,executed,reads,writes,starts);
    }
    conv_available=0u;
}

#ifdef TEST_NMSIS
extern int cosim_reference(const int8_t *,const int8_t *,const int32_t *,
    const int32_t *,const int32_t *,const nmsis_nn_dims *,const nmsis_nn_dims *,
    const nmsis_nn_dims *,const nmsis_nn_conv_params *,int8_t *);

static void nmsis_fallback(void)
{
    unsigned char *page = mmap(NULL,4096,PROT_NONE,
                               MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0);
    assert(page != MAP_FAILED && (uintptr_t)page <= UINT32_MAX - 4096u);
    int8_t *input = (int8_t *)page, *filter = (int8_t *)page + 512;
    int32_t *mult = (int32_t *)(page + 1024), *shift = (int32_t *)(page + 1088);
    int32_t *bias = (int32_t *)(page + 1152);
    int8_t *output = (int8_t *)page + 1280;
    nmsis_nn_dims in = {1,1,16,16}, f = {16,1,1,16}, out = {1,1,16,16};
    nmsis_nn_dims bd = {1,1,1,16};
    nmsis_nn_conv_params p = {0};
    nmsis_nn_per_channel_quant_params q = {mult,shift};
    riscv_nmsis_nn_status status;
    p.stride.h = p.stride.w = p.dilation.h = p.dilation.w = 1;
    p.input_offset = 17; p.output_offset = -3;
    p.activation.min = -120; p.activation.max = 110;
    reads = writes = starts = 0;
    /* Input, filter, result, bias and quant arrays are all unreadable. A valid
     * unsupported shape must return not-handled before inspecting them. */
    assert(riscv_convolve_s8_try_dsa(&p,&q,&in,input,&f,filter,bias,NULL,
                                    &out,output,&status) == 0);
    assert(reads == 3);
    assert(writes == 0 && starts == 0);
    printf("PROBE_FALLBACK_PASS guarded_tensors=6 reads=%u writes=%u starts=%u\n",reads,writes,starts);

    assert(mprotect(page,4096,PROT_READ|PROT_WRITE) == 0);
    memset(page,0,4096);
    in = (nmsis_nn_dims){1,3,3,1}; f = (nmsis_nn_dims){2,2,2,1};
    out = (nmsis_nn_dims){1,2,2,2}; bd.c = 2;
    const int8_t weights[8] = {1,-1,2,1,-2,1,1,2};
    for (unsigned i=0;i<9;++i) input[i]=(int8_t)((int)i-4);
    memcpy(filter,weights,sizeof weights);
    bias[0]=3; bias[1]=-5; mult[0]=1073741824; mult[1]=1610612736;
    shift[0]=-1; shift[1]=-2;
    int16_t scratch[32]; int8_t golden[8];
    nmsis_nn_context ctx = {scratch,sizeof scratch};
    assert(cosim_reference(input,filter,bias,mult,shift,&in,&f,&out,&p,golden) == 0);
    reads = writes = starts = 0;
    status = riscv_convolve_wrapper_s8_acc(&ctx,&p,&q,&in,input,&f,filter,
                                          &bd,bias,&out,output);
    assert(status == RISCV_NMSIS_NN_SUCCESS);
    assert(memcmp(output,golden,sizeof golden) == 0);
    assert(writes == 0 && starts == 0);
    assert(reads == 6);
    printf("NMSIS_SOFTWARE_FALLBACK_PASS outputs=8 status=%d reads=%u writes=%u starts=%u\n",
           status,reads,writes,starts);
    assert(munmap(page,4096) == 0);
}
#endif

int main(void)
{
    low_level();
#ifdef TEST_NMSIS
    nmsis_fallback();
#endif
    printf("CONV_CAPABILITY_PASS compiled_pcr=%u\n",(unsigned)DSA_PCR_ENGINE);
    return 0;
}
