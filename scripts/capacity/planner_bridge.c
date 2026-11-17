/* SPDX-License-Identifier: Apache-2.0 */
#include "gempact_tiling.h"

/* Fixed-width arrays keep the host interface independent of C structure ABI. */
int capacity_plan_device(const uint32_t *input, uint64_t *output)
{
    gempact_device_request_t q = {0};
    gempact_dispatch_t p;gempact_shared_memory_t memory;gempact_im2col_geometry_t geometry;
    uint32_t i = 0;
#define READ(name) q.name = input[i++]
    READ(rows); READ(reduction); READ(cols); READ(size); READ(ia_bytes);
    READ(frames); READ(pool_bytes); READ(req_r); READ(req_w); READ(mode);
    READ(is_supported); READ(per_channel); READ(lhs_element_bytes);
    READ(compact_mode_mask); READ(frame_capable); READ(adaptive);
    READ(estimated_record_bytes); READ(literal_record_bytes); READ(micro_setup_cycles);
    READ(im2col_source_bytes); READ(im2col_pixel_channels); READ(im2col_stage_bytes_per_position);
    READ(im2col_base_fraction_q8); READ(im2col_cache_bytes); READ(directory_rows);
    READ(ia_bank_count); READ(ps_bank_count);
#undef READ
    memory.total_bytes=input[i++];memory.bank_bytes=input[i++];
    memory.ia_bank_mask=input[i++];memory.directory_rows=input[i++];
    geometry.input_bytes=input[i++];geometry.input_channels=input[i++];geometry.group_channels=input[i++];
    geometry.kernel_h=input[i++];geometry.kernel_w=input[i++];geometry.stride_w=input[i++];
    geometry.source_bytes=input[i++];geometry.cache_bytes=input[i++];
    if(geometry.source_bytes&&!gempact_set_im2col_geometry(&q,&geometry)) return 0;
    if(memory.total_bytes) {if(!gempact_plan_shared(&q,&memory,&p)) return 0;}
    else if (!gempact_plan_device(&q, &p)) return 0;
    i = 0;
#define WRITE(name) output[i++] = p.name
    WRITE(tiling.ia_reuse); WRITE(tiling.w_reuse); WRITE(tiling.row_groups);
    WRITE(tiling.row_tail_tiles); WRITE(tiling.col_groups); WRITE(tiling.col_tail_tiles);
    WRITE(raw_safe.ia_reuse); WRITE(raw_safe.w_reuse); WRITE(raw_safe.row_groups);
    WRITE(raw_safe.row_tail_tiles); WRITE(raw_safe.col_groups); WRITE(raw_safe.col_tail_tiles);
    WRITE(is_mode); WRITE(frame_rows); WRITE(adaptive_active);
    WRITE(reduction); WRITE(lhs_element_bytes); WRITE(bus_bytes);
    WRITE(payload_bound_bytes); WRITE(lhs_read_rounds); WRITE(rhs_read_rounds);
    WRITE(operand_read_bytes); WRITE(frame_count); WRITE(array_stream_cycles);
    WRITE(service_estimate); WRITE(ps_control); WRITE(ia_slots); WRITE(slice_rows);
    WRITE(predicted_resident_frames); WRITE(estimated_record_bytes);
    WRITE(literal_record_bytes); WRITE(candidates_evaluated);
    WRITE(micro_commands); WRITE(weight_shift_rows);
    WRITE(ia_bank_count); WRITE(ia_bytes); WRITE(pool_bytes);
    WRITE(raw_safe_is_mode); WRITE(raw_safe_ps_control); WRITE(raw_safe_slice_rows);
    WRITE(raw_safe_ia_bank_count); WRITE(raw_safe_ia_bytes); WRITE(raw_safe_pool_bytes);
#undef WRITE
    return 1;
}
