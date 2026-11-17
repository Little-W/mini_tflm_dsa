#define GEMPACT_PLANNER_TEST_EXHAUSTIVE 1
#include "gempact_tiling.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

static void require(int condition,const char *message) {
    if(!condition) {fprintf(stderr,"%s\n",message);exit(1);}
}
static uint32_t random_word(void) {
    static uint32_t state=20261116u;
    state^=state<<13;state^=state>>17;state^=state<<5;return state;
}

static uint64_t replay_raw(const gempact_device_request_t *q,const gempact_dispatch_t *p) {
    uint32_t mode=p->is_mode,r=p->tiling.ia_reuse,w=p->tiling.w_reuse;
    uint32_t sr=mode?q->cols:q->rows,sc=mode?q->rows:q->cols;
    uint32_t ct=(sc+15u)/16u,kt=(q->reduction+15u)/16u;
    uint32_t tag_p[64],tag_q[64],stationary_c=UINT32_MAX,stationary_q=UINT32_MAX;
    uint64_t stream=0,stationary=0,parameters=0;
    int micro=(p->ps_control&2u)!=0u;
    for(unsigned i=0;i<64u;++i) {tag_p[i]=UINT32_MAX;tag_q[i]=UINT32_MAX;}
    for(uint32_t pg=0;pg<sr;pg+=r*16u) {
        uint32_t rows=gempact_min_u32(r*16u,sr-pg);
        uint32_t slice=micro?gempact_min_u32(rows,p->slice_rows):rows;
        uint32_t parts=(rows+slice-1u)/slice,window=w*parts;
        if(micro) {
            if(window>q->frames) window=q->frames;
            if(kt>1u) {
                uint32_t payload_frames=q->pool_bytes/(64u*slice);
                if(window>payload_frames) window=payload_frames;
                if(q->directory_rows&&window>q->directory_rows/p->slice_rows)
                    window=q->directory_rows/p->slice_rows;
            }
        }
        require(window>0u,"RAW replay needs a physical frame");
        for(uint32_t first=0;first<ct*parts;first+=window) {
            uint32_t end=gempact_min_u32(first+window,ct*parts);
            for(uint32_t k=0;k<kt;++k) {
                uint32_t red=gempact_min_u32(16u,q->reduction-k*16u);
                for(uint32_t frame=first;frame<end;++frame) {
                    uint32_t c=frame/parts,part=(frame%parts)*slice;
                    uint32_t active=gempact_min_u32(slice,rows-part);
                    if(k+1u==kt) {
                        uint32_t values=q->per_channel?3u:1u;
                        if(!mode) parameters+=(uint64_t)gempact_min_u32(16u,sc-c*16u)*values*4u;
                        else if(micro||c==0u) parameters+=(uint64_t)active*values*4u;
                    }
                    for(uint32_t local=0;local<active;local+=16u) {
                        uint32_t tile=(pg+part+local)/16u;
                        uint32_t slot=(tile+k*r)%p->ia_slots;
                        int hit=micro?(tag_p[slot]==tile&&tag_q[slot]==k):(c!=first/parts);
                        if(!hit) stream+=(uint64_t)gempact_min_u32(16u,active-local)*red;
                        tag_p[slot]=tile;tag_q[slot]=k;
                    }
                    if(!micro||stationary_c!=c||stationary_q!=k)
                        stationary+=(uint64_t)gempact_min_u32(16u,sc-c*16u)*red;
                    stationary_c=c;stationary_q=k;
                }
            }
        }
    }
    return parameters+(mode?stationary*q->lhs_element_bytes+stream:
                stream*q->lhs_element_bytes+stationary);
}

int main(void) {
    uint64_t candidates=0,exhaustive_candidates=0,raw_checks=0;uint32_t expanded=0,physical_checks=0;
    for(unsigned test=0;test<1000u;++test) {
        gempact_device_request_t q={0};gempact_dispatch_t raw={0},adaptive={0},exhaustive={0};
        q.rows=1u+random_word()%193u;q.cols=1u+random_word()%193u;
        q.reduction=1u+random_word()%257u;q.size=16u;q.ia_bytes=2048u;
        q.frames=16u;q.pool_bytes=4096u;q.mode=2u;q.is_supported=1u;
        q.lhs_element_bytes=1u+random_word()%2u;q.compact_mode_mask=random_word()%4u;
        q.frame_capable=1u;q.estimated_record_bytes=16u+16u*(random_word()%3u);
        q.literal_record_bytes=32u+16u*(random_word()%3u);q.micro_setup_cycles=random_word()%65u;
        if(test&1u) {
            q.im2col_source_bytes=1u+random_word()%2u;q.im2col_pixel_channels=1u+random_word()%16u;
            q.im2col_stage_bytes_per_position=1u+random_word()%257u;
            q.im2col_base_fraction_q8=random_word()%257u;q.im2col_cache_bytes=256u<<(random_word()%5u);
        }
        require(gempact_plan_device(&q,&raw),"RAW planner rejected a valid workload");
        require(gempact_plan_device_exhaustive(&q,&exhaustive),"Exhaustive RAW planner rejected a valid workload");
        require(!gempact_device_better(&raw,&exhaustive)&&!gempact_device_better(&exhaustive,&raw),
                "Reduced RAW selection differs from exhaustive ordering");
        require(raw.ps_control==exhaustive.ps_control && raw.is_mode==exhaustive.is_mode &&
                raw.tiling.ia_reuse==exhaustive.tiling.ia_reuse && raw.tiling.w_reuse==exhaustive.tiling.w_reuse,
                "Reduced RAW selection changed its configuration");
        require(raw.candidates_evaluated>0u&&raw.candidates_evaluated<=exhaustive.candidates_evaluated,
                "The RAW scored candidate count exceeds exhaustive enumeration");
        q.adaptive=1u;
        require(gempact_plan_device(&q,&adaptive),"Adaptive planner omitted a valid RAW workload");
        require(gempact_plan_device_exhaustive(&q,&exhaustive),"Exhaustive adaptive planner rejected a valid workload");
        if(gempact_device_better(&adaptive,&exhaustive)||gempact_device_better(&exhaustive,&adaptive)) {
            fprintf(stderr,"shape=%u,%u,%u optimized=%u,%u,%u,%u exhaustive=%u,%u,%u,%u\n",
                q.rows,q.reduction,q.cols,adaptive.is_mode,adaptive.tiling.ia_reuse,adaptive.tiling.w_reuse,adaptive.ps_control,
                exhaustive.is_mode,exhaustive.tiling.ia_reuse,exhaustive.tiling.w_reuse,exhaustive.ps_control);
            require(0,"Reduced adaptive selection differs from exhaustive ordering");
        }
        require(adaptive.ps_control==exhaustive.ps_control && adaptive.is_mode==exhaustive.is_mode &&
                adaptive.tiling.ia_reuse==exhaustive.tiling.ia_reuse && adaptive.tiling.w_reuse==exhaustive.tiling.w_reuse,
                "Reduced adaptive selection changed its configuration");
        require(adaptive.service_estimate<=raw.service_estimate,"Adaptive selection omitted the RAW minimum cost");
        require(adaptive.candidates_evaluated>0u&&adaptive.candidates_evaluated<=exhaustive.candidates_evaluated,
                "The scored candidate count exceeds exhaustive enumeration");
        candidates+=adaptive.candidates_evaluated;exhaustive_candidates+=exhaustive.candidates_evaluated;
        expanded+=adaptive.adaptive_active!=0u;
        for(uint32_t mode=0;mode<2u;++mode) {
            uint32_t maxr=(q.compact_mode_mask&(1u<<mode))?4u:2u;
            for(uint32_t r=1;r<=maxr;r*=2u) for(uint32_t w=1;w<=16u;++w) {
                for(uint32_t path=0;path<4u;++path) {
                    gempact_dispatch_t p={0};
                    if(!gempact_device_candidate(&q,mode,r,w,path,1u,&p)) continue;
                    if(p.operand_read_bytes!=replay_raw(&q,&p)) {
                        fprintf(stderr,"shape=%u,%u,%u mode=%u R=%u W=%u path=%u slots=%u predicted=%" PRIu64 " replay=%" PRIu64 "\n",
                            q.rows,q.reduction,q.cols,mode,r,w,path,p.ia_slots,p.operand_read_bytes,replay_raw(&q,&p));
                        require(0,"RAW transfer estimate differs from independent physical-slot replay");
                    }
                    ++raw_checks;
                }
            }
        }
    }
    for(unsigned test=0;test<1000u;++test) {
        const uint32_t pools[4]={64u,4096u,8192u,12288u};
        gempact_device_request_t q={0};gempact_dispatch_t reduced={0},exhaustive={0};
        q.rows=test%16u?1u+random_word()%2049u:1048575u;
        q.cols=test%17u?1u+random_word()%2049u:1048575u;
        q.reduction=1u+random_word()%1025u;q.size=16u;q.ia_bytes=1024u<<(random_word()%4u);
        q.directory_rows=test%3u?0u:16u<<(random_word()%8u);
        q.frames=(uint32_t[]){1u,4u,8u,16u,25u,32u,64u}[random_word()%7u];q.pool_bytes=pools[test%4u];q.mode=random_word()%3u;
        q.is_supported=random_word()%2u;q.req_r=random_word()%5u;q.req_w=random_word()%65u;
        q.per_channel=random_word()%2u;q.lhs_element_bytes=1u+random_word()%2u;
        q.compact_mode_mask=random_word()%4u;q.frame_capable=random_word()%2u;
        q.estimated_record_bytes=16u+16u*(random_word()%4u);
        q.literal_record_bytes=32u+16u*(random_word()%3u);q.micro_setup_cycles=random_word()%257u;
        if(test&1u) {
            q.im2col_source_bytes=1u+random_word()%2u;q.im2col_pixel_channels=1u+random_word()%16u;
            q.im2col_stage_bytes_per_position=1u+random_word()%257u;
            q.im2col_base_fraction_q8=random_word()%257u;q.im2col_cache_bytes=256u<<(random_word()%5u);
        }
        for(unsigned adaptive=0;adaptive<2u;++adaptive) {
            int a,b;q.adaptive=adaptive;
            a=gempact_plan_device(&q,&reduced);b=gempact_plan_device_exhaustive(&q,&exhaustive);
            require(a==b,"Reduced physical-capability search changed request acceptance");
            if(a) {
                require(!gempact_device_better(&reduced,&exhaustive)&&!gempact_device_better(&exhaustive,&reduced),
                        "Reduced physical-capability search changed candidate ordering");
                require(reduced.ps_control==exhaustive.ps_control && reduced.is_mode==exhaustive.is_mode &&
                        reduced.tiling.ia_reuse==exhaustive.tiling.ia_reuse &&
                        reduced.tiling.w_reuse==exhaustive.tiling.w_reuse,
                        "Reduced physical-capability search changed the selected configuration");
            }
            ++physical_checks;
        }
    }
    {
        gempact_device_request_t q={36,128,128,16,2048,16,4096,4,1,0,1,1,2,3,1,0,32,64,32,0,0,0,0,0,0,0,0};
        gempact_dispatch_t p={0};
        require(gempact_device_candidate(&q,0,4,1,0,1,&p),"R4 with a three-tile tail was rejected");
        require(p.tiling.row_groups==1u&&p.tiling.row_tail_tiles==3u&&p.payload_bound_bytes==2304u,"R4 tail geometry differs");
        q.reduction=16u;q.pool_bytes=64u;
        require(gempact_device_candidate(&q,0,4,8,0,1,&p)&&p.payload_bound_bytes==0u,"Single-K operation was restricted by PS capacity");
    }
    printf("{\"passed\":true,\"random_shapes\":1000,\"candidates\":%" PRIu64 ",\"exhaustive_candidates\":%" PRIu64 ",\"independent_raw_replays\":%" PRIu64 ",\"cold_adaptive_selections\":%u,\"physical_configuration_checks\":%u,\"tail_and_single_k_cases\":2}\n",candidates,exhaustive_candidates,raw_checks,expanded,physical_checks);
    return 0;
}
