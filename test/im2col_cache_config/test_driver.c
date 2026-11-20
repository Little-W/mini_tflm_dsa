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
static uint32_t bus_bits=64u;
static uint32_t cache_reads, query_checks, plan_checks, footprint_checks, address_checks, image_checks;

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
    case NPU_REG_DMA_MAX_BYTES:return 256u*(bus_bits/8u);
    case NPU_REG_AXI_DATA_BITS:return bus_bits;
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

/* 从实际像素字节地址求物理行，用独立散列表排除重复读取。
 * 大像素按空间位置索引缓存组，小像素按同一物理行共用缓存组。 */
static void reference_footprints(const dsa_schedule_config_t *c,uint32_t expected[65])
{
    const uint32_t line_bytes=DSA_IM2COL_CACHE_LINE_BYTES;
    const uint32_t sets=c->im2col.cache_bytes/(2u*line_bytes);
    const uint64_t pixel_bytes=(uint64_t)c->im2col.input_channels*c->im2col.source_bytes;
    uint32_t counts[2048]={0},peak=0u;
    uint64_t physical_lines[2048];
    uint32_t points=c->rows<1024u?c->rows:1024u;
    memset(expected,0,65u*sizeof(*expected));
    if(!c->im2col_input_width || !c->im2col_output_width || !c->im2col_stride_h ||
       c->im2col.group_channels<16u || !pixel_bytes || c->lhs_address%line_bytes ||
       sets<2u || sets>2048u || (sets&(sets-1u))) return;
    if(pixel_bytes>=line_bytes) {
        if(pixel_bytes%line_bytes) return;
    } else if(line_bytes%pixel_bytes || (pixel_bytes&(pixel_bytes-1u))) return;
    for(uint32_t i=0u;i<2048u;++i)physical_lines[i]=UINT64_MAX;
    for(uint32_t position=0u;position<points;++position) {
        uint64_t x=(uint64_t)(position%c->im2col_output_width)*c->im2col.stride_w;
        uint64_t y=(uint64_t)(position/c->im2col_output_width)*c->im2col_stride_h;
        uint64_t pixel=y*c->im2col_input_width+x;
        uint64_t line=((uint64_t)c->lhs_address+pixel*pixel_bytes)/line_bytes;
        uint32_t bucket=(uint32_t)(line^(line>>11))%2048u;
        while(physical_lines[bucket]!=UINT64_MAX && physical_lines[bucket]!=line)
            bucket=(bucket+1u)%2048u;
        if(physical_lines[bucket]==UINT64_MAX) {
            uint32_t set=(uint32_t)((pixel_bytes>=line_bytes?pixel:
                pixel*pixel_bytes/line_bytes)%sets);
            physical_lines[bucket]=line;
            if(++counts[set]>peak)peak=counts[set];
        }
        expected[(position+16u)/16u]=peak*sets*line_bytes;
    }
    for(uint32_t i=(points+15u)/16u+1u;i<=64u;++i)
        expected[i]=peak*sets*line_bytes;
}

static void check_footprints(void)
{
    const uint32_t widths[]={7u,14u,16u,31u,64u};
    const uint32_t channels[]={16u,32u,64u,128u,256u};
    for(uint32_t bytes=512u;bytes<=65536u;bytes*=2u)
        for(uint32_t w=0u;w<5u;++w)
            for(uint32_t stride=1u;stride<=3u;++stride)
                for(uint32_t type=1u;type<=2u;++type)
                    for(uint32_t channel=0u;channel<5u;++channel)
                    for(uint32_t rows=1u;rows<=1024u;rows=rows==1u?37u:rows==37u?1024u:1025u) {
                        dsa_schedule_config_t c={0};
                        uint32_t actual[65],expected[65];
                        c.rows=rows;c.im2col.cache_bytes=bytes;c.im2col.source_bytes=type;
                        c.lhs_address=0x10000u;
                        c.im2col.group_channels=c.im2col.input_channels=channels[channel];
                        c.im2col_input_width=(widths[w]-1u)*stride+3u;
                        c.im2col_output_width=widths[w];
                        c.im2col_stride_h=stride;c.im2col.stride_w=stride;
                        reference_footprints(&c,expected);
                        dsa_schedule_window_footprints(&c,actual);
                        assert(memcmp(actual,expected,sizeof(actual))==0);
                        ++footprint_checks;
                    }
    /* 小通道、非二次幂像素和行内起始地址使用通用容量估算。 */
    const uint32_t fallback_channels[]={0u,3u,8u,24u,48u,96u};
    for(uint32_t i=0u;i<sizeof(fallback_channels)/sizeof(fallback_channels[0]);++i) {
        dsa_schedule_config_t c={0};
        uint32_t actual[65],expected[65];
        c.rows=64u;c.im2col.cache_bytes=8192u;c.im2col.source_bytes=1u;
        c.im2col.group_channels=c.im2col.input_channels=fallback_channels[i];
        c.im2col_input_width=9u;c.im2col_output_width=7u;
        c.im2col_stride_h=c.im2col.stride_w=1u;c.lhs_address=0x10000u;
        reference_footprints(&c,expected);dsa_schedule_window_footprints(&c,actual);
        assert(memcmp(actual,expected,sizeof(actual))==0);
        for(uint32_t j=0u;j<=64u;++j)assert(actual[j]==0u);
        ++footprint_checks;
    }
    for(uint32_t offset=0u;offset<DSA_IM2COL_CACHE_LINE_BYTES;offset+=8u) {
        dsa_schedule_config_t c={0};
        uint32_t actual[65],expected[65];
        c.rows=64u;c.im2col.cache_bytes=8192u;c.im2col.source_bytes=1u;
        c.im2col.group_channels=c.im2col.input_channels=16u;
        c.im2col_input_width=9u;c.im2col_output_width=7u;
        c.im2col_stride_h=c.im2col.stride_w=1u;c.lhs_address=0x10000u+offset;
        reference_footprints(&c,expected);dsa_schedule_window_footprints(&c,actual);
        assert(memcmp(actual,expected,sizeof(actual))==0);
        if(offset)for(uint32_t j=0u;j<=64u;++j)assert(actual[j]==0u);
        ++footprint_checks;
    }
}

static void check_address_plans(void)
{
    dsa_conv_s8_config_t c={0};
    const uint32_t addresses[]={0x10000u,0x10008u};
    c.input_h=c.input_w=32u;c.input_c=c.group_c=16u;
    c.kernel_h=c.kernel_w=3u;c.output_h=c.output_w=30u;
    c.output_channels=32u;c.stride_h=c.stride_w=1u;
    c.dilation_h=c.dilation_w=1u;c.dataflow_mode=DSA_DATAFLOW_AUTO;
    c.filter_base=0x20000u;c.output_base=0x30000u;
    c.multiplier_base=0x40000u;c.shift_base=0x41000u;c.dst_row_stride=32u;
    for(bus_bits=32u;bus_bits<=64u;bus_bits*=2u) {
        dsa_matrix_limits_t limits;
        dsa_schedule_t independent[2],planned;
        cache_bytes=8192u;dsa_matrix_query(&limits);
        assert(limits.axi_data_bits==bus_bits);
        assert((addresses[0]%(bus_bits/8u))==(addresses[1]%(bus_bits/8u)));
        for(uint32_t i=0u;i<2u;++i) {
            memset(dsa_schedule_cache,0,sizeof(dsa_schedule_cache));dsa_schedule_cache_next=0u;
            c.input_base=addresses[i];
            assert(dsa_conv_plan_with_ps_bound(&c,&limits,1u,48u,&independent[i])==DSA_SUCCESS);
        }
        for(uint32_t first=0u;first<2u;++first) {
            memset(dsa_schedule_cache,0,sizeof(dsa_schedule_cache));dsa_schedule_cache_next=0u;
            for(uint32_t step=0u;step<4u;++step) {
                uint32_t i=(first+step)%2u;
                c.input_base=addresses[i];
                assert(dsa_conv_plan_with_ps_bound(&c,&limits,1u,48u,&planned)==DSA_SUCCESS);
                assert(memcmp(&planned,&independent[i],sizeof(planned))==0);
                assert(dsa_schedule_cache_next==(step?2u:1u));
                ++address_checks;
            }
            /* 相差完整缓存行且地址余数相同的图像继续复用已有计划。 */
            for(uint32_t i=0u;i<2u;++i) {
                c.input_base=addresses[i]+DSA_IM2COL_CACHE_LINE_BYTES;
                assert(dsa_conv_plan_with_ps_bound(&c,&limits,1u,48u,&planned)==DSA_SUCCESS);
                assert(memcmp(&planned,&independent[i],sizeof(planned))==0);
                assert(dsa_schedule_cache_next==2u);
                ++address_checks;
            }
        }
    }
    bus_bits=64u;
}

static void check_image_costs(void)
{
    /* 一行、256个归约元素包含16条描述符；控制时间为16×4个周期。
     * 表中元素生成时间根据实际并行度独立计算，并检查两种数据流方向。 */
    const uint32_t cases[][6]={
        {32u,1u,1u,DSA_SCHEDULE_WS,256u,80u},
        {64u,1u,1u,DSA_SCHEDULE_WS,256u,80u},
        {32u,1u,0u,DSA_SCHEDULE_WS,256u,128u},
        {64u,1u,0u,DSA_SCHEDULE_WS,256u,96u},
        {32u,2u,1u,DSA_SCHEDULE_WS,256u,96u},
        {64u,2u,1u,DSA_SCHEDULE_WS,256u,96u},
        {32u,2u,0u,DSA_SCHEDULE_WS,256u,128u},
        {64u,2u,0u,DSA_SCHEDULE_WS,256u,96u},
        {32u,1u,0u,DSA_SCHEDULE_IS,512u,160u},
        {64u,1u,0u,DSA_SCHEDULE_IS,512u,160u},
        {32u,2u,0u,DSA_SCHEDULE_IS,512u,192u},
        {64u,2u,0u,DSA_SCHEDULE_IS,512u,192u},
    };
    for(uint32_t i=0u;i<sizeof(cases)/sizeof(cases[0]);++i) {
        dsa_schedule_config_t c;
        gempact_device_request_t q={0};
        gempact_dispatch_t p={0};
        dsa_schedule_init(&c,1u,256u,32u,16u,4u,16u);
        c.axi_data_bits=cases[i][0];
        q.rows=1u;q.reduction=256u;q.cols=32u;q.size=16u;
        q.im2col_source_bytes=cases[i][1];q.im2col_pixel_channels=16u;
        q.im2col_stage_bytes_per_position=16u*cases[i][1];
        q.im2col_base_fraction_q8=256u;q.im2col_cache_bytes=8192u;
        q.compact_mode_mask=cases[i][2]?3u:0u;
        p.is_mode=cases[i][3];p.tiling.ia_reuse=p.tiling.w_reuse=1u;
        p.slice_rows=1u;
        uint64_t stream=p.is_mode?16u:cases[i][4];
        uint64_t stationary=p.is_mode?cases[i][4]:16u;
        assert(dsa_schedule_image_cost(&c,&q,&p,0,stream,stationary)==cases[i][5]);
        ++image_checks;
    }
    /* 两个维度各有一个尾块，17×17需要四条独立描述符。 */
    for(uint32_t source_bytes=1u;source_bytes<=2u;++source_bytes) {
        dsa_schedule_config_t c;
        gempact_device_request_t q={0};
        gempact_dispatch_t p={0};
        dsa_schedule_init(&c,17u,17u,16u,16u,4u,16u);c.axi_data_bits=64u;
        q.rows=17u;q.reduction=17u;q.cols=16u;q.size=16u;q.compact_mode_mask=3u;
        q.im2col_source_bytes=source_bytes;q.im2col_pixel_channels=16u;
        q.im2col_stage_bytes_per_position=16u*source_bytes;
        q.im2col_base_fraction_q8=256u;q.im2col_cache_bytes=8192u;
        p.tiling.ia_reuse=p.tiling.w_reuse=1u;p.slice_rows=16u;
        assert(dsa_schedule_image_cost(&c,&q,&p,0,289u,1u)==(source_bytes==1u?35u:53u));
        assert(dsa_schedule_image_cost(&c,&q,&p,0,0u,0u)==0u);
        image_checks+=2u;
    }
    /* 隔离旁路输入流量：两次256元素遍历，逐16字节原始字读取。 */
    for(uint32_t bits=32u;bits<=64u;bits*=2u)
        for(uint32_t source_bytes=1u;source_bytes<=2u;++source_bytes) {
            dsa_schedule_config_t c;
            gempact_device_request_t q={0};
            gempact_dispatch_t p={0};
            dsa_schedule_t result;
            dsa_schedule_init(&c,1u,256u,32u,16u,4u,16u);
            c.axi_data_bits=bits;c.spatial=1u;
            c.im2col.input_bytes=256u*source_bytes;c.im2col.source_bytes=source_bytes;
            c.im2col.cache_bytes=0u;
            q.rows=1u;q.reduction=256u;q.cols=32u;q.size=16u;q.compact_mode_mask=3u;
            q.im2col_source_bytes=source_bytes;q.im2col_pixel_channels=16u;
            q.im2col_stage_bytes_per_position=16u*source_bytes;
            q.im2col_base_fraction_q8=0u;q.im2col_cache_bytes=0u;
            p.tiling.ia_reuse=p.tiling.w_reuse=p.tiling.row_groups=1u;
            p.tiling.col_groups=2u;p.slice_rows=1u;
            dsa_schedule_memory_score_work(&c,&q,&p,0u,0u,0u,0u,0,512u,8192u,&result);
            assert(result.read_requests==32u*source_bytes);
            assert(result.read_beats==(bits==32u?128u:64u)*source_bytes);
            assert(result.read_words==128u*source_bytes);
            assert(dsa_schedule_image_cost(&c,&q,&p,0,512u,8192u)==
                (source_bytes==1u?160u:192u));
            ++image_checks;
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
    check_plans();check_footprints();check_address_plans();check_image_costs();
    printf("IM2COL_DRIVER_PASS fallback=%u query_checks=%u plans=%u footprints=%u address_plans=%u image_costs=%u\n",
           DSA_IM2COL_CACHE_BYTES,query_checks,plan_checks,footprint_checks,address_checks,image_checks);
    return 0;
}
