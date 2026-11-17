/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#ifdef TEST_NMSIS
#include "../../drivers/tflm/NMSIS/NN/Source/ExtraAccFunctions/dsa_accel.c"
#else
#include "../../drivers/dsa_accel.c"
#endif

static uint32_t cache_bytes=4096u, valid_id=1u, ps_available=1u;
static uint32_t cache_reads, query_checks, plan_checks, footprint_checks;

void dsa_mmio_write(uint32_t address,uint32_t value)
{
    (void)address;(void)value;
    assert(0);
}

uint32_t dsa_mmio_read(uint32_t address)
{
    switch(address-DSA_MMIO_BASE) {
    case NPU_REG_ID:return valid_id?0x4e505531u:0u;
    case NPU_REG_CONFIG_ABI:return 2u;
    case NPU_REG_MATRIX_CAPS:return (16u<<24)|(16u<<16)|(4u<<8)|7u;
    case NPU_REG_MATRIX_PS_ROWS:return 0u;
    case NPU_REG_MATRIX_OUTPUT_BANKS:return 32u|(4u<<16);
    case NPU_REG_DMA_MAX_BYTES:return 2048u;
    case NPU_REG_AXI_DATA_BITS:return 64u;
    case NPU_REG_IM2COL_CACHE_BYTES:++cache_reads;return cache_bytes;
    case NPU_REG_PS_CAPS:return ps_available?(1u<<24)|(16u<<16)|0x37u:0u;
    case NPU_REG_PS_POOL_BYTES:return 12288u;
    case NPU_REG_IA_CACHE_BYTES:return 2048u;
    case NPU_REG_SHARED_TOTAL_BYTES:return 14336u;
    case NPU_REG_SHARED_BANK_BYTES:return 2048u;
    case NPU_REG_IA_BANK_MASK:return 0x16u;
    case NPU_REG_PS_DIRECTORY_ROWS:return 1024u;
    default:return 0u;
    }
}

static void check_query(uint32_t bytes,uint32_t expected)
{
    dsa_matrix_limits_t limits;
    cache_bytes=bytes;
    uint32_t before=cache_reads;
    dsa_matrix_query(&limits);
    assert(limits.im2col_cache_bytes==expected);
    assert(cache_reads-before==valid_id);
    ++query_checks;
}

static void check_plans(void)
{
    dsa_conv_s8_config_t c={0};
    c.input_h=c.input_w=32u;c.input_c=c.group_c=16u;
    c.kernel_h=c.kernel_w=3u;c.output_h=c.output_w=30u;
    c.output_channels=16u;c.stride_h=c.stride_w=1u;
    c.dilation_h=c.dilation_w=1u;c.dataflow_mode=DSA_DATAFLOW_AUTO;
    c.input_base=0x10000u;c.filter_base=0x20000u;c.output_base=0x30000u;
    c.multiplier_base=0x40000u;c.shift_base=0x41000u;
    c.dst_row_stride=16u;
    uint64_t first_cost=0u,last_cost=0u;
    for(uint32_t bytes=512u;bytes<=65536u;bytes*=2u) {
        dsa_matrix_limits_t limits;
        dsa_schedule_t first,repeated;
        cache_bytes=bytes;dsa_matrix_query(&limits);
        memset(dsa_schedule_cache,0,sizeof(dsa_schedule_cache));dsa_schedule_cache_next=0u;
        assert(dsa_conv_plan_with_ps_bound(&c,&limits,1u,48u,&first)==DSA_SUCCESS);
        assert(dsa_schedule_cache_next==1u);
        assert(dsa_schedule_cache[0].configuration.im2col.cache_bytes==bytes);
        assert(dsa_conv_plan_with_ps_bound(&c,&limits,1u,48u,&repeated)==DSA_SUCCESS);
        assert(dsa_schedule_cache_next==1u);
        assert(memcmp(&first,&repeated,sizeof(first))==0);
        if(bytes==512u)first_cost=first.estimated_cycles;
        last_cost=first.estimated_cycles;
        c.bypass_cache=1u;
        assert(dsa_conv_plan_with_ps_bound(&c,&limits,1u,48u,&repeated)==DSA_SUCCESS);
        assert(dsa_schedule_cache_next==2u);
        assert(dsa_schedule_cache[1].configuration.im2col.cache_bytes==0u);
        c.bypass_cache=0u;
        ++plan_checks;
    }
    assert(first_cost>last_cost);
}

static void check_footprints(void)
{
    const uint32_t widths[]={7u,14u,16u,31u,64u};
    for(uint32_t bytes=512u;bytes<=65536u;bytes*=2u)
        for(uint32_t w=0u;w<5u;++w)
            for(uint32_t stride=1u;stride<=3u;++stride)
                for(uint32_t type=1u;type<=2u;++type)
                    for(uint32_t rows=1u;rows<=1024u;rows=rows==1u?37u:rows==37u?1024u:1025u) {
                        dsa_schedule_config_t c={0};
                        uint32_t actual[65],expected[65]={0},counts[2048]={0};
                        uint32_t sets=bytes/32u,peak=0u;
                        c.rows=rows;c.im2col.cache_bytes=bytes;c.im2col.source_bytes=type;
                        c.im2col.group_channels=c.im2col.input_channels=16u;
                        c.im2col_input_width=widths[w]+2u;
                        c.im2col_output_width=widths[w];
                        c.im2col_stride_h=stride;c.im2col.stride_w=stride;
                        for(uint32_t p=0u;p<rows;++p) {
                            uint32_t x=(p%widths[w])*stride;
                            uint32_t y=(p/widths[w])*stride;
                            uint32_t index=(y*c.im2col_input_width+x)%sets;
                            if(++counts[index]>peak)peak=counts[index];
                            expected[(p+16u)/16u]=peak*sets*16u*type;
                        }
                        for(uint32_t i=(rows+15u)/16u+1u;i<=64u;++i)
                            expected[i]=peak*sets*16u*type;
                        dsa_schedule_window_footprints(&c,actual);
                        assert(memcmp(actual,expected,sizeof(actual))==0);
                        ++footprint_checks;
                    }
}

int main(void)
{
    for(ps_available=0u;ps_available<=1u;++ps_available)
        for(uint32_t bytes=512u;bytes<=65536u;bytes*=2u)check_query(bytes,bytes);
    ps_available=1u;
    check_query(64u,64u);
    const uint32_t unsupported[]={0u,1u,32u,96u,768u,131072u};
    for(uint32_t i=0u;i<sizeof(unsupported)/sizeof(unsupported[0]);++i)
        check_query(unsupported[i],DSA_IM2COL_CACHE_BYTES);
    valid_id=0u;check_query(16384u,DSA_IM2COL_CACHE_BYTES);valid_id=1u;
    check_plans();check_footprints();
    printf("IM2COL_DRIVER_PASS fallback=%u query_checks=%u plans=%u footprints=%u\n",
           DSA_IM2COL_CACHE_BYTES,query_checks,plan_checks,footprint_checks);
    return 0;
}
