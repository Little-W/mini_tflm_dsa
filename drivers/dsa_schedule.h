/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_SCHEDULE_H
#define DSA_SCHEDULE_H

#include <stdint.h>
#include "gempact_tiling.h"
#include "dsa_memory.h"

#define DSA_SCHEDULE_WS 0u
#define DSA_SCHEDULE_IS 1u
#define DSA_SCHEDULE_AUTO 2u

#ifndef DSA_PS_STORAGE_ROWS
#define DSA_PS_STORAGE_ROWS 0u
#endif
#ifndef DSA_SCHEDULE_AXI_DATA_BITS
#ifdef NPU_CONFIG_NPU_AXI_DATA_WIDTH
#define DSA_SCHEDULE_AXI_DATA_BITS NPU_CONFIG_NPU_AXI_DATA_WIDTH
#else
#define DSA_SCHEDULE_AXI_DATA_BITS 32u
#endif
#endif
#ifndef DSA_SCHEDULE_READ_BEAT_CYCLES
#define DSA_SCHEDULE_READ_BEAT_CYCLES 2u
#endif
#ifndef DSA_SCHEDULE_WRITE_BEAT_CYCLES
#define DSA_SCHEDULE_WRITE_BEAT_CYCLES 1u
#endif
#ifndef DSA_SCHEDULE_READ_REQUEST_CYCLES
#define DSA_SCHEDULE_READ_REQUEST_CYCLES 1u
#endif
#ifndef DSA_SCHEDULE_WRITE_REQUEST_CYCLES
#define DSA_SCHEDULE_WRITE_REQUEST_CYCLES 3u
#endif
#ifndef DSA_SCHEDULE_MERGE_CONTIGUOUS_ROWS
#define DSA_SCHEDULE_MERGE_CONTIGUOUS_ROWS 1u
#endif

/* Dimensions use A[rows,depth], B[cols,depth], C[rows,cols].
 * Strides and address residues affect transfer estimates, not tensor layout.
 * AUTO enumerates both supported directions; explicit directions stay fixed.
 * Requested reuse factors are upper bounds, with zero selecting the capacity.
 */
typedef struct {
    uint32_t rows, depth, cols, size, ia_blocks, ps_frames;
    uint32_t ps_storage_rows, ps_pool_bytes, flow, requested_r, requested_w;
    uint32_t lhs_bytes, rhs_bytes, output_bytes;
    uint32_t lhs_stride, rhs_stride, output_stride;
    uint32_t lhs_address, rhs_address, output_address;
    uint32_t allow_is, per_channel, has_bias, spatial;
    uint32_t read_beat_cycles, write_beat_cycles;
    uint32_t read_request_cycles, write_request_cycles;
    uint32_t merge_contiguous_rows;
    uint32_t lhs_tile_packed, rhs_tile_packed, output_banks_s8, output_banks_s16;
    uint32_t dma_max_bytes, axi_data_bits;
    uint32_t ps_caps, ia_cache_bytes, shared_total_bytes, shared_bank_bytes;
    uint32_t shared_ia_bank_mask, ps_directory_rows, compact_mode_mask, force_raw;
    uint32_t source_s8;
    int32_t lhs_offset, rhs_offset;
    gempact_im2col_geometry_t im2col;
    uint32_t im2col_input_width,im2col_output_width,im2col_stride_h;
} dsa_schedule_config_t;

typedef struct {
    gempact_tiling_t tiling;
    uint32_t dataflow_mode, candidates;
    uint64_t estimated_cycles, read_words, read_requests, write_words;
    uint64_t write_requests, compute_cycles, ps_payload_bytes;
    uint64_t read_beats, write_beats;
    uint32_t ps_control, ia_bank_count, ia_cache_bytes, ps_pool_bytes;
    uint32_t memory_policy_valid, frame_rows, predicted_resident_frames;
} dsa_schedule_t;

static inline uint64_t dsa_schedule_add(uint64_t a, uint64_t b)
{
    return UINT64_MAX-a<b ? UINT64_MAX : a+b;
}

static inline uint64_t dsa_schedule_mul(uint64_t a, uint64_t b)
{
    if ((a|b)<=UINT32_MAX) return a*b;
    return a && b>UINT64_MAX/a ? UINT64_MAX : a*b;
}

static inline uint64_t dsa_schedule_max(uint64_t a, uint64_t b)
{
    return a>b ? a:b;
}

static inline uint32_t dsa_schedule_min(uint32_t a, uint32_t b)
{
    return a<b ? a:b;
}

static inline void dsa_schedule_init(dsa_schedule_config_t *c,
    uint32_t rows, uint32_t depth, uint32_t cols,
    uint32_t size, uint32_t ia_blocks, uint32_t ps_frames)
{
    dsa_schedule_config_t empty = {0};
    *c=empty;
    c->rows=rows; c->depth=depth; c->cols=cols;
    c->size=size; c->ia_blocks=ia_blocks; c->ps_frames=ps_frames;
    c->flow=DSA_SCHEDULE_AUTO; c->allow_is=1u;
    c->lhs_bytes=c->rhs_bytes=c->output_bytes=1u;
    c->lhs_stride=c->rhs_stride=depth; c->output_stride=cols;
    c->read_beat_cycles=DSA_SCHEDULE_READ_BEAT_CYCLES;
    c->write_beat_cycles=DSA_SCHEDULE_WRITE_BEAT_CYCLES;
    c->read_request_cycles=DSA_SCHEDULE_READ_REQUEST_CYCLES;
    c->write_request_cycles=DSA_SCHEDULE_WRITE_REQUEST_CYCLES;
    c->merge_contiguous_rows=DSA_SCHEDULE_MERGE_CONTIGUOUS_ROWS;
    c->axi_data_bits=DSA_SCHEDULE_AXI_DATA_BITS;
    c->dma_max_bytes=256u*(c->axi_data_bits/8u);
}

/* Traffic words retain their 32-bit unit; AXI beats use the discovered bus
 * width. Each unaligned logical row adds the DMA realignment beat. Read
 * request estimates precede 4 KiB splitting of individual descriptors. */
static inline uint32_t dsa_schedule_bus_bytes(const dsa_schedule_config_t *c)
{
    return (c->axi_data_bits ? c->axi_data_bits:DSA_SCHEDULE_AXI_DATA_BITS)/8u;
}

static inline uint32_t dsa_schedule_dma_bytes(const dsa_schedule_config_t *c)
{
    return c->dma_max_bytes ? c->dma_max_bytes:256u*dsa_schedule_bus_bytes(c);
}

static inline void dsa_schedule_operand(const dsa_schedule_config_t *c,
    uint32_t rows, uint32_t bytes, uint32_t stride, uint32_t address,
    int merge, int packed, uint64_t *words, uint64_t *requests)
{
    uint64_t count=0, request_count=0;
    uint32_t full=c->depth/c->size, tail=c->depth%c->size;
    uint32_t beat_bytes=dsa_schedule_bus_bytes(c);
    uint32_t max_bytes=dsa_schedule_dma_bytes(c), max_beats=max_bytes/beat_bytes;
    if (packed) {
        uint64_t kt=full+(tail!=0u),row_bytes=(uint64_t)c->size*bytes;
        uint64_t row_beats=(row_bytes+beat_bytes-1u)/beat_bytes;
        if (address&(beat_bytes-1u)) {
            ++row_beats;
            *words=(uint64_t)rows*kt*row_beats*(beat_bytes/4u);
            *requests=(uint64_t)rows*kt*((row_beats+max_beats-1u)/max_beats);
        } else {
            *words=(uint64_t)rows*kt*row_beats*(beat_bytes/4u);
            *requests=kt*((uint64_t)(rows/c->size)*((c->size*row_bytes+max_bytes-1u)/max_bytes)+
                         ((rows%c->size)*row_bytes+max_bytes-1u)/max_bytes);
        }
        return;
    }
    if (merge && c->merge_contiguous_rows && c->depth<=c->size &&
        (uint64_t)stride==(uint64_t)c->depth*bytes &&
        (uint64_t)c->size*c->depth*bytes<=256u*beat_bytes &&
        (c->depth*bytes)%beat_bytes==0u && address%beat_bytes==0u) {
        uint64_t row_bytes=(uint64_t)c->depth*bytes;
        uint64_t block_bytes=(uint64_t)c->size*row_bytes;
        uint64_t tail_bytes=(uint64_t)(rows%c->size)*row_bytes;
        *words=dsa_schedule_mul(rows,row_bytes)/4u;
        *requests=(uint64_t)(rows/c->size)*((block_bytes+max_bytes-1u)/max_bytes)+
                  (tail_bytes+max_bytes-1u)/max_bytes;
        return;
    }
    for (uint32_t i=0;i<beat_bytes;++i) {
        uint64_t times=rows/beat_bytes+(i<rows%beat_bytes);
        uint32_t row_residue=(address+i*stride)&(beat_bytes-1u);
        uint64_t per_row=0u,per_requests=0u;
        for (uint32_t j=0;j<beat_bytes;++j) {
            uint64_t tiles=full/beat_bytes+(j<full%beat_bytes);
            uint32_t residue=(row_residue+j*c->size*bytes)&(beat_bytes-1u);
            uint32_t beats=gempact_ceil_div(c->size*bytes,beat_bytes)+(residue!=0u);
            per_row+=tiles*beats;
            per_requests+=tiles*gempact_ceil_div(beats,max_beats);
        }
        if (tail) {
            uint32_t residue=(row_residue+full*c->size*bytes)&(beat_bytes-1u);
            uint32_t beats=gempact_ceil_div(tail*bytes,beat_bytes)+(residue!=0u);
            per_row+=beats;
            per_requests+=gempact_ceil_div(beats,max_beats);
        }
        count=dsa_schedule_add(count,dsa_schedule_mul(times,per_row));
        request_count=dsa_schedule_add(request_count,dsa_schedule_mul(times,per_requests));
    }
    *words=dsa_schedule_mul(count,beat_bytes/4u);
    *requests=request_count;
}

/* This bound matches npu_top's physical PS admission check, including one
 * spare frame. A single reduction tile never stores intermediate sums.
 */
static inline uint64_t dsa_schedule_ps_bytes(const dsa_schedule_config_t *c,
    uint32_t stream_rows, uint32_t stream_cols, uint32_t r, uint32_t w)
{
    uint32_t tr=gempact_ceil_div(stream_rows,c->size);
    uint32_t tc=gempact_ceil_div(stream_cols,c->size);
    if (c->depth<=c->size) return 0u;
    return ((uint64_t)dsa_schedule_min(r,tr)*c->size+c->size-1u)*
           (dsa_schedule_min(w,tc)+1u)*c->size*4u;
}

/* Dense output descriptors have a power-of-two byte length dividing 4 KiB.
 * Count the configured burst limit, the unaligned boundary word, and page
 * splits without iterating over tensor rows. */
static inline uint64_t dsa_schedule_contiguous_writes(uint64_t address,
    uint64_t bytes, uint32_t descriptor_bytes, uint32_t max_bytes, uint32_t beat_bytes)
{
    uint64_t aligned,span,pages,base,split,offset;
    if (!bytes) return 0u;
    aligned=address&~(uint64_t)(beat_bytes-1u);
    span=descriptor_bytes+((address&(beat_bytes-1u))!=0u ? beat_bytes:0u);
    base=(span+max_bytes-1u)/max_bytes;
    offset=descriptor_bytes-(aligned%descriptor_bytes);
    split=(offset+max_bytes-1u)/max_bytes+(span-offset+max_bytes-1u)/max_bytes;
    pages=(aligned+bytes+(span-descriptor_bytes)-1u)/4096u-aligned/4096u;
    return (bytes/descriptor_bytes)*base+pages*(split-base);
}

static inline uint32_t dsa_schedule_dense_write_bytes(uint64_t group_bytes,
                                                       uint32_t row_bytes, uint32_t beat_bytes)
{
    if (beat_bytes==8u && group_bytes%2048u==0u) return 2048u;
    if (group_bytes%1024u==0u) return 1024u;
    if (group_bytes%512u==0u) return 512u;
    if (group_bytes%256u==0u) return 256u;
    return row_bytes;
}

static inline uint64_t dsa_schedule_write_traffic(const dsa_schedule_config_t *c,
    uint32_t mode, uint32_t r, uint32_t w, uint64_t *beats)
{
    uint32_t chunk=1u;
    uint32_t max_bytes=dsa_schedule_dma_bytes(c);
    uint32_t beat_bytes=dsa_schedule_bus_bytes(c);
    uint32_t banks=c->output_banks_s8 ? c->output_banks_s8:
        dsa_schedule_min(32u,c->ps_frames*(c->ia_blocks<2u?1u:c->ia_blocks/2u));
    if (!mode && c->allow_is && c->size==16u && c->output_bytes==1u &&
        r<=16u && c->output_stride==c->cols) {
        uint32_t row_tiles=dsa_schedule_min(r,gempact_ceil_div(c->rows,16u));
        if (c->rows>1u && c->rows<16u && w>=2u && c->cols>=32u && banks>=2u)
            chunk=2u;
        else for (uint32_t x=2u;x<=16u;x<<=1u)
            if (x<=w && row_tiles*x<=banks && c->cols>=x*16u) chunk=x;
        if (chunk>=2u && c->cols%(chunk*16u)==0u) {
            if (c->cols==chunk*16u) {
                uint32_t full_rows=c->rows/(r*16u)*(r*16u);
                uint64_t full_bytes=(uint64_t)full_rows*c->cols;
                uint64_t tail_bytes=(uint64_t)(c->rows-full_rows)*c->cols;
                uint32_t full_len=dsa_schedule_dense_write_bytes((uint64_t)r*16u*c->cols,c->cols,beat_bytes);
                uint32_t tail_len=dsa_schedule_dense_write_bytes(tail_bytes,c->cols,beat_bytes);
                *beats=full_bytes/full_len*(full_len/beat_bytes+(c->output_address%beat_bytes!=0u))+
                    tail_bytes/tail_len*(tail_len/beat_bytes+((c->output_address+full_bytes)%beat_bytes!=0u));
                return dsa_schedule_contiguous_writes(c->output_address,full_bytes,full_len,max_bytes,beat_bytes)+
                    dsa_schedule_contiguous_writes((uint64_t)c->output_address+full_bytes,tail_bytes,tail_len,max_bytes,beat_bytes);
            }
            *beats=(uint64_t)c->rows*c->cols/(chunk*16u)*
                (chunk*16u/beat_bytes+(c->output_address%beat_bytes!=0u));
            return dsa_schedule_contiguous_writes(c->output_address,
                (uint64_t)c->rows*c->cols,chunk*16u,max_bytes,beat_bytes);
        }
        chunk=1u;
    }
    if (mode && c->size==16u && c->output_bytes==1u &&
        r>=2u && r<=16u && (r&(r-1u))==0u && r<=banks &&
        c->cols%(16u*r)==0u && c->output_address%(16u*r)==0u &&
        c->output_stride%(16u*r)==0u) chunk=r;
    {
        uint32_t columns=c->size*chunk,full=c->cols/columns,tail=c->cols%columns;
        uint64_t requests=0u,beat_count=0u;
        uint32_t max_beats=max_bytes/beat_bytes;
        for (uint32_t i=0;i<beat_bytes;++i) {
            uint64_t times=c->rows/beat_bytes+(i<c->rows%beat_bytes);
            uint32_t row_residue=(c->output_address+i*c->output_stride)&(beat_bytes-1u);
            uint64_t per_row=0u,per_requests=0u;
            for (uint32_t j=0;j<beat_bytes;++j) {
                uint64_t tiles=full/beat_bytes+(j<full%beat_bytes);
                uint32_t residue=(row_residue+j*columns*c->output_bytes)&(beat_bytes-1u);
                uint32_t length=gempact_ceil_div(columns*c->output_bytes,beat_bytes)+(residue!=0u);
                per_row+=tiles*length;
                per_requests+=tiles*gempact_ceil_div(length,max_beats);
            }
            if (tail) {
                uint32_t residue=(row_residue+full*columns*c->output_bytes)&(beat_bytes-1u);
                uint32_t length=gempact_ceil_div(tail*c->output_bytes,beat_bytes)+(residue!=0u);
                per_row+=length;
                per_requests+=gempact_ceil_div(length,max_beats);
            }
            beat_count=dsa_schedule_add(beat_count,dsa_schedule_mul(times,per_row));
            requests=dsa_schedule_add(requests,dsa_schedule_mul(times,per_requests));
        }
        *beats=beat_count;
        return requests;
    }
}

static inline uint64_t dsa_schedule_writes(const dsa_schedule_config_t *c,
    uint32_t mode, uint32_t r, uint32_t w)
{
    uint64_t beats;
    return dsa_schedule_write_traffic(c,mode,r,w,&beats);
}

static inline int dsa_schedule_better(const dsa_schedule_t *a,
                                       const dsa_schedule_t *b)
{
    uint64_t ak[7]={a->estimated_cycles,a->read_words,a->read_requests,
                   a->compute_cycles,a->write_requests,a->ps_payload_bytes,a->dataflow_mode};
    uint64_t bk[7]={b->estimated_cycles,b->read_words,b->read_requests,
                   b->compute_cycles,b->write_requests,b->ps_payload_bytes,b->dataflow_mode};
    for (uint32_t i=0;i<7u;++i) {
        if (ak[i]!=bk[i]) return ak[i]<bk[i];
    }
    return 0;
}

static inline int dsa_schedule_plan_legacy(const dsa_schedule_config_t *c,
                                     dsa_schedule_t *out)
{
    uint32_t rcap,wcap,candidates=0;
    uint64_t a_words,a_requests,b_words,b_requests;
    int found=0;
    if (out) {dsa_schedule_t empty={0};*out=empty;}
    if (!c || !out || !c->rows || !c->depth || !c->cols ||
        !c->size || (c->size&(c->size-1u)) || c->size>256u ||
        !c->ia_blocks || !c->ps_frames || c->flow>DSA_SCHEDULE_AUTO ||
        c->lhs_bytes<1u || c->lhs_bytes>2u || c->rhs_bytes<1u || c->rhs_bytes>2u ||
        c->output_bytes<1u || c->output_bytes>2u ||
        c->per_channel>1u || c->has_bias>1u ||
        c->lhs_tile_packed>1u || c->rhs_tile_packed>1u ||
        ((c->lhs_tile_packed || c->rhs_tile_packed) && c->size!=16u) ||
        (c->spatial && c->lhs_tile_packed) || !c->read_beat_cycles ||
        !c->write_beat_cycles ||
        (c->axi_data_bits && c->axi_data_bits!=32u && c->axi_data_bits!=64u) ||
        (c->dma_max_bytes && (c->dma_max_bytes<dsa_schedule_bus_bytes(c) ||
         c->dma_max_bytes>256u*dsa_schedule_bus_bytes(c) ||
         (c->dma_max_bytes&(c->dma_max_bytes-1u)))) ||
        (c->flow==DSA_SCHEDULE_IS && !c->allow_is)) return 0;
    rcap=c->ia_blocks<2u ? 1u:c->ia_blocks/2u;
    wcap=c->ps_frames;
    if (c->requested_r && c->requested_r<rcap) rcap=c->requested_r;
    if (c->requested_w && c->requested_w<wcap) wcap=c->requested_w;
    dsa_schedule_operand(c,c->rows,c->lhs_bytes,c->lhs_stride,c->lhs_address,
                         !c->spatial,c->lhs_tile_packed,&a_words,&a_requests);
    dsa_schedule_operand(c,c->cols,c->rhs_bytes,c->rhs_stride,c->rhs_address,
                         1,c->rhs_tile_packed,&b_words,&b_requests);
    for (uint32_t mode=0;mode<2u;++mode) {
        uint32_t sr=mode ? c->cols:c->rows, sc=mode ? c->rows:c->cols;
        uint32_t tr=gempact_ceil_div(sr,c->size),tc=gempact_ceil_div(sc,c->size);
        uint32_t kt=gempact_ceil_div(c->depth,c->size);
        if ((c->flow!=DSA_SCHEDULE_AUTO && c->flow!=mode) || (mode && !c->allow_is)) continue;
        for (uint32_t ri=0;ri<17u;++ri) {
            uint32_t r=ri==16u ? 25u:(1u<<ri);
            if (r>rcap || (r>tr && r/2u>=tr) ||
                (c->output_bytes==2u && c->output_banks_s16 &&
                 r>c->output_banks_s16)) continue;
            for (uint32_t wi=0;wi<17u;++wi) {
                uint32_t w=wi==16u ? 25u:(1u<<wi),rg,cg;
                uint64_t payload,read_cycles,write_cycles,parameter_words,parameter_requests;
                uint64_t stream_words,stream_requests,stream_cycles,stationary_commits;
                uint32_t a_passes,b_passes,parameter_passes;
                dsa_schedule_t candidate={0};
                if (w>wcap || (w>tc && w/2u>=tc)) continue;
                rg=gempact_ceil_div(tr,r); cg=gempact_ceil_div(tc,w);
                if (rg>65535u || cg>65535u) continue;
                payload=dsa_schedule_ps_bytes(c,sr,sc,r,w);
                if ((c->ps_storage_rows && payload>(uint64_t)c->ps_storage_rows*c->size*4u) ||
                    (c->ps_pool_bytes && payload>c->ps_pool_bytes)) continue;
                candidate.tiling.ia_reuse=r; candidate.tiling.w_reuse=w;
                candidate.tiling.row_groups=rg; candidate.tiling.col_groups=cg;
                candidate.tiling.row_tail_tiles=tr-(rg-1u)*r;
                candidate.tiling.col_tail_tiles=tc-(cg-1u)*w;
                candidate.dataflow_mode=mode; candidate.ps_payload_bytes=payload;
                a_passes=mode ? rg:cg; b_passes=mode ? cg:rg;
                parameter_passes=mode || c->cols<=c->size ? 1u:rg;
                {
                    uint32_t beat_bytes=dsa_schedule_bus_bytes(c);
                    uint32_t max_bytes=dsa_schedule_dma_bytes(c);
                    parameter_words=((uint64_t)(c->cols/16u)*(64u/beat_bytes)+
                        gempact_ceil_div((c->cols%16u)*4u,beat_bytes))*(beat_bytes/4u)*
                        parameter_passes*(c->has_bias+2u*c->per_channel);
                    parameter_requests=((uint64_t)(c->cols/16u)*gempact_ceil_div(64u,max_bytes)+
                        gempact_ceil_div((c->cols%16u)*4u,max_bytes))*parameter_passes*
                        (c->has_bias+2u*c->per_channel);
                }
                candidate.read_words=dsa_schedule_add(dsa_schedule_add(
                    dsa_schedule_mul(a_words,a_passes),dsa_schedule_mul(b_words,b_passes)),parameter_words);
                candidate.read_requests=dsa_schedule_add(dsa_schedule_add(
                    dsa_schedule_mul(a_requests,a_passes),dsa_schedule_mul(b_requests,b_passes)),parameter_requests);
                candidate.read_beats=candidate.read_words/(dsa_schedule_bus_bytes(c)/4u);
                candidate.write_requests=dsa_schedule_write_traffic(c,mode,r,w,&candidate.write_beats);
                candidate.write_words=candidate.write_beats*(dsa_schedule_bus_bytes(c)/4u);
                candidate.compute_cycles=dsa_schedule_add(
                    dsa_schedule_mul((uint64_t)sr*tc,kt),
                    dsa_schedule_mul(dsa_schedule_mul((uint64_t)rg*tc,kt),2u*c->size+2u));
                read_cycles=dsa_schedule_add(dsa_schedule_mul(candidate.read_beats,c->read_beat_cycles),
                    dsa_schedule_mul(candidate.read_requests,c->read_request_cycles));
                write_cycles=dsa_schedule_add(dsa_schedule_mul(candidate.write_beats,c->write_beat_cycles),
                    dsa_schedule_mul(candidate.write_requests,c->write_request_cycles));
                stream_words=dsa_schedule_mul(mode ? b_words:a_words,mode ? b_passes:a_passes);
                stream_requests=dsa_schedule_mul(mode ? b_requests:a_requests,mode ? b_passes:a_passes);
                stationary_commits=dsa_schedule_mul((uint64_t)rg*tc,kt);
                /* IA refills and stationary-operand installation form a
                 * separate scheduling path. Each installation consumes SIZE
                 * array cycles before the streamed operand can execute. */
                stream_cycles=dsa_schedule_add(
                    dsa_schedule_mul(stream_words/(dsa_schedule_bus_bytes(c)/4u),c->read_beat_cycles),
                    dsa_schedule_add(dsa_schedule_mul(stream_requests,c->read_request_cycles),
                                     dsa_schedule_mul(stationary_commits,c->size)));
                candidate.estimated_cycles=dsa_schedule_max(
                    dsa_schedule_max(read_cycles,write_cycles),
                    dsa_schedule_max(candidate.compute_cycles,stream_cycles));
                ++candidates;
                if (!found || dsa_schedule_better(&candidate,out)) {*out=candidate;found=1;}
            }
        }
    }
    if (found) out->candidates=candidates;
    return found;
}

#include "dsa_memory_schedule.h"

/* Optional layout selection for tensors whose caller can prepare either
 * storage format. The mask uses bit0 for lhs and bit1 for rhs. Existing
 * packed flags stay required. A newly packed allocation is word aligned. */
static inline int dsa_schedule_plan_layout(const dsa_schedule_config_t *c,
    uint32_t may_pack, dsa_schedule_t *out, uint32_t *layout)
{
    uint32_t required,candidates=0;
    int found=0;
    if (out) *out=(dsa_schedule_t){0};
    if (!c || !out || !layout || may_pack>3u) return 0;
    required=c->lhs_tile_packed | (c->rhs_tile_packed<<1);
    for (uint32_t flags=0;flags<4u;++flags) {
        dsa_schedule_config_t candidate_config=*c;
        dsa_schedule_t candidate;
        if ((flags&required)!=required || (flags&~(may_pack|required))) continue;
        candidate_config.lhs_tile_packed=flags&1u;
        candidate_config.rhs_tile_packed=(flags>>1)&1u;
        if (flags&1u) candidate_config.lhs_address=0u;
        if (flags&2u) candidate_config.rhs_address=0u;
        if (!dsa_schedule_plan(&candidate_config,&candidate)) continue;
        candidates+=candidate.candidates;
        if (!found || dsa_schedule_better(&candidate,out)) {
            *out=candidate;*layout=flags;found=1;
        }
    }
    if (found) out->candidates=candidates;
    return found;
}

#endif
