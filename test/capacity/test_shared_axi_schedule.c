/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "dsa_schedule.h"

typedef struct {
    uint32_t bits,max_bytes,channels,lhs_address,rhs_address;
    uint64_t read_beats,read_requests,write_beats,long_writes,long_cycles,frame_cycles;
} transfer_case_t;

static dsa_schedule_config_t configuration(const transfer_case_t *test)
{
    dsa_schedule_config_t c;
    dsa_schedule_init(&c,16u,32u,test->channels,16u,4u,16u);
    c.axi_data_bits=test->bits;c.dma_max_bytes=test->max_bytes;
    c.lhs_address=test->lhs_address;c.rhs_address=test->rhs_address;
    c.flow=DSA_SCHEDULE_WS;c.requested_r=1u;c.requested_w=2u;
    c.ps_caps=(1u<<24)|(16u<<16)|23u;
    c.ps_pool_bytes=12288u;c.ia_cache_bytes=2048u;
    c.shared_total_bytes=14336u;c.shared_bank_bytes=2048u;
    c.shared_ia_bank_mask=1u<<1;c.ps_directory_rows=1024u;
    c.source_s8=1u;c.compact_mode_mask=3u;c.force_raw=1u;
    c.rhs_tile_packed=1u;c.has_bias=c.per_channel=1u;
    c.read_beat_cycles=2u;c.write_beat_cycles=1u;
    c.read_request_cycles=1u;c.write_request_cycles=3u;
    return c;
}

static dsa_schedule_t score(const dsa_schedule_config_t *c,uint32_t frame)
{
    gempact_device_request_t q={0};
    gempact_dispatch_t p;
    dsa_schedule_t result;
    uint64_t a_words,a_reads,b_words,b_reads;
    q.rows=c->rows;q.reduction=c->depth;q.cols=c->cols;q.size=16u;
    q.frames=16u;q.ia_bytes=2048u;q.pool_bytes=12288u;
    q.ia_bank_count=1u;q.ps_bank_count=6u;q.directory_rows=1024u;
    q.mode=DSA_SCHEDULE_WS;q.is_supported=1u;q.per_channel=1u;
    q.lhs_element_bytes=1u;q.compact_mode_mask=3u;q.frame_capable=1u;
    q.estimated_record_bytes=32u;q.literal_record_bytes=48u;
    q.micro_setup_cycles=64u;
    assert(gempact_device_candidate(&q,DSA_SCHEDULE_WS,1u,2u,frame,1u,&p));
    assert(((p.ps_control&DSA_PS_CTRL_FRAME)!=0u)==frame);
    dsa_schedule_operand(c,c->rows,1u,c->lhs_stride,c->lhs_address,1,0,&a_words,&a_reads);
    dsa_schedule_operand(c,c->cols,1u,c->rhs_stride,c->rhs_address,1,1,&b_words,&b_reads);
    dsa_schedule_memory_score(c,&q,&p,a_words,a_reads,b_words,b_reads,&result);
    return result;
}

static uint32_t quantization_groups(void)
{
    /* Each row gives complete long-path setup costs for WS and IS. The
     * two 64-channel shapes require four and eight WS parameter groups;
     * each IS plan retains one 64-channel parameter group. */
    const uint32_t cases[][7]={
        {64u,784u,64u,32u,1u,592u,586u},
        {64u,784u,64u,64u,1u,496u,490u},
        {125u,64u,64u,64u,1u,240u,162u},
        {125u,64u,64u,64u,2u,400u,258u},
    };
    uint32_t checked=0u;
    for (uint32_t i=0u;i<sizeof(cases)/sizeof(cases[0]);++i) {
        dsa_schedule_config_t c;
        dsa_schedule_init(&c,cases[i][0],cases[i][1],cases[i][2],16u,4u,16u);
        c.axi_data_bits=cases[i][3];c.read_beat_cycles=cases[i][4];
        c.per_channel=1u;c.rhs_tile_packed=1u;
        for (uint32_t mode=0u;mode<2u;++mode) {
            gempact_dispatch_t p={0};
            p.is_mode=mode;p.tiling.ia_reuse=4u;p.tiling.w_reuse=4u;
            p.tiling.row_groups=mode?1u:(c.rows+63u)/64u;
            p.tiling.col_groups=mode?(c.rows+63u)/64u:1u;
            assert(dsa_schedule_loader_cost(&c,&p)==cases[i][5u+mode]);
            ++checked;
            p.ps_control=DSA_PS_CTRL_FRAME;
            assert(dsa_schedule_loader_cost(&c,&p)==0u);
            ++checked;
        }
        c.per_channel=0u;
        gempact_dispatch_t p={0};
        p.tiling.ia_reuse=4u;p.tiling.w_reuse=4u;p.tiling.col_groups=1u;
        assert(dsa_schedule_loader_cost(&c,&p)==(i<2u?392u:64u));
        ++checked;
    }
    return checked;
}

int main(void)
{
#ifdef TEST_EXPECT_AXI_DATA_BITS
    dsa_schedule_config_t defaults;
    dsa_schedule_init(&defaults,1u,16u,16u,16u,4u,16u);
    assert(defaults.axi_data_bits==TEST_EXPECT_AXI_DATA_BITS);
    assert(defaults.dma_max_bytes==256u*(TEST_EXPECT_AXI_DATA_BITS/8u));
#endif
    /* A holds 512 B. A 32-channel B holds 1,024 B, three parameter vectors
     * hold 384 B, and C holds 512 B. Long setup costs four IA control
     * cycles, four parameter-group control cycles, and 512 B of initial
     * stationary and complete quantization transfers. Frame
     * scores include four 64-cycle commands and serial output service. */
    const transfer_case_t cases[]={
        {32u,1024u,32u,0u,0u,480u,42u,128u,1u,1266u,1482u},
        {64u,2048u,32u,0u,0u,240u,42u,64u,1u,658u,938u},
        {64u,64u,32u,0u,0u,240u,54u,64u,8u,670u,950u},
        {64u,8u,32u,0u,0u,240u,240u,64u,64u,856u,1232u},
        {64u,2048u,32u,4u,0u,272u,42u,64u,1u,722u,1002u},
        {64u,2048u,32u,0u,4u,304u,102u,64u,1u,846u,1126u},
        {64u,2048u,17u,0u,0u,159u,42u,76u,32u,468u,788u},
    };
    uint32_t checked=0u,rejected=0u;
    for (uint32_t i=0u;i<sizeof(cases)/sizeof(cases[0]);++i) {
        dsa_schedule_config_t c=configuration(&cases[i]);
        for (uint32_t frame=0u;frame<2u;++frame) {
            dsa_schedule_t p=score(&c,frame);
            uint64_t writes=frame?(cases[i].max_bytes==8u?64u:32u):cases[i].long_writes;
            assert(p.read_beats==cases[i].read_beats && p.read_requests==cases[i].read_requests);
            assert(p.write_beats==cases[i].write_beats && p.write_requests==writes);
            assert(p.read_words==p.read_beats*(c.axi_data_bits/32u));
            assert(p.write_words==p.write_beats*(c.axi_data_bits/32u));
            assert(p.compute_cycles==200u);
            assert(p.estimated_cycles==(frame?cases[i].frame_cycles:cases[i].long_cycles));
            ++checked;
        }
    }
    const uint32_t invalid[][2]={{16u,64u},{128u,2048u},{64u,4u},
        {64u,4096u},{32u,2048u},{64u,96u}};
    for (uint32_t i=0u;i<sizeof(invalid)/sizeof(invalid[0]);++i) {
        dsa_schedule_config_t c=configuration(&cases[0]);
        dsa_schedule_t p;
        c.axi_data_bits=invalid[i][0];c.dma_max_bytes=invalid[i][1];
        assert(!dsa_schedule_plan(&c,&p));
        ++rejected;
    }
    uint32_t group_checks=quantization_groups();
    printf("SHARED_AXI_SCHEDULE_PASS transfer_cases=%u invalid_bus_configs=%u quant_group_checks=%u\n",
        checked,rejected,group_checks);
    return 0;
}
