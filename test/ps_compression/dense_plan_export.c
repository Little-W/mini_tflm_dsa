/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include "dsa_accel.c"

#ifndef DENSE_SWEEP_BUS_WIDTH
#error "Include the selected simulator's generated hardware_profile.h"
#endif
#define DENSE_SWEEP_LITERAL_BOUND ((DENSE_SWEEP_PS_CAPS & DSA_PS_CAP_LITERAL_BOUND) != 0u)

enum { SCHEDULE_FIELDS = 23, CANDIDATE_FIELDS = 38 };
static unsigned char *arena;
static uint32_t weight_bytes;

void dsa_mmio_write(uint32_t address, uint32_t value)
{
    (void)address; (void)value;
    abort();
}

uint32_t dsa_mmio_read(uint32_t address)
{
    switch (address - DSA_MMIO_BASE) {
    case NPU_REG_ID: return 0x4e505531u;
    case NPU_REG_CONFIG_ABI: return 2u;
    case NPU_REG_MATRIX_CAPS: return (DENSE_SWEEP_SIZE << 24) |
        (DENSE_SWEEP_PS_FRAME_COUNT << 16) | (DENSE_SWEEP_IA_CACHE_BLOCKS << 8) | 7u;
    case NPU_REG_MATRIX_PS_ROWS: return DENSE_SWEEP_MATRIX_PS_ROWS;
    case NPU_REG_MATRIX_OUTPUT_BANKS: return DENSE_SWEEP_MATRIX_OUTPUT_BANKS;
    case NPU_REG_DMA_MAX_BYTES: return DENSE_SWEEP_DMA_MAX_BYTES;
    case NPU_REG_AXI_DATA_BITS: return DENSE_SWEEP_BUS_WIDTH;
    case NPU_REG_CONV_CAPS: return (DSA_CONV_CAP_VERSION << 16) | 7u;
    case NPU_REG_PS_CAPS: return DENSE_SWEEP_PS_CAPS;
    case NPU_REG_PS_POOL_BYTES: return DENSE_SWEEP_PS_POOL_BYTES;
    case NPU_REG_IA_CACHE_BYTES: return DENSE_SWEEP_IA_CACHE_BYTES;
    case NPU_REG_SHARED_TOTAL_BYTES: return DENSE_SWEEP_SHARED_TOTAL_BYTES;
    case NPU_REG_SHARED_BANK_BYTES: return DENSE_SWEEP_SHARED_BANK_BYTES;
    case NPU_REG_IA_BANK_MASK: return DENSE_SWEEP_SHARED_IA_BANK_MASK;
    case NPU_REG_PS_DIRECTORY_ROWS: return DENSE_SWEEP_PS_DIRECTORY_ROWS;
    default: return 0u;
    }
}

static void output_schedule(const dsa_schedule_t *p, uint64_t *output)
{
    uint32_t i = 0u;
#define WRITE(field) output[i++] = p->field
    WRITE(tiling.ia_reuse); WRITE(tiling.w_reuse); WRITE(tiling.row_groups);
    WRITE(tiling.row_tail_tiles); WRITE(tiling.col_groups); WRITE(tiling.col_tail_tiles);
    WRITE(dataflow_mode); WRITE(candidates); WRITE(estimated_cycles);
    WRITE(read_words); WRITE(read_requests); WRITE(write_words); WRITE(write_requests);
    WRITE(compute_cycles); WRITE(ps_payload_bytes); WRITE(ps_control);
    WRITE(ia_bank_count); WRITE(ia_cache_bytes); WRITE(ps_pool_bytes);
    WRITE(frame_rows); WRITE(predicted_resident_frames);
    WRITE(read_beats); WRITE(write_beats);
#undef WRITE
    assert(i == SCHEDULE_FIELDS);
}

static void initialize_arena(void)
{
    if (arena) return;
    arena = mmap(0, 2u << 20, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    assert(arena != MAP_FAILED && (uintptr_t)arena <= UINT32_MAX - (2u << 20));
    int32_t *multiplier = (int32_t *)(arena + 0x110000u);
    int32_t *shift = (int32_t *)(arena + 0x120000u);
    for (uint32_t i = 0u; i < 1024u; ++i) {
        multiplier[i] = 1073741824;
        shift[i] = -8;
    }
}

int dense_set_weights(const void *source, uint32_t bytes)
{
    initialize_arena();
    if (!source || !bytes || bytes > 0x100000u) return 0;
    memcpy(arena, source, bytes);
    weight_bytes = bytes;
    return 1;
}

int dense_set_parameters(const void *bias, uint32_t bias_bytes,
    const void *multiplier, uint32_t multiplier_bytes,
    const void *shift, uint32_t shift_bytes)
{
    initialize_arena();
    if (!bias || !multiplier || !shift || !bias_bytes || !multiplier_bytes ||
        multiplier_bytes != shift_bytes || bias_bytes > 0x10000u ||
        multiplier_bytes > 0x10000u || ((bias_bytes | multiplier_bytes) & 3u)) return 0;
    memcpy(arena+0x100000u,bias,bias_bytes);
    memcpy(arena+0x110000u,multiplier,multiplier_bytes);
    memcpy(arena+0x120000u,shift,shift_bytes);
    return 1;
}

int dense_profile_values(uint32_t *output, uint32_t capacity)
{
    dsa_matrix_limits_t limits;
    dsa_schedule_config_t c;
    if (!output || capacity < 19u) return 0;
    dsa_matrix_query(&limits);
    dsa_schedule_init(&c,1u,16u,16u,limits.tile_size,limits.ia_cache_blocks,limits.ps_frame_count);
    dsa_schedule_set_limits(&c,&limits);
    uint32_t i=0u;
    output[i++]=c.axi_data_bits;output[i++]=c.dma_max_bytes;
    output[i++]=c.read_beat_cycles;output[i++]=c.write_beat_cycles;
    output[i++]=c.read_request_cycles;output[i++]=c.write_request_cycles;
    output[i++]=c.shared_total_bytes;output[i++]=c.shared_bank_bytes;
    output[i++]=c.shared_ia_bank_mask;output[i++]=c.ps_directory_rows;
    output[i++]=c.ps_caps;output[i++]=c.ia_cache_bytes;output[i++]=c.ps_pool_bytes;
    output[i++]=c.output_banks_s8;output[i++]=c.output_banks_s16;
    output[i++]=DENSE_SWEEP_RAM_READ_FIRST_LATENCY;
    output[i++]=DENSE_SWEEP_RAM_FIXED_LAT;
    output[i++]=DSA_SCHEDULE_IA_TILE_SETUP_CYCLES;
    output[i++]=DSA_SCHEDULE_QUANT_GROUP_SETUP_CYCLES;
    assert(i==19u);
    return 1;
}

uint32_t dense_weight_bound(const int32_t *input)
{
    assert(arena && weight_bytes);
    return dsa_ps_bound_s8(arena,(uint32_t)input[2],(uint32_t)input[1],
        (uint32_t)input[1],(uint32_t)input[7],input[3],input[4]);
}

uint32_t dense_prepared_literal_bytes(void)
{
    return dsa_schedule_cache[0].configuration.ps_literal_bytes;
}

/* Input fields: rows, depth, channels, input/filter offset, per-channel,
 * bias, packed weights, packed input, forced RAW storage. */
int export_dense_candidates(const int32_t *input, uint64_t *selected,
                            uint64_t *records, uint32_t capacity)
{
    initialize_arena();
    uint64_t required_bytes=input[7] ?
        (uint64_t)(((uint32_t)input[2]+15u)/16u)*(((uint32_t)input[1]+15u)/16u)*256u :
        (uint64_t)(uint32_t)input[2]*(uint32_t)input[1];
    if (required_bytes != weight_bytes) return -1002;
    memset(dsa_schedule_cache, 0, sizeof(dsa_schedule_cache));
    dsa_schedule_cache_next = 0u;
    dsa_set_ps_force_raw((uint32_t)input[9]);
    uint32_t base = (uint32_t)(uintptr_t)arena;
    dsa_prepared_matmul_s8_config_t prepared_config = {0};
    dsa_prepared_t prepared;
    prepared_config.rows = input[0];
    prepared_config.depth = prepared_config.input_stride = prepared_config.filter_stride = input[1];
    prepared_config.channels = prepared_config.output_stride = input[2];
    prepared_config.input_offset = input[3]; prepared_config.filter_offset = input[4];
    prepared_config.per_channel = input[5];
    prepared_config.bias_base = input[6] ? base + 0x100000u : 0u;
    prepared_config.rhs_tile_packed = input[7]; prepared_config.lhs_tile_packed = input[8];
    prepared_config.filter_base = base;
    prepared_config.multiplier_base = base + 0x110000u;
    prepared_config.shift_base = base + 0x120000u;
    prepared_config.multiplier = *(const int32_t *)(arena + 0x110000u);
    prepared_config.shift = *(const int32_t *)(arena + 0x120000u);
    prepared_config.activation_min = -128; prepared_config.activation_max = 127;
    prepared_config.dataflow_mode = DSA_SCHEDULE_AUTO;
    uint32_t status = dsa_prepare_matmul_s8(&prepared, &prepared_config);
    if (status != DSA_SUCCESS) return -(int)status;
    assert(dsa_schedule_cache_next == 1u && dsa_schedule_cache[0].valid);
    const dsa_schedule_config_t *c = &dsa_schedule_cache[0].configuration;
    const dsa_schedule_t *chosen = &dsa_schedule_cache[0].schedule;
    assert(prepared.ps_control == chosen->ps_control &&
           prepared.ia_bank_count == chosen->ia_bank_count);
    assert(c->ps_literal_bytes == ((DENSE_SWEEP_LITERAL_BOUND && !input[9]) ?
                                  dense_weight_bound(input) : 0u));
    output_schedule(chosen, selected);

    gempact_device_request_t request = {0};
    request.rows = c->rows; request.reduction = c->depth; request.cols = c->cols;
    request.size = c->size; request.frames = c->ps_frames;
    request.is_supported = c->allow_is; request.per_channel = c->per_channel;
    request.lhs_element_bytes = c->lhs_bytes; request.compact_mode_mask = c->compact_mode_mask;
    request.frame_capable = (c->ps_caps & DSA_PS_CAP_FRAME_SCHEDULE) != 0u;
    request.adaptive = request.frame_capable && !c->force_raw && !(c->ps_caps & DSA_PS_CAP_RAW_ONLY);
    request.estimated_record_bytes = DSA_PLANNER_RECORD_BYTES;
    request.literal_record_bytes = request.adaptive ?
        gempact_literal_record_bytes(c->depth,c->source_s8,c->lhs_offset,c->rhs_offset) : 64u;
    if (request.adaptive && (c->ps_caps&DSA_PS_CAP_LITERAL_BOUND) && c->ps_literal_bytes)
        request.literal_record_bytes=c->ps_literal_bytes;
    request.micro_setup_cycles = DSA_PLANNER_MICRO_CYCLES;
    request.directory_rows = c->ps_directory_rows;
    uint64_t a_words, a_requests, b_words, b_requests;
    dsa_schedule_operand(c, c->rows, c->lhs_bytes, c->lhs_stride, c->lhs_address,
        1, c->lhs_tile_packed, &a_words, &a_requests);
    dsa_schedule_operand(c, c->cols, c->rhs_bytes, c->rhs_stride, c->rhs_address,
        1, c->rhs_tile_packed, &b_words, &b_requests);
    uint32_t count = 0u;
    int found = 0;
    dsa_schedule_t best = {0};
    const uint32_t banks=c->shared_total_bytes/c->shared_bank_bytes;
    for (uint32_t ia = 1u; ia < banks; ++ia) {
        if (!(c->shared_ia_bank_mask & (1u<<ia))) continue;
        gempact_device_request_t q = request;
        q.ia_bank_count = ia; q.ps_bank_count = banks - ia;
        q.ia_bytes = ia * c->shared_bank_bytes;
        q.pool_bytes = c->shared_total_bytes - q.ia_bytes;
        for (uint32_t mode = 0u; mode < 2u; ++mode) {
            uint32_t slots = q.ia_bytes / 512u;
            if (q.compact_mode_mask & (1u << mode)) slots *= 2u;
            uint32_t ct = gempact_ceil_div(mode ? c->rows : c->cols, 16u);
            for (uint32_t r = 1u; r <= slots / 2u; r *= 2u)
                for (uint32_t w = 1u; w <= gempact_window_limit(&q, ct); ++w)
                    for (uint32_t path = 0u; path < 4u; ++path)
                        for (uint32_t raw = request.adaptive ? 0u : 1u; raw <= 1u; ++raw) {
                            gempact_dispatch_t p = {0};
                            dsa_schedule_t score;
                            if (!gempact_device_candidate(&q, mode, r, w, path, raw, &p)) continue;
                            dsa_schedule_memory_score(c, &q, &p, a_words, a_requests,
                                b_words, b_requests, &score);
                            if (!raw && (c->ps_caps&DSA_PS_CAP_LITERAL_BOUND)) {
                                if (c->ps_literal_bytes==32u) score.ps_control|=DSA_PS_CTRL_BOUND_S16;
                                if (c->ps_literal_bytes==48u) score.ps_control|=DSA_PS_CTRL_BOUND_S24;
                            }
                            uint32_t admitted = raw || p.adaptive_active;
                            if (admitted && (!found || dsa_schedule_better(&score, &best))) {
                                best = score; found = 1;
                            }
                            if (count >= capacity) return -1000;
                            uint64_t *out = records + count * CANDIDATE_FIELDS;
                            output_schedule(&score, out);
                            uint32_t i = SCHEDULE_FIELDS;
                            out[i++] = path; out[i++] = raw; out[i++] = p.adaptive_active;
                            out[i++] = admitted; out[i++] = p.ia_slots;
                            out[i++] = p.literal_record_bytes; out[i++] = p.estimated_record_bytes;
                            out[i++] = p.micro_commands; out[i++] = p.frame_count;
                            out[i++] = p.array_stream_cycles; out[i++] = p.weight_shift_rows;
                            out[i++] = p.operand_read_bytes;
                            out[i++] = p.lhs_read_rounds; out[i++] = p.rhs_read_rounds;
                            out[i++] = (uint64_t)(mode ? c->cols : c->rows) * ct *
                                (gempact_ceil_div(c->depth, 16u) - 1u);
                            assert(i == CANDIDATE_FIELDS);
                            ++count;
                        }
        }
    }
    assert(found && !dsa_schedule_better(&best, chosen) && !dsa_schedule_better(chosen, &best));
    assert(chosen->read_words==chosen->read_beats*(c->axi_data_bits/32u));
    assert(chosen->write_words==chosen->write_beats*(c->axi_data_bits/32u));
    return (int)count;
}
