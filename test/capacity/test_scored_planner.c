/* SPDX-License-Identifier: Apache-2.0 */
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#include "dsa_schedule.h"
static uint32_t rng=0x8542a517u;
static uint32_t rnd(void) {rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
static void req(const dsa_schedule_config_t *c,gempact_device_request_t *q) {
 *q=(gempact_device_request_t){0};
 q->rows=c->rows;q->cols=c->cols;q->reduction=c->depth;q->size=16;q->frames=c->ps_frames;
 q->req_r=c->requested_r;q->req_w=c->requested_w;q->mode=c->flow;q->is_supported=c->allow_is;
 q->per_channel=c->per_channel;q->lhs_element_bytes=c->lhs_bytes;
 q->compact_mode_mask=(c->ps_caps&DSA_PS_CAP_IA_COMPACT)?c->compact_mode_mask:0;
 q->frame_capable=(c->ps_caps&DSA_PS_CAP_FRAME_SCHEDULE)!=0;
 q->adaptive=q->frame_capable&&!c->force_raw&&!(c->ps_caps&DSA_PS_CAP_RAW_ONLY);
 q->estimated_record_bytes=c->source_s8?DSA_PLANNER_RECORD_BYTES:64;
 q->literal_record_bytes=gempact_literal_record_bytes(c->depth,c->source_s8,c->lhs_offset,c->rhs_offset);
 q->micro_setup_cycles=DSA_PLANNER_MICRO_CYCLES;q->directory_rows=c->ps_directory_rows;
 if(c->im2col.input_bytes) assert(gempact_set_im2col_geometry(q,&c->im2col));
 if(c->output_bytes==2&&c->output_banks_s16&&(!q->req_r||q->req_r>c->output_banks_s16))q->req_r=c->output_banks_s16;
}
static int enumerate(const dsa_schedule_config_t *c,dsa_schedule_t *best) {
 uint64_t aw,ar,bw,br;int found=0;
 dsa_schedule_operand(c,c->rows,c->lhs_bytes,c->lhs_stride,c->lhs_address,!c->spatial,c->lhs_tile_packed,&aw,&ar);
 dsa_schedule_operand(c,c->cols,c->rhs_bytes,c->rhs_stride,c->rhs_address,1,c->rhs_tile_packed,&bw,&br);
 for(uint32_t bank=1;bank<c->shared_total_bytes/c->shared_bank_bytes;bank++) {
  if(!(c->shared_ia_bank_mask&(1u<<bank)))continue;
  gempact_device_request_t q;req(c,&q);q.ia_bank_count=bank;q.ps_bank_count=c->shared_total_bytes/c->shared_bank_bytes-bank;
  q.ia_bytes=bank*c->shared_bank_bytes;q.pool_bytes=c->shared_total_bytes-q.ia_bytes;
  for(uint32_t mode=0;mode<2;mode++) {
   if((c->flow<2&&c->flow!=mode)||(mode&&!c->allow_is))continue;
   uint32_t slots=q.ia_bytes/512*((q.compact_mode_mask>>mode&1)?2:1);
   uint32_t tc=gempact_ceil_div(mode?c->rows:c->cols,16);
   for(uint32_t r=1;r<=slots/2;r*=2) {
    if(q.req_r&&r>q.req_r)continue;
    for(uint32_t w=1;w<=gempact_window_limit(&q,tc);w++) for(uint32_t path=0;path<4;path++)for(uint32_t raw=0;raw<2;raw++) {
     if(!raw&&!q.adaptive)continue;
     gempact_dispatch_t p;dsa_schedule_t s;
     if(!gempact_device_candidate(&q,mode,r,w,path,raw,&p))continue;
     if(!raw&&!p.adaptive_active)continue;
     dsa_schedule_memory_score(c,&q,&p,aw,ar,bw,br,&s);
     if(!found||dsa_schedule_better(&s,best)){*best=s;found=1;}
    }
   }
  }
 }
 return found;
}
static void show(const char *tag,const dsa_schedule_t *s){printf(" %s score=%llu read=%llu/%llu compute=%llu write=%llu ia=%u mode=%u R=%u W=%u ctrl=%u slice=%u\n",tag,(unsigned long long)s->estimated_cycles,(unsigned long long)s->read_words,(unsigned long long)s->read_requests,(unsigned long long)s->compute_cycles,(unsigned long long)s->write_requests,s->ia_bank_count,s->dataflow_mode,s->tiling.ia_reuse,s->tiling.w_reuse,s->ps_control,s->frame_rows);}
static void geometry_checks(void)
{
 dsa_schedule_config_t c;uint32_t footprints[65];
 dsa_schedule_init(&c,256u,144u,32u,16u,4u,16u);
 c.im2col=(gempact_im2col_geometry_t){16384u,16u,16u,3u,3u,2u,1u,4096u};
 c.im2col_input_width=32u;c.im2col_output_width=16u;c.im2col_stride_h=2u;
 dsa_schedule_window_footprints(&c,footprints);
 assert(footprints[4]==4096u && footprints[8]==8192u);
 c.im2col.source_bytes=2u;
 dsa_schedule_window_footprints(&c,footprints);
 assert(footprints[4]==8192u && footprints[8]==16384u);
 c.im2col.source_bytes=1u;c.im2col.stride_w=1u;
 c.im2col_output_width=32u;c.im2col_stride_h=1u;
 dsa_schedule_window_footprints(&c,footprints);
 assert(footprints[8]==2048u && footprints[16]==4096u);
 c.im2col.input_channels=c.im2col.group_channels=3u;
 dsa_schedule_window_footprints(&c,footprints);
 for(uint32_t i=0u;i<=64u;++i)assert(footprints[i]==0u);
}

int main(void){unsigned checks=0,fail=0;
 geometry_checks();
 for(uint32_t i=0;i<800;i++){
  dsa_schedule_config_t c;dsa_schedule_t fast={0},all={0},rawp={0};
  uint32_t dims[]={1,7,16,17,31,32,36,47,64,80,96,128,144,192,256,257,384};
  dsa_schedule_init(&c,dims[rnd()%17],dims[rnd()%17],dims[rnd()%17],16,4,16);
  c.ps_caps=(1u<<24)|(16u<<16)|23u;c.ps_pool_bytes=12288;c.ia_cache_bytes=2048;
  c.shared_bank_bytes=1024u<<(i%3u);c.shared_total_bytes=(6u+(i/3u)%4u)*c.shared_bank_bytes;c.shared_ia_bank_mask=0x16;c.ps_directory_rows=(rnd()&1)?1024:256;
  c.flow=rnd()%3;c.allow_is=1;c.force_raw=rnd()&1;c.compact_mode_mask=rnd()%4;c.source_s8=rnd()&1;
  c.lhs_bytes=c.source_s8?1:2;c.output_bytes=(rnd()%4)?1:2;c.output_banks_s8=8;c.output_banks_s16=8;
  c.lhs_stride=c.depth*c.lhs_bytes+(rnd()%5);c.rhs_stride=c.depth+(rnd()%5);c.output_stride=c.cols*c.output_bytes+(rnd()%5);
  c.lhs_address=rnd()%4096;c.rhs_address=rnd()%4096;c.output_address=rnd()%4096;
  c.has_bias=rnd()&1;c.per_channel=rnd()&1;c.lhs_offset=(int)(rnd()%257)-128;c.rhs_offset=(int)(rnd()%257)-128;
  c.lhs_tile_packed=rnd()&1;c.rhs_tile_packed=rnd()&1;
  c.read_beat_cycles=1+rnd()%4;c.write_beat_cycles=1+rnd()%4;c.read_request_cycles=rnd()%12;c.write_request_cycles=rnd()%16;
  c.axi_data_bits=(i&1u)?64u:32u;c.dma_max_bytes=(c.axi_data_bits/8u)<<(rnd()%9u);
  if(i%3==0){c.spatial=1;c.lhs_tile_packed=0;c.lhs_bytes=2;c.im2col=(gempact_im2col_geometry_t){32768,32,32,3,3,1,c.source_s8?1:2,4096};c.im2col_input_width=32;c.im2col_output_width=16;c.im2col_stride_h=2;}
  if(rnd()%5==0)c.requested_r=1u<<(rnd()%5);
  if(rnd()%5==0)c.requested_w=1+rnd()%16;
  int a=dsa_schedule_plan(&c,&fast),b=enumerate(&c,&all);
  if(a!=b||(a&&dsa_schedule_better(&all,&fast))){printf("MISMATCH i=%u shape=%u,%u,%u raw=%u flow=%u compact=%u total=%u geom=%u\n",i,c.rows,c.depth,c.cols,c.force_raw,c.flow,c.compact_mode_mask,c.shared_total_bytes,c.spatial);show("fast",&fast);show("all",&all);if(++fail>=8)return 1;}
  if(a){assert(fast.read_words==fast.read_beats*(c.axi_data_bits/32u));assert(fast.write_words==fast.write_beats*(c.axi_data_bits/32u));assert(fast.ia_cache_bytes+fast.ps_pool_bytes==c.shared_total_bytes);uint32_t slots=fast.ia_cache_bytes/512*((c.compact_mode_mask>>fast.dataflow_mode&1)?2:1);assert(fast.tiling.ia_reuse<=slots/2);if(c.force_raw)assert(fast.ps_control&1);if(!c.force_raw){c.force_raw=1;int ok=dsa_schedule_plan(&c,&rawp);if(ok&&dsa_schedule_better(&rawp,&fast)){printf("RAW_FAIRNESS i=%u\n",i);show("adaptive",&fast);show("raw",&rawp);if(++fail>=8)return 1;}}}
  ++checks;
 }
 printf("SCORED_PLANNER_PASS configurations=%u geometry_checks=71 failures=%u\n",checks,fail);return fail?1:0;
}
