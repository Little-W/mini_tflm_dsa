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

void dsa_mmio_write(uint32_t address,uint32_t value)
{
    (void)address;(void)value;
    assert(0);
}
uint32_t dsa_mmio_read(uint32_t address)
{
    (void)address;
    assert(0);
    return 0u;
}

static uint32_t hits,misses,equivalent;

static dsa_schedule_t cached(const dsa_schedule_config_t *c,uint32_t hit)
{
    uint32_t before=dsa_schedule_cache_next;
    dsa_schedule_t schedule,independent;
    assert(dsa_schedule_cached_plan(c,&schedule));
    assert(dsa_schedule_cache_next==(hit?before:(before+1u)%DSA_PLANNER_CACHE_ENTRIES));
    assert(dsa_schedule_plan(c,&independent));
    assert(memcmp(&schedule,&independent,sizeof(schedule))==0);
    if(hit)++hits;else ++misses;
    ++equivalent;
    return schedule;
}

int main(void)
{
    dsa_schedule_config_t c;
    dsa_schedule_init(&c,16u,16u,32u,16u,4u,16u);
    c.ps_caps=(1u<<24)|(16u<<16)|23u;
    c.ps_pool_bytes=12288u;c.ia_cache_bytes=2048u;
    c.shared_total_bytes=14336u;c.shared_bank_bytes=2048u;
    c.shared_ia_bank_mask=0x16u;c.ps_directory_rows=1024u;
    c.source_s8=1u;c.compact_mode_mask=3u;c.force_raw=1u;
    c.rhs_tile_packed=1u;c.has_bias=c.per_channel=1u;
    c.lhs_address=0x1000u;c.rhs_address=0x2000u;c.output_address=0x3000u;
    cached(&c,0u);
    c.lhs_address+=0x100000u;c.rhs_address+=0x200000u;c.output_address+=0x300000u;
    cached(&c,1u);
    c.rhs_address+=16u;
    cached(&c,1u);
    c.lhs_address+=1u;
    cached(&c,0u);
    c.lhs_address+=0x400000u;
    cached(&c,1u);
    c.rhs_tile_packed=0u;c.rhs_address=0x4001u;
    cached(&c,0u);
    c.rhs_address+=0x100000u;
    cached(&c,1u);
    c.rhs_address+=1u;
    cached(&c,0u);
    c.output_address+=4u;
    cached(&c,0u);
    c.output_address+=4096u;
    cached(&c,1u);
    c.force_raw=0u;
    cached(&c,0u);
    c.force_raw=1u;
    cached(&c,1u);
    c.force_raw=0u;
    cached(&c,1u);

    memset(dsa_schedule_cache,0,sizeof(dsa_schedule_cache));
    dsa_schedule_cache_next=0u;
    c.force_raw=1u;c.lhs_address=c.rhs_address=c.output_address=0u;
    c.rhs_tile_packed=1u;
    dsa_schedule_t aligned=cached(&c,0u);
    c.output_address=4080u;
    dsa_schedule_t crossing=cached(&c,0u);
    assert(aligned.write_requests<crossing.write_requests);
    c.output_address+=0x800000u;
    cached(&c,1u);
    c.lhs_tile_packed=1u;c.lhs_address=0x10000u;
    cached(&c,0u);
    c.lhs_address+=16u;
    cached(&c,1u);

    memset(dsa_schedule_cache,0,sizeof(dsa_schedule_cache));
    dsa_schedule_cache_next=0u;
    c.lhs_tile_packed=c.rhs_tile_packed=0u;
    c.lhs_address=c.rhs_address=c.output_address=0u;
    c.axi_data_bits=64u;c.dma_max_bytes=2048u;
    aligned=cached(&c,0u);
    c.lhs_address=4u;
    dsa_schedule_t unaligned=cached(&c,0u);
    assert(unaligned.read_beats>aligned.read_beats);
    c.lhs_address+=8u;
    cached(&c,1u);
    c.rhs_tile_packed=1u;
    aligned=cached(&c,0u);
    c.rhs_address=4u;
    unaligned=cached(&c,0u);
    assert(unaligned.read_beats>aligned.read_beats);
    c.rhs_address+=8u;
    cached(&c,1u);
    c.lhs_tile_packed=1u;c.lhs_address=0u;
    aligned=cached(&c,0u);
    c.lhs_address=4u;
    unaligned=cached(&c,0u);
    assert(unaligned.read_beats>aligned.read_beats);
    c.lhs_address+=8u;
    cached(&c,1u);
    c.axi_data_bits=32u;c.dma_max_bytes=1024u;
    cached(&c,0u);
    c.axi_data_bits=64u;c.dma_max_bytes=2048u;
    cached(&c,1u);

    memset(dsa_schedule_cache,0,sizeof(dsa_schedule_cache));
    dsa_schedule_cache_next=0u;
    cached(&c,0u);
    c.dma_max_bytes=64u;
    cached(&c,0u);
    ++c.read_beat_cycles;
    cached(&c,0u);
    ++c.write_beat_cycles;
    cached(&c,0u);
    ++c.read_request_cycles;
    cached(&c,0u);
    ++c.write_request_cycles;
    cached(&c,0u);
    c.lhs_address+=0x100000u;c.rhs_address+=0x200000u;
    cached(&c,1u);
    c.shared_bank_bytes=4096u;c.shared_total_bytes=7u*c.shared_bank_bytes;
    dsa_schedule_t small_banks=cached(&c,0u);
    assert(small_banks.ia_cache_bytes+small_banks.ps_pool_bytes==c.shared_total_bytes);
    c.shared_bank_bytes=8192u;c.shared_total_bytes=9u*c.shared_bank_bytes;
    dsa_schedule_t large_banks=cached(&c,0u);
    assert(large_banks.ia_cache_bytes+large_banks.ps_pool_bytes==c.shared_total_bytes);
    c.shared_total_bytes=6u*c.shared_bank_bytes;
    cached(&c,0u);
    c.shared_total_bytes=9u*c.shared_bank_bytes;
    cached(&c,1u);
    memset(dsa_schedule_cache,0,sizeof(dsa_schedule_cache));
    dsa_schedule_cache_next=0u;
    c.rows=1u;c.depth=c.lhs_stride=c.rhs_stride=64u;c.cols=c.output_stride=10u;
    c.lhs_tile_packed=0u;c.lhs_address=c.rhs_address=c.output_address=0u;
    c.force_raw=0u;
    dsa_schedule_t compressed=cached(&c,0u);
    assert(!(compressed.ps_control&DSA_PS_CTRL_RAW));
    c.force_raw=1u;
    dsa_schedule_t raw=cached(&c,0u);
    assert(raw.ps_control&DSA_PS_CTRL_RAW);
    c.force_raw=0u;
    compressed=cached(&c,1u);
    assert(!(compressed.ps_control&DSA_PS_CTRL_RAW));
    c.ps_caps|=DSA_PS_CAP_RAW_ONLY;
    raw=cached(&c,0u);
    assert(raw.ps_control&DSA_PS_CTRL_RAW);
    c.ps_caps&=~DSA_PS_CAP_RAW_ONLY;
    compressed=cached(&c,1u);
    assert(!(compressed.ps_control&DSA_PS_CTRL_RAW));
    c.ps_caps|=DSA_PS_CAP_LITERAL_BOUND;
    c.ps_literal_bytes=48u;
    compressed=cached(&c,0u);
    assert((compressed.ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S24);
    c.ps_literal_bytes=32u;
    compressed=cached(&c,0u);
    assert((compressed.ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S16);
    c.ps_literal_bytes=48u;
    compressed=cached(&c,1u);
    assert((compressed.ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S24);
    c.force_raw=1u;
    raw=cached(&c,0u);
    assert((raw.ps_control&(DSA_PS_CTRL_RAW|DSA_PS_CTRL_BOUND_MASK))==DSA_PS_CTRL_RAW);
    c.force_raw=0u;c.ps_caps|=DSA_PS_CAP_RAW_ONLY;
    raw=cached(&c,0u);
    assert((raw.ps_control&(DSA_PS_CTRL_RAW|DSA_PS_CTRL_BOUND_MASK))==DSA_PS_CTRL_RAW);
    c.ps_caps&=~DSA_PS_CAP_RAW_ONLY;
    compressed=cached(&c,1u);
    assert((compressed.ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S24);
    printf("PLANNER_CACHE_PASS hits=%u misses=%u independent_plans=%u\n",hits,misses,equivalent);
    return 0;
}
