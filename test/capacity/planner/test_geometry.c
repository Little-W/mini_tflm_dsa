#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "gempact_tiling.h"

static uint32_t random_word(void)
{
    static uint32_t state=0x103ae617u;
    state^=state<<13;state^=state>>17;state^=state<<5;
    return state;
}

static uint64_t reference_cost(const gempact_device_request_t *q,
    uint32_t mode,uint32_t r,uint32_t w,uint32_t path,uint32_t slice,uint32_t resident,
    uint64_t stream,uint64_t stationary)
{
    if(!q->im2col_source_bytes) return 0;
    uint64_t elements=mode?stationary:stream;
    uint64_t result=elements+6u*((elements+q->im2col_pixel_channels-1u)/q->im2col_pixel_channels);
    uint64_t positions=(mode?w:r)*16u;
    if(positions>q->rows) positions=q->rows;
    if(mode&&path&&resident) {
        uint32_t rows=q->cols<r*16u?q->cols:r*16u;
        uint32_t parts=(rows+slice-1u)/slice;
        uint32_t columns=resident/parts;
        if(!columns) columns=1u;
        if(positions>columns*16u) positions=columns*16u;
    }
    uint64_t footprint=positions*q->im2col_stage_bytes_per_position;
    if(footprint>q->im2col_cache_bytes) {
        uint64_t unshared=(elements*q->im2col_source_bytes*(256u-q->im2col_base_fraction_q8))/256u;
        uint64_t overflow=256u-(uint64_t)q->im2col_cache_bytes*256u/footprint;
        result+=unshared*overflow/512u;
    }
    return result;
}

int main(void)
{
    uint32_t request_checks=0,cost_checks=0;
    for(uint32_t index=0;index<10000u;++index) {
        gempact_device_request_t q={0};
        gempact_im2col_geometry_t c={0};
        q.rows=1u+random_word()%4097u;q.cols=1u+random_word()%129u;
        c.input_channels=1u+random_word()%257u;
        c.group_channels=1u+random_word()%c.input_channels;
        c.kernel_h=1u+random_word()%7u;c.kernel_w=1u+random_word()%7u;
        c.stride_w=1u+random_word()%4u;c.source_bytes=1u+random_word()%2u;
        c.cache_bytes=(index%8u)?64u<<(random_word()%7u):0u;
        q.reduction=c.kernel_h*c.kernel_w*c.group_channels;
        c.input_bytes=1u+random_word()%1048576u;
        assert(gempact_set_im2col_geometry(&q,&c));
        assert(gempact_im2col_valid(&q));
        uint32_t crossed_rows=1u,covered=c.kernel_w*c.group_channels;
        while(covered<16u&&crossed_rows<c.kernel_h) {++crossed_rows;covered+=c.kernel_w*c.group_channels;}
        uint32_t expected_stage=c.stride_w*(c.input_channels<16u?c.input_channels:16u)*c.source_bytes*crossed_rows;
        uint64_t logical=(uint64_t)q.rows*q.reduction*c.source_bytes;
        uint32_t expected_fraction=c.input_bytes>=logical?256u:(uint32_t)((uint64_t)c.input_bytes*256u/logical);
        assert(q.im2col_stage_bytes_per_position==expected_stage);
        assert(q.im2col_base_fraction_q8==expected_fraction);
        assert(q.im2col_pixel_channels==(c.group_channels<16u?c.group_channels:16u));
        for(uint32_t mode=0;mode<2u;++mode) {
            uint32_t r=1u<<(random_word()%4u),w=1u+random_word()%64u;
            uint32_t path=random_word()%4u,slice=1u+random_word()%128u,resident=1u+random_word()%64u;
            uint64_t stream=1u+random_word()%1048576u,stationary=1u+random_word()%1048576u;
            assert(gempact_im2col_cost(&q,mode,r,w,path,slice,resident,stream,stationary)==
                   reference_cost(&q,mode,r,w,path,slice,resident,stream,stationary));
            ++cost_checks;
        }
        ++request_checks;
    }
    {
        gempact_device_request_t q={0};
        gempact_im2col_geometry_t c={8192u,64u,64u,1u,1u,1u,1u,1024u};
        q.rows=128u;q.reduction=64u;
        assert(gempact_set_im2col_geometry(&q,&c));
        assert(!gempact_image_window_sensitive(&q,64u));
        c.kernel_h=3u;q.reduction=192u;
        assert(gempact_set_im2col_geometry(&q,&c));
        assert(!gempact_image_window_sensitive(&q,4u));
        assert(gempact_image_window_sensitive(&q,8u));
        c.source_bytes=3u;assert(!gempact_set_im2col_geometry(&q,&c));
        c.source_bytes=2u;q.rows=UINT32_MAX;q.reduction=UINT32_MAX;
        assert(!gempact_set_im2col_geometry(&q,&c));
    }
    {
        gempact_device_request_t q={1024u,144u,16u,16u,2048u,16u,12288u,
            1u,3u,1u,1u,1u,2u,3u,1u,0u,32u,48u,0u,0,0,0,0,0,0,0,0};
        gempact_im2col_geometry_t c={16384u,16u,16u,3u,3u,1u,1u,1024u};
        gempact_dispatch_t p={0};
        assert(gempact_set_im2col_geometry(&q,&c));
        assert(gempact_plan_device(&q,&p));
        assert(p.is_mode==1u&&p.tiling.ia_reuse==1u&&p.tiling.w_reuse==3u&&p.ps_control==15u);
    }
    printf("{\"passed\":true,\"geometry_requests\":%u,\"independent_geometry_costs\":%u,\"boundary_checks\":5,\"small_window_micro_checks\":1,\"cache_bypass_supported\":true}\n",request_checks,cost_checks);
    return 0;
}
