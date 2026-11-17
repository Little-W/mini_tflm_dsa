#include "gempact_tiling.h"
#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
int reference_plan(const gempact_device_request_t *,gempact_dispatch_t *);
static uint32_t rng(void) { static uint32_t s=0x515053u;s^=s<<13;s^=s>>17;s^=s<<5;return s; }
int main(void) { unsigned accepted=0,checks=0;
 for(unsigned i=0;i<10000u;++i) {
  gempact_device_request_t q={0};gempact_dispatch_t a={0},b={0};
  q.rows=1u+rng()%((i%7u)?513u:1048575u);q.cols=1u+rng()%((i%9u)?513u:1048575u);
  q.reduction=1u+rng()%1025u;q.size=16u;q.ia_bytes=512u<<(rng()%5u);
  q.frames=(uint32_t[]){1,4,8,16,25,32,64}[rng()%7u];q.pool_bytes=64u*(1u+rng()%257u);q.mode=rng()%3u;
  q.is_supported=rng()%2u;q.per_channel=rng()%2u;q.lhs_element_bytes=1u+rng()%3u;
  q.req_r=rng()%9u;q.req_w=rng()%65u;q.compact_mode_mask=rng()%4u;
  q.frame_capable=rng()%2u;q.adaptive=rng()%2u;q.estimated_record_bytes=16u+rng()%49u;
  q.literal_record_bytes=32u+16u*(rng()%3u);q.micro_setup_cycles=rng()%1025u;
  if(i&1u) {
   q.im2col_source_bytes=1u+rng()%2u;q.im2col_pixel_channels=1u+rng()%16u;
   q.im2col_stage_bytes_per_position=1u+rng()%513u;
   q.im2col_base_fraction_q8=rng()%257u;q.im2col_cache_bytes=64u<< (rng()%7u);
  }
  q.directory_rows=(i%3u)?0u:16u<<(rng()%8u);
  int x=gempact_plan_device(&q,&a),y=reference_plan(&q,&b);
  if(x!=y) {fprintf(stderr,"acceptance differs at %u\n",i);return 1;}
  if(x) {
   if(a.tiling.ia_reuse!=b.tiling.ia_reuse) {fprintf(stderr,"field tiling.ia_reuse differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.tiling.ia_reuse,(uint64_t)b.tiling.ia_reuse);return 1;}
   if(a.tiling.w_reuse!=b.tiling.w_reuse) {fprintf(stderr,"field tiling.w_reuse differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.tiling.w_reuse,(uint64_t)b.tiling.w_reuse);return 1;}
   if(a.tiling.row_groups!=b.tiling.row_groups) {fprintf(stderr,"field tiling.row_groups differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.tiling.row_groups,(uint64_t)b.tiling.row_groups);return 1;}
   if(a.tiling.row_tail_tiles!=b.tiling.row_tail_tiles) {fprintf(stderr,"field tiling.row_tail_tiles differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.tiling.row_tail_tiles,(uint64_t)b.tiling.row_tail_tiles);return 1;}
   if(a.tiling.col_groups!=b.tiling.col_groups) {fprintf(stderr,"field tiling.col_groups differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.tiling.col_groups,(uint64_t)b.tiling.col_groups);return 1;}
   if(a.tiling.col_tail_tiles!=b.tiling.col_tail_tiles) {fprintf(stderr,"field tiling.col_tail_tiles differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.tiling.col_tail_tiles,(uint64_t)b.tiling.col_tail_tiles);return 1;}
   if(a.raw_safe.ia_reuse!=b.raw_safe.ia_reuse) {fprintf(stderr,"field raw_safe.ia_reuse differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.raw_safe.ia_reuse,(uint64_t)b.raw_safe.ia_reuse);return 1;}
   if(a.raw_safe.w_reuse!=b.raw_safe.w_reuse) {fprintf(stderr,"field raw_safe.w_reuse differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.raw_safe.w_reuse,(uint64_t)b.raw_safe.w_reuse);return 1;}
   if(a.raw_safe.row_groups!=b.raw_safe.row_groups) {fprintf(stderr,"field raw_safe.row_groups differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.raw_safe.row_groups,(uint64_t)b.raw_safe.row_groups);return 1;}
   if(a.raw_safe.row_tail_tiles!=b.raw_safe.row_tail_tiles) {fprintf(stderr,"field raw_safe.row_tail_tiles differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.raw_safe.row_tail_tiles,(uint64_t)b.raw_safe.row_tail_tiles);return 1;}
   if(a.raw_safe.col_groups!=b.raw_safe.col_groups) {fprintf(stderr,"field raw_safe.col_groups differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.raw_safe.col_groups,(uint64_t)b.raw_safe.col_groups);return 1;}
   if(a.raw_safe.col_tail_tiles!=b.raw_safe.col_tail_tiles) {fprintf(stderr,"field raw_safe.col_tail_tiles differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.raw_safe.col_tail_tiles,(uint64_t)b.raw_safe.col_tail_tiles);return 1;}
   if(a.is_mode!=b.is_mode) {fprintf(stderr,"field is_mode differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.is_mode,(uint64_t)b.is_mode);return 1;}
   if(a.frame_rows!=b.frame_rows) {fprintf(stderr,"field frame_rows differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.frame_rows,(uint64_t)b.frame_rows);return 1;}
   if(a.adaptive_active!=b.adaptive_active) {fprintf(stderr,"field adaptive_active differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.adaptive_active,(uint64_t)b.adaptive_active);return 1;}
   if(a.reduction!=b.reduction) {fprintf(stderr,"field reduction differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.reduction,(uint64_t)b.reduction);return 1;}
   if(a.lhs_element_bytes!=b.lhs_element_bytes) {fprintf(stderr,"field lhs_element_bytes differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.lhs_element_bytes,(uint64_t)b.lhs_element_bytes);return 1;}
   if(a.bus_bytes!=b.bus_bytes) {fprintf(stderr,"field bus_bytes differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.bus_bytes,(uint64_t)b.bus_bytes);return 1;}
   if(a.payload_bound_bytes!=b.payload_bound_bytes) {fprintf(stderr,"field payload_bound_bytes differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.payload_bound_bytes,(uint64_t)b.payload_bound_bytes);return 1;}
   if(a.lhs_read_rounds!=b.lhs_read_rounds) {fprintf(stderr,"field lhs_read_rounds differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.lhs_read_rounds,(uint64_t)b.lhs_read_rounds);return 1;}
   if(a.rhs_read_rounds!=b.rhs_read_rounds) {fprintf(stderr,"field rhs_read_rounds differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.rhs_read_rounds,(uint64_t)b.rhs_read_rounds);return 1;}
   if(a.operand_read_bytes!=b.operand_read_bytes) {fprintf(stderr,"field operand_read_bytes differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.operand_read_bytes,(uint64_t)b.operand_read_bytes);return 1;}
   if(a.frame_count!=b.frame_count) {fprintf(stderr,"field frame_count differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.frame_count,(uint64_t)b.frame_count);return 1;}
   if(a.array_stream_cycles!=b.array_stream_cycles) {fprintf(stderr,"field array_stream_cycles differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.array_stream_cycles,(uint64_t)b.array_stream_cycles);return 1;}
   if(a.service_estimate!=b.service_estimate) {fprintf(stderr,"field service_estimate differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.service_estimate,(uint64_t)b.service_estimate);return 1;}
   if(a.ps_control!=b.ps_control) {fprintf(stderr,"field ps_control differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.ps_control,(uint64_t)b.ps_control);return 1;}
   if(a.ia_slots!=b.ia_slots) {fprintf(stderr,"field ia_slots differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.ia_slots,(uint64_t)b.ia_slots);return 1;}
   if(a.slice_rows!=b.slice_rows) {fprintf(stderr,"field slice_rows differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.slice_rows,(uint64_t)b.slice_rows);return 1;}
   if(a.predicted_resident_frames!=b.predicted_resident_frames) {fprintf(stderr,"field predicted_resident_frames differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.predicted_resident_frames,(uint64_t)b.predicted_resident_frames);return 1;}
   if(a.estimated_record_bytes!=b.estimated_record_bytes) {fprintf(stderr,"field estimated_record_bytes differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.estimated_record_bytes,(uint64_t)b.estimated_record_bytes);return 1;}
   if(a.literal_record_bytes!=b.literal_record_bytes) {fprintf(stderr,"field literal_record_bytes differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.literal_record_bytes,(uint64_t)b.literal_record_bytes);return 1;}
   if(!a.candidates_evaluated||a.candidates_evaluated>b.candidates_evaluated) {fprintf(stderr,"candidate count exceeds the general search at %u\n",i);return 1;}
   if(a.micro_commands!=b.micro_commands) {fprintf(stderr,"field micro_commands differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.micro_commands,(uint64_t)b.micro_commands);return 1;}
   if(a.weight_shift_rows!=b.weight_shift_rows) {fprintf(stderr,"field weight_shift_rows differs at %u: %" PRIu64 " / %" PRIu64 "\n",i,(uint64_t)a.weight_shift_rows,(uint64_t)b.weight_shift_rows);return 1;}
   if(a.ia_bytes!=b.ia_bytes||a.pool_bytes!=b.pool_bytes||a.ia_bank_count!=b.ia_bank_count||
      a.raw_safe_is_mode!=b.raw_safe_is_mode||a.raw_safe_ps_control!=b.raw_safe_ps_control||
      a.raw_safe_slice_rows!=b.raw_safe_slice_rows||a.raw_safe_ia_bank_count!=b.raw_safe_ia_bank_count||
      a.raw_safe_ia_bytes!=b.raw_safe_ia_bytes||a.raw_safe_pool_bytes!=b.raw_safe_pool_bytes) {
       fprintf(stderr,"memory or RAW executable fields differ at %u\n",i);return 1;
   }
   ++accepted;
  }
  ++checks;
 }
 printf("{\"passed\":true,\"request_checks\":%u,\"accepted_requests\":%u,\"fields_per_request\":42,\"candidate_count_checks\":%u}\n",checks,accepted,accepted);
 return 0;
}
