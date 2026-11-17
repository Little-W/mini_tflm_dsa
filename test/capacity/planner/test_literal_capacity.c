#include "gempact_tiling.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

_Static_assert(sizeof(gempact_device_request_t)==27u*sizeof(uint32_t),"request layout");

static void require(int condition,const char *message)
{
    if(!condition) {fprintf(stderr,"%s\n",message);exit(1);}
}

static uint32_t operand_bound(uint32_t source_s8,int32_t offset)
{
    if(!source_s8) return 32768u;
    if(offset==0) return 128u;
    if(offset>=-128&&offset<=128) return 256u;
    return 32768u;
}

int main(void)
{
    uint64_t format_checks=0,capacity_checks=0,rotation_checks=0,occupancy_checks=0;
    const int32_t offsets[]={INT32_MIN,-65537,-129,-128,-127,-1,0,1,127,128,129,65536,INT32_MAX};
    const uint32_t reductions[]={0,1,15,16,17,31,32,33,127,128,129,255,256,257,511,512,513,65535,1048575,UINT32_MAX};
    for(uint32_t type=0;type<2u;++type)
    for(uint32_t a=0;a<sizeof(offsets)/sizeof(offsets[0]);++a)
    for(uint32_t b=0;b<sizeof(offsets)/sizeof(offsets[0]);++b)
    for(uint32_t k=0;k<sizeof(reductions)/sizeof(reductions[0]);++k) {
        uint32_t reduction=reductions[k],prefix=reduction?(reduction-1u)&~15u:0u;
        uint64_t product=(uint64_t)operand_bound(type,offsets[a])*operand_bound(1u,offsets[b]);
        uint32_t expected=reduction&&product<8388608u&&product*prefix<8388608u?48u:64u;
        require(gempact_literal_record_bytes(reduction,type,offsets[a],offsets[b])==expected,
                "Format bound differs from the integer product reference");
        ++format_checks;
    }
    for(uint32_t cap=2;cap<=4u;++cap)
    for(uint32_t rows=1;rows<=128u;++rows)
    for(uint32_t start=0;start<4u;++start)
    for(uint32_t pattern=0;pattern<8u;++pattern) {
        uint32_t bank[4]={0},position=start;
        for(uint32_t row=0;row<rows;++row) {
            uint32_t words=pattern==0u?cap:(row*13u+pattern*17u)%(cap+1u);
            for(uint32_t word=0;word<words;++word) {++bank[position];position=(position+1u)%4u;}
        }
        for(uint32_t b=0;b<4u;++b)
            require(bank[b]<=(cap*rows+3u)/4u,"Record rotation exceeded the per-frame bank reservation");
        require(gempact_bank_reservation(rows,cap*16u)==(cap*rows+3u)/4u,
                "Per-frame bank rounding differs from integer arithmetic");
        ++rotation_checks;
    }
    for(uint32_t mode=0;mode<2u;++mode)
    for(uint32_t literal=32u;literal<=64u;literal+=16u)
    for(uint32_t rows=1u;rows<=128u;++rows)
    for(uint32_t w=1u;w<=64u;++w) {
        uint32_t cap=literal/16u,frame=(cap*rows+3u)/4u;
        uint32_t depth_cases[]={1u,frame,frame*w-1u,frame*w,rows*w};
        for(uint32_t t=0;t<sizeof(depth_cases)/sizeof(depth_cases[0]);++t) {
            uint32_t depth=depth_cases[t];
            if(!depth) continue;
            gempact_device_request_t q={0};gempact_dispatch_t p={0};
            q.rows=mode?1024u:rows;q.cols=mode?rows:1024u;q.reduction=64u;q.size=16u;
            q.ia_bytes=8192u;q.frames=64u;q.pool_bytes=64u*depth;q.mode=mode;
            q.is_supported=q.frame_capable=q.adaptive=1u;q.lhs_element_bytes=1u;
            q.estimated_record_bytes=32u;q.literal_record_bytes=literal;
            int expected=(w&(w-1u))==0u&&frame*w<=depth;
            require(gempact_device_candidate(&q,mode,8u,w,0u,0u,&p)==expected,
                    "Literal long eligibility differs from the per-frame bank bound");
            expected=(w&(w-1u))==0u&&rows*w<=depth;
            require(gempact_device_candidate(&q,mode,8u,w,0u,1u,&p)==expected,
                    "RAW long eligibility differs from the four-word row bound");
            require(gempact_device_candidate(&q,mode,8u,w,1u,0u,&p)==(frame<=depth),
                    "Whole-R command eligibility differs from its protected-frame bound");
            ++capacity_checks;
        }
    }
    for(uint32_t literal=32u;literal<=64u;literal+=16u)
    for(uint32_t estimate=16u;estimate<=64u;estimate+=16u)
    for(uint32_t rows=1u;rows<=64u;++rows) {
        uint32_t cap=literal;
        uint32_t reserved=(cap/16u*rows+3u)/4u;
        uint32_t record=estimate<cap?estimate:cap;
        uint32_t occupied=(cap+(rows-1u)*record+63u)/64u;
        for(uint32_t depth=reserved;depth<reserved+65u;++depth) {
            gempact_device_request_t q={0};uint32_t admitted=1u,remaining=depth-reserved;
            q.literal_record_bytes=literal;q.estimated_record_bytes=estimate;q.pool_bytes=depth*64u;q.size=16u;q.reduction=32u;
            while(remaining>=occupied) {remaining-=occupied;++admitted;}
            require(gempact_record_limit(&q,rows,rows,0u,UINT32_MAX)==admitted,
                    "Predicted resident count differs from repeated bank allocation");
            ++occupancy_checks;
        }
    }
    {
        gempact_device_request_t q={125u,64u,64u,16u,2048u,16u,12288u,0,0,2u,1u,1u,2u,3u,1u,1u,32u,48u,32u,0,0,0,0,0,0,0,0};
        gempact_dispatch_t p={0},raw={0};
        require(gempact_plan_device(&q,&p)&&p.adaptive_active&&p.ps_control==0u&&
                p.literal_record_bytes==48u&&p.tiling.ia_reuse==4u&&p.tiling.w_reuse==4u,
                "Static S24 workload did not select its legal long window");
        q.adaptive=0;
        require(gempact_plan_device(&q,&raw)&&raw.ps_control==1u&&
                raw.payload_bound_bytes<=q.pool_bytes&&raw.literal_record_bytes==64u,
                "RAW policy did not retain a complete legal long choice");
        q.adaptive=1;q.literal_record_bytes=64u;
        require(gempact_device_candidate(&q,0u,4u,4u,1u,0u,&p)&&p.ps_control==14u,
                "Whole-R scheduling was lost when the static S24 proof was unavailable");
        require(!gempact_device_candidate(&q,0u,4u,4u,0u,0u,&p),
                "An unproven long window bypassed its RAW requirement");
        q.frame_capable=0;q.literal_record_bytes=48u;
        require(gempact_plan_device(&q,&p)&&(p.ps_control&1u),
                "A request without frame capability used compressed scheduling");
    }
    {
        gempact_device_request_t q={196u,72u,16u,16u,2048u,16u,13312u,0,0,1u,1u,1u,2u,3u,1u,1u,32u,48u,32u,0,0,0,0,0,0,0,0};
        gempact_dispatch_t p={0};
        require(gempact_plan_device(&q,&p)&&p.tiling.w_reuse==16u&&p.ps_control==1u&&
                p.payload_bound_bytes==13u*16u*64u,
                "RAW long tail did not reserve only its thirteen actual frames");
        q.pool_bytes=9984u;
        require(gempact_device_candidate(&q,1u,1u,16u,0u,0u,&p)&&
                p.ps_control==0u&&p.payload_bound_bytes==13312u&&p.literal_record_bytes==48u,
                "S24 long tail did not admit its thirteen actual frames");
        require(!gempact_device_candidate(&q,1u,1u,16u,0u,1u,&p),
                "RAW long tail ignored its actual payload requirement");
        q.frames=13u;
        require(!gempact_device_candidate(&q,1u,1u,16u,0u,0u,&p),
                "A padded configuration exceeded FRAME_COUNT");
        q.frames=16u;q.req_w=13u;
        require(gempact_window_limit(&q,13u)==13u,"Tail padding exceeded the requested W limit");
        q.req_w=0;q.reduction=16u;q.pool_bytes=64u;
        require(gempact_device_candidate(&q,1u,1u,16u,0u,1u,&p)&&p.payload_bound_bytes==0u,
                "A single-K padded tail acquired a PS requirement");
    }
    printf("{\"passed\":true,\"format_checks\":%" PRIu64 ",\"capacity_checks\":%" PRIu64
           ",\"bank_rotation_checks\":%" PRIu64 ",\"predicted_resident_checks\":%" PRIu64
           ",\"selection_cases\":11}\n",format_checks,capacity_checks,rotation_checks,occupancy_checks);
    return 0;
}
