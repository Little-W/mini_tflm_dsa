#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "gempact_tiling.h"

static uint32_t random_word(void)
{
    static uint32_t state=0x17421913u;
    state^=state<<13;state^=state>>17;state^=state<<5;return state;
}

static int reference_shared(const gempact_device_request_t *request,
    const gempact_shared_memory_t *memory,gempact_dispatch_t *result)
{
    int found=0,raw_found=0;uint32_t evaluated=0;gempact_dispatch_t raw_best={0};
    if(!gempact_shared_valid(memory)) return 0;
    for(uint32_t bank=1u;bank<32u;++bank) {
        if(!(memory->ia_bank_mask&(1u<<bank))) continue;
        uint64_t ia=(uint64_t)bank*memory->bank_bytes;
        if(ia>=memory->total_bytes) continue;
        gempact_device_request_t q=*request;gempact_dispatch_t candidate={0},raw={0};
        q.ia_bytes=(uint32_t)ia;q.pool_bytes=memory->total_bytes-(uint32_t)ia;
        q.directory_rows=memory->directory_rows;q.ia_bank_count=bank;
        q.ps_bank_count=memory->total_bytes/memory->bank_bytes-bank;
        if(!gempact_plan_device_exhaustive_pair(&q,&candidate,&raw)) continue;
        candidate.ia_bank_count=bank;
        if(raw.tiling.ia_reuse) {
            raw.ia_bank_count=bank;
            if(!raw_found||gempact_device_better(&raw,&raw_best)) {raw_best=raw;raw_found=1;}
        }
        evaluated+=candidate.candidates_evaluated;
        if(!found||gempact_device_better(&candidate,result)) {*result=candidate;found=1;}
    }
    if(found) {result->candidates_evaluated=evaluated;gempact_raw_execution(result,raw_found?&raw_best:0);}
    return found;
}

int main(void)
{
    uint32_t checks=0,raw_slices=0;
    for(uint32_t test=0;test<600u;++test) {
        gempact_device_request_t q={0};
        uint32_t bank_bytes=2048u<<(test%3u);
        gempact_shared_memory_t memory={(6u+(test/3u)%4u)*bank_bytes,bank_bytes,0x16u,1024u};
        q.rows=1u+random_word()%1025u;q.reduction=1u+random_word()%513u;q.cols=1u+random_word()%257u;
        q.size=16u;q.frames=16u;q.is_supported=1u;q.mode=random_word()%3u;
        q.frame_capable=1u;q.lhs_element_bytes=1u+random_word()%2u;q.compact_mode_mask=random_word()%4u;
        q.per_channel=random_word()%2u;q.estimated_record_bytes=16u*(1u+random_word()%4u);
        q.literal_record_bytes=32u+16u*(random_word()%3u);q.micro_setup_cycles=random_word()%65u;
        if(test&1u) {
            q.im2col_source_bytes=1u;q.im2col_pixel_channels=1u+random_word()%16u;
            q.im2col_stage_bytes_per_position=1u+random_word()%64u;
            q.im2col_base_fraction_q8=random_word()%257u;q.im2col_cache_bytes=1024u;
        }
        if(test%5u==0u) memory.directory_rows=16u<<(random_word()%7u);
        if(test%7u==0u) memory.ia_bank_mask=1u<<((uint32_t[]){1u,2u,4u}[random_word()%3u]);
        for(uint32_t policy=0;policy<2u;++policy) {
            gempact_dispatch_t a={0},b={0},raw={0};q.adaptive=policy;
            int good=gempact_plan_shared(&q,&memory,&a);
            assert(good==reference_shared(&q,&memory,&b));
            if(!good) continue;
            if(gempact_device_better(&a,&b)||gempact_device_better(&b,&a)) {
                fprintf(stderr,"test=%u policy=%u shape=%u,%u,%u mode=%u mask=%u compact=%u bytes=%u dir=%u literal=%u estimate=%u setup=%u\n",test,policy,q.rows,q.reduction,q.cols,q.mode,memory.ia_bank_mask,q.compact_mode_mask,q.lhs_element_bytes,memory.directory_rows,q.literal_record_bytes,q.estimated_record_bytes,q.micro_setup_cycles);
                fprintf(stderr,"fast IA%u mode%u R%u W%u ctl%u score%llu micro%llu bytes%llu stream%llu weight%llu\n",a.ia_bank_count,a.is_mode,a.tiling.ia_reuse,a.tiling.w_reuse,a.ps_control,(unsigned long long)a.service_estimate,(unsigned long long)a.micro_commands,(unsigned long long)a.operand_read_bytes,(unsigned long long)a.array_stream_cycles,(unsigned long long)a.weight_shift_rows);
                fprintf(stderr,"full IA%u mode%u R%u W%u ctl%u score%llu micro%llu bytes%llu stream%llu weight%llu\n",b.ia_bank_count,b.is_mode,b.tiling.ia_reuse,b.tiling.w_reuse,b.ps_control,(unsigned long long)b.service_estimate,(unsigned long long)b.micro_commands,(unsigned long long)b.operand_read_bytes,(unsigned long long)b.array_stream_cycles,(unsigned long long)b.weight_shift_rows);
                return 1;
            }
            assert(a.tiling.ia_reuse==b.tiling.ia_reuse);
            assert(a.tiling.w_reuse==b.tiling.w_reuse);
            assert(a.tiling.row_groups==b.tiling.row_groups);
            assert(a.tiling.row_tail_tiles==b.tiling.row_tail_tiles);
            assert(a.tiling.col_groups==b.tiling.col_groups);
            assert(a.tiling.col_tail_tiles==b.tiling.col_tail_tiles);
            assert(a.raw_safe.ia_reuse==b.raw_safe.ia_reuse);
            assert(a.raw_safe.w_reuse==b.raw_safe.w_reuse);
            assert(a.raw_safe.row_groups==b.raw_safe.row_groups);
            assert(a.raw_safe.row_tail_tiles==b.raw_safe.row_tail_tiles);
            assert(a.raw_safe.col_groups==b.raw_safe.col_groups);
            assert(a.raw_safe.col_tail_tiles==b.raw_safe.col_tail_tiles);
            assert(a.is_mode==b.is_mode);
            assert(a.frame_rows==b.frame_rows);
            assert(a.adaptive_active==b.adaptive_active);
            assert(a.reduction==b.reduction);
            assert(a.lhs_element_bytes==b.lhs_element_bytes);
            assert(a.bus_bytes==b.bus_bytes);
            assert(a.payload_bound_bytes==b.payload_bound_bytes);
            assert(a.lhs_read_rounds==b.lhs_read_rounds);
            assert(a.rhs_read_rounds==b.rhs_read_rounds);
            assert(a.operand_read_bytes==b.operand_read_bytes);
            assert(a.frame_count==b.frame_count);
            assert(a.array_stream_cycles==b.array_stream_cycles);
            assert(a.service_estimate==b.service_estimate);
            assert(a.ps_control==b.ps_control);
            assert(a.ia_slots==b.ia_slots);
            assert(a.slice_rows==b.slice_rows);
            assert(a.predicted_resident_frames==b.predicted_resident_frames);
            assert(a.estimated_record_bytes==b.estimated_record_bytes);
            assert(a.literal_record_bytes==b.literal_record_bytes);
            assert(a.micro_commands==b.micro_commands);
            assert(a.weight_shift_rows==b.weight_shift_rows);
            assert(a.ia_bank_count==b.ia_bank_count);
            assert(a.ia_bytes==b.ia_bytes);
            assert(a.pool_bytes==b.pool_bytes);
            assert(a.raw_safe_is_mode==b.raw_safe_is_mode);
            assert(a.raw_safe_ps_control==b.raw_safe_ps_control);
            assert(a.raw_safe_slice_rows==b.raw_safe_slice_rows);
            assert(a.raw_safe_ia_bank_count==b.raw_safe_ia_bank_count);
            assert(a.raw_safe_ia_bytes==b.raw_safe_ia_bytes);
            assert(a.raw_safe_pool_bytes==b.raw_safe_pool_bytes);
            assert(a.tiling.ia_reuse==b.tiling.ia_reuse&&a.tiling.w_reuse==b.tiling.w_reuse);
            assert(a.ia_bank_count==b.ia_bank_count&&a.ia_bytes==b.ia_bytes&&a.pool_bytes==b.pool_bytes);
            assert(a.ia_bytes+a.pool_bytes==memory.total_bytes);
            assert(a.ia_bank_count*memory.bank_bytes==a.ia_bytes);
            assert(a.candidates_evaluated<=b.candidates_evaluated);
            assert(a.raw_safe_is_mode==b.raw_safe_is_mode&&a.raw_safe_ps_control==b.raw_safe_ps_control);
            assert(a.raw_safe_slice_rows==b.raw_safe_slice_rows&&a.raw_safe_ia_bank_count==b.raw_safe_ia_bank_count);
            if(a.raw_safe.ia_reuse) {
            q.ia_bank_count=a.raw_safe_ia_bank_count;q.ps_bank_count=memory.total_bytes/memory.bank_bytes-q.ia_bank_count;
            q.ia_bytes=a.raw_safe_ia_bytes;q.pool_bytes=a.raw_safe_pool_bytes;q.directory_rows=memory.directory_rows;
            uint32_t path=(a.raw_safe_ps_control&2u)?
                ((a.raw_safe_ps_control>>2)==3u?1u:(a.raw_safe_ps_control>>2)==1u?2u:3u):0u;
            assert(gempact_device_candidate(&q,a.raw_safe_is_mode,a.raw_safe.ia_reuse,a.raw_safe.w_reuse,path,1u,&raw));
            assert(raw.ps_control==a.raw_safe_ps_control&&raw.slice_rows==a.raw_safe_slice_rows);
            raw_slices+=(raw.ps_control&2u)!=0u;
            }
            if(!policy) assert(a.ps_control&1u);
            ++checks;
        }
    }
    {
        gempact_device_request_t q={0};gempact_dispatch_t p={0};
        q.rows=256u;q.reduction=144u;q.cols=64u;q.size=16u;q.ia_bytes=8192u;q.pool_bytes=6144u;
        q.frames=16u;q.directory_rows=1024u;q.frame_capable=1u;q.compact_mode_mask=3u;
        q.lhs_element_bytes=2u;q.estimated_record_bytes=32u;q.literal_record_bytes=48u;
        assert(gempact_device_candidate(&q,0u,16u,4u,2u,1u,&p));
        assert(p.ps_control==7u&&p.payload_bound_bytes>q.pool_bytes&&p.slice_rows==16u);
        assert(!gempact_device_candidate(&q,0u,16u,4u,0u,1u,&p));
        q.rows=100u;q.cols=512u;q.pool_bytes=65536u;q.frames=64u;
        assert(gempact_device_candidate(&q,0u,4u,32u,1u,1u,&p));
        assert(p.predicted_resident_frames==16u);
    }
    {
        gempact_device_request_t q={0};gempact_dispatch_t p={0};
        q.rows=q.cols=16u;q.reduction=32u;q.size=16u;q.ia_bytes=8192u;q.pool_bytes=6144u;
        q.ia_bank_count=4u;q.ps_bank_count=3u;q.frames=16u;q.directory_rows=1024u;
        q.frame_capable=q.adaptive=1u;q.compact_mode_mask=3u;q.lhs_element_bytes=2u;
        q.estimated_record_bytes=32u;q.literal_record_bytes=48u;
        assert(gempact_device_candidate(&q,0u,1u,1u,0u,0u,&p)&&p.adaptive_active);
        assert(!gempact_device_candidate(&q,0u,1u,1u,0u,1u,&p));
        q.literal_record_bytes=64u;assert(!gempact_device_candidate(&q,0u,1u,1u,1u,0u,&p));
        q.reduction=16u;assert(gempact_device_candidate(&q,0u,1u,1u,0u,1u,&p));
        q.ia_bank_count=1u;q.ia_bytes=2048u;q.ps_bank_count=6u;q.pool_bytes=12288u;
        q.compact_mode_mask=2u;
        assert(!gempact_device_candidate(&q,0u,1u,1u,0u,1u,&p));
        assert(gempact_device_candidate(&q,1u,1u,1u,0u,1u,&p));
    }
    uint32_t capability_checks=0u;
    for(uint32_t bytes=2048u;bytes<=8192u;bytes*=2u)
    for(uint32_t banks=0u;banks<=12u;++banks) {
        gempact_shared_memory_t memory={banks*bytes,bytes,0x16u,1024u};
        assert(gempact_shared_valid(&memory)==(banks>=6u&&banks<=9u));++capability_checks;
    }
    {
        gempact_shared_memory_t memory={14336u,2048u,0x16u,1024u};
        memory.bank_bytes=512u;memory.total_bytes=7u*512u;assert(!gempact_shared_valid(&memory));++capability_checks;
        memory.bank_bytes=1024u;memory.total_bytes=7u*1024u;assert(!gempact_shared_valid(&memory));++capability_checks;
        memory.total_bytes=14336u;
        memory.bank_bytes=2048u;memory.directory_rows=0u;
        assert(!gempact_shared_valid(&memory));++capability_checks;
        memory.directory_rows=1024u;memory.ia_bank_mask=8u;
        assert(!gempact_shared_valid(&memory));++capability_checks;
        memory.ia_bank_mask=0x16u;memory.total_bytes+=16u;
        assert(!gempact_shared_valid(&memory));++capability_checks;
    }
    {
        gempact_shared_memory_t memory={7u*4096u,4096u,0x16u,1024u};
        gempact_device_request_t q={0};gempact_dispatch_t fast={0},full={0};
        q.rows=512u;q.reduction=16u;q.cols=16u;q.size=16u;q.frames=16u;
        q.frame_capable=q.is_supported=1u;q.mode=0u;q.compact_mode_mask=3u;
        q.lhs_element_bytes=1u;q.estimated_record_bytes=32u;q.literal_record_bytes=48u;
        q.micro_setup_cycles=64u;
        assert(gempact_plan_shared(&q,&memory,&fast));
        assert(reference_shared(&q,&memory,&full));
        assert(!gempact_device_better(&fast,&full)&&!gempact_device_better(&full,&fast));
        assert(fast.tiling.ia_reuse==32u&&fast.ia_bank_count==4u&&fast.ia_slots==64u);
        ++capability_checks;
        memory.total_bytes=7u*8192u;memory.bank_bytes=8192u;q.rows=1024u;
        assert(gempact_plan_shared(&q,&memory,&fast));
        assert(reference_shared(&q,&memory,&full));
        assert(!gempact_device_better(&fast,&full)&&!gempact_device_better(&full,&fast));
        assert(fast.tiling.ia_reuse==64u&&fast.ia_bank_count==4u&&fast.ia_slots==128u);
        ++capability_checks;
        for(uint32_t bytes=2048u;bytes<=8192u;bytes*=2u) {
            q.ia_bytes=bytes;q.ia_bank_count=1u;q.pool_bytes=6u*bytes;q.ps_bank_count=6u;
            q.compact_mode_mask=2u;q.directory_rows=1024u;
            assert(!gempact_device_candidate(&q,0u,1u,1u,0u,1u,&fast));
            assert(gempact_device_candidate(&q,1u,1u,1u,0u,1u,&fast));
            assert(gempact_ps_bank_words(&q)==bytes/16u);
            ++capability_checks;
        }
    }
    uint32_t bank_checks=0u;
    for(uint32_t banks=2u;banks<=8u;++banks) for(uint32_t words=3u;words<=4u;++words)
    for(uint32_t rows=1u;rows<=256u;++rows) {
        gempact_device_request_t q={0};q.ps_bank_count=banks;
        uint32_t maximum=0u;
        for(uint32_t rotation=0u;rotation<banks;++rotation) {
            uint32_t count[8]={0};
            for(uint32_t w=0u;w<rows*words;++w) ++count[(rotation+w)%banks];
            for(uint32_t bank=0u;bank<banks;++bank) if(maximum<count[bank]) maximum=count[bank];
        }
        assert(maximum==gempact_reserve_bank_words(&q,rows,words*16u));++bank_checks;
    }
    printf("{\"passed\":true,\"shared_request_checks\":1200,\"accepted_shared_requests\":%u,\"decision_fields_per_request\":42,\"complete_raw_micro_plans\":%u,\"directory_tail_checks\":1,\"raw_sliced_admission_checks\":2,\"bandwidth_checks\":6,\"rotated_reservation_checks\":%u,\"shared_capability_checks\":%u}\n",checks,raw_slices,bank_checks,capability_checks);
    return 0;
}
