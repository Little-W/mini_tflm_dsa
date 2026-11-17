#ifndef GEMPACT_TILING_H
#define GEMPACT_TILING_H
#include <stdint.h>
/* Host/compiler helper. rows/cols refer to the public logical output shape. */
typedef struct {
    uint32_t ia_reuse, w_reuse;
    uint32_t row_groups, row_tail_tiles, col_groups, col_tail_tiles;
} gempact_tiling_t;

static inline uint32_t gempact_ceil_div(uint32_t a, uint32_t b) {
    return a ? 1u + (a-1u)/b : 0u;
}

static inline uint32_t gempact_floor_supported(uint32_t x) {
    uint32_t p=1;
    if (x>=25u && x<32u) return 25u;
    while (p <= x/2u) p <<= 1;
    return p;
}
static inline int gempact_plan_tiling(uint32_t rows, uint32_t cols,
    uint32_t size, uint32_t cache, uint32_t ps, uint32_t req_r, uint32_t req_w,
    int is_mode, int per_channel, gempact_tiling_t *out) {
    uint32_t tr,tc,rc,wc,wr,r,w,tmp;
    if (!out || !rows || !cols || !size || (size & (size-1u)) || !cache || !ps) return 0;
    if (is_mode) {tmp=rows;rows=cols;cols=tmp;}
    tr=rows/size+(rows%size!=0u);tc=cols/size+(cols%size!=0u);
    tmp=cache/2u;if (!tmp) tmp=1;
    rc=gempact_floor_supported(tmp);
    wr=tc<ps?tc:ps;wc=gempact_floor_supported(wr);
    r=gempact_floor_supported(!req_r||req_r>=rc?rc:req_r);
    w=gempact_floor_supported(!req_w||req_w>=wc?wc:req_w);
    if (is_mode && per_channel && r==25u) r=16u;
    out->ia_reuse=r;out->w_reuse=w;
    out->row_groups=tr/r+(tr%r!=0u);out->row_tail_tiles=tr%r?tr%r:r;
    out->col_groups=tc/w+(tc%w!=0u);out->col_tail_tiles=tc%w?tc%w:w;
    return out->row_groups<=65535u && out->col_groups<=65535u && r<=65535u && w<=65535u;
}

/* The PS store contains active matrix rows. Per-bank admission retains an
 * existing frame until its replacement can be completed. */
static inline uint64_t gempact_ps_payload_bound(uint32_t size, uint32_t r,
                                               uint32_t w) {
    return (uint64_t)r*size*(uint64_t)w*size*4u;
}
static inline uint64_t gempact_task_payload_bound(uint32_t rows, uint32_t cols,
    uint32_t size, uint32_t r, uint32_t w, int is_mode) {
    uint64_t stream_rows=is_mode?cols:rows;
    uint64_t group_rows=(uint64_t)r*size;
    if (stream_rows<group_rows) group_rows=stream_rows;
    return group_rows*(uint64_t)w*size*4u;
}
static inline int gempact_supported_reuse(uint32_t x) {
    return x && ((x & (x-1u))==0u || x==25u);
}
static inline int gempact_plan_capacity(uint32_t rows, uint32_t cols,
    uint32_t size, uint32_t cache, uint32_t ps, uint32_t req_r, uint32_t req_w,
    int is_mode, int per_channel, uint32_t pool_bytes,
    gempact_tiling_t *out, uint64_t *payload_bound) {
    gempact_tiling_t cap, candidate, best;
    uint64_t best_cost=UINT64_MAX, best_area=0, best_bytes=UINT64_MAX;
    uint32_t tr,tc,sr,sc,r,w; int found=0;
    if (!out || !gempact_plan_tiling(rows,cols,size,cache,ps,req_r,req_w,
                                     is_mode,per_channel,&cap)) return 0;
    if (!pool_bytes) {
        *out=cap; if(payload_bound) *payload_bound=0; return 1;
    }
    /* The shared codec stores sixteen complete INT32 lanes per row. */
    if (size!=16u || pool_bytes%64u) return 0;
    if (gempact_task_payload_bound(rows,cols,size,cap.ia_reuse,cap.w_reuse,is_mode)<=pool_bytes) {
        *out=cap;
        if(payload_bound) *payload_bound=gempact_task_payload_bound(rows,cols,size,cap.ia_reuse,cap.w_reuse,is_mode);
        return 1;
    }
    sr=is_mode?cols:rows; sc=is_mode?rows:cols;
    tr=sr/size+(sr%size!=0u); tc=sc/size+(sc%size!=0u);
    /* At most 16 powers of two and the special factor 25 are evaluated. */
    for (uint32_t ri=0;ri<17u;ri++) {
        r=ri==16u?25u:(1u<<ri);
        if (r>cap.ia_reuse) continue;
        for (uint32_t wi=0;wi<17u;wi++) {
            uint64_t bytes,cost,area;
            w=wi==16u?25u:(1u<<wi);
            if (w>cap.w_reuse) continue;
            if (!gempact_plan_tiling(rows,cols,size,cache,ps,r,w,is_mode,
                                     per_channel,&candidate)) continue;
            /* Evaluate the requested pair within the physical limits. */
            if (candidate.ia_reuse!=r || candidate.w_reuse!=w) continue;
            bytes=gempact_task_payload_bound(rows,cols,size,r,w,is_mode);
            if (bytes>pool_bytes) continue;
            cost=(uint64_t)sr*(tc/w+(tc%w!=0u))+
                 (uint64_t)sc*(tr/r+(tr%r!=0u));
            area=(uint64_t)r*w;
            if (!found || cost<best_cost || (cost==best_cost &&
                (area>best_area || (area==best_area && bytes<best_bytes)))) {
                found=1; best=candidate;best_cost=cost;best_area=area;best_bytes=bytes;
            }
        }
    }
    if (!found) return 0;
    *out=best;if(payload_bound) *payload_bound=best_bytes;return 1;
}

/* Public matrix shape is rows x reduction x cols. IS exchanges the physical
 * stream and stationary operands while retaining the public output layout. */
typedef struct {
    gempact_tiling_t tiling;
    gempact_tiling_t raw_safe;
    uint32_t is_mode;
    uint32_t frame_rows;
    uint32_t adaptive_active;
    uint32_t reduction, lhs_element_bytes, bus_bytes;
    uint64_t payload_bound_bytes;
    uint64_t lhs_read_rounds, rhs_read_rounds;
    uint64_t operand_read_bytes, frame_count, array_stream_cycles;
    uint64_t service_estimate;
    uint32_t ps_control, ia_slots, slice_rows, predicted_resident_frames;
    uint32_t estimated_record_bytes, literal_record_bytes, candidates_evaluated;
    uint64_t micro_commands, weight_shift_rows;
    uint32_t ia_bank_count,ia_bytes,pool_bytes;
    uint32_t raw_safe_is_mode,raw_safe_ps_control,raw_safe_slice_rows;
    uint32_t raw_safe_ia_bank_count,raw_safe_ia_bytes,raw_safe_pool_bytes;
} gempact_dispatch_t;

static inline uint64_t gempact_transfer_cycles(uint64_t bytes, uint32_t bus_bytes) {
    if (bus_bytes==4u) return (bytes>>2)+(uint64_t)((bytes&3u)!=0u);
    if (bus_bytes==1u) return bytes;
    if ((bus_bytes&(bus_bytes-1u))==0u) {
        uint32_t shift=0, value=bus_bytes;
        while (value>1u) {value>>=1;++shift;}
        return (bytes>>shift)+(uint64_t)((bytes&(bus_bytes-1u))!=0u);
    }
    return bytes/bus_bytes+(uint64_t)(bytes%bus_bytes!=0u);
}

static inline void gempact_workload_cost(uint32_t rows, uint32_t reduction,
    uint32_t cols, uint32_t size, uint32_t lhs_bytes, uint32_t bus_bytes,
    int is_mode, const gempact_tiling_t *t, gempact_dispatch_t *p) {
    uint64_t sr=is_mode?cols:rows, sc=is_mode?rows:cols;
    uint64_t frames_per_group=(uint64_t)gempact_ceil_div((uint32_t)sc,size)*
                               gempact_ceil_div(reduction,size);
    uint64_t transfer_cycles;
    p->lhs_read_rounds=is_mode?t->row_groups:t->col_groups;
    p->rhs_read_rounds=is_mode?t->col_groups:t->row_groups;
    p->operand_read_bytes=(uint64_t)rows*reduction*lhs_bytes*p->lhs_read_rounds+
                          (uint64_t)cols*reduction*p->rhs_read_rounds;
    p->frame_count=(uint64_t)t->row_groups*frames_per_group;
    p->array_stream_cycles=(sr+(uint64_t)(size-1u)*t->row_groups)*frames_per_group;
    transfer_cycles=gempact_transfer_cycles(p->operand_read_bytes,bus_bytes);
    p->service_estimate=(transfer_cycles>p->array_stream_cycles?
                         transfer_cycles:p->array_stream_cycles)+p->frame_count;
}

static inline uint32_t gempact_reuse_at(uint32_t index) {
    return index<5u?(1u<<index):index==5u?25u:(1u<<(index-1u));
}

static inline uint32_t gempact_groups_at(uint32_t tiles, uint32_t index,
                                        uint32_t *tail) {
    uint32_t reuse=gempact_reuse_at(index), remainder, groups;
    if (index==5u) {
        remainder=tiles%25u;groups=tiles/25u+(remainder!=0u);
    } else {
        uint32_t shift=index<5u?index:index-1u;
        remainder=tiles&(reuse-1u);groups=(tiles>>shift)+(remainder!=0u);
    }
    *tail=remainder?remainder:reuse;
    return groups;
}

/* Feasibility depends on the smallest legal reuse pair and needs no work
 * scoring. This is suitable for a capability query before reading tensors. */
static inline int gempact_plan_feasible(uint32_t rows, uint32_t reduction,
    uint32_t cols, uint32_t size, uint32_t cache, uint32_t ps,
    uint32_t req_r, uint32_t req_w, uint32_t mode, int is_supported,
    int per_channel, uint32_t pool_bytes) {
    uint32_t planning_pool=reduction<=size?0u:pool_bytes;
    if (!reduction || mode>2u) return 0;
    if (planning_pool && (size!=16u || planning_pool%64u)) return 0;
    for (uint32_t m=0;m<2u;++m) {
        gempact_tiling_t cap;
        uint32_t tr,tc,r=0,w=0;
        if ((mode!=2u && mode!=m) || (m && !is_supported)) continue;
        if (!gempact_plan_tiling(rows,cols,size,cache,ps,req_r,req_w,m,per_channel,&cap)) continue;
        if (!planning_pool) return 1;
        tr=gempact_ceil_div(m?cols:rows,size);
        tc=gempact_ceil_div(m?rows:cols,size);
        for (uint32_t i=0;i<17u && gempact_reuse_at(i)<=cap.ia_reuse;++i) {
            uint32_t candidate=gempact_reuse_at(i);
            if (m && per_channel && candidate==25u) continue;
            if (tr<=candidate*65535u) {r=candidate;break;}
        }
        for (uint32_t i=0;i<17u && gempact_reuse_at(i)<=cap.w_reuse;++i) {
            uint32_t candidate=gempact_reuse_at(i);
            if (tc<=candidate*65535u) {w=candidate;break;}
        }
        if (r && w && gempact_task_payload_bound(rows,cols,size,r,w,m)<=planning_pool) return 1;
    }
    return 0;
}

/* Compare work estimates; equal work prefers the smaller payload bound. */
static inline int gempact_dispatch_better(const gempact_dispatch_t *a,
                                          const gempact_dispatch_t *b) {
    if (a->service_estimate!=b->service_estimate) return a->service_estimate<b->service_estimate;
    if (a->frame_count!=b->frame_count) return a->frame_count<b->frame_count;
    if (a->operand_read_bytes!=b->operand_read_bytes) return a->operand_read_bytes<b->operand_read_bytes;
    if (a->array_stream_cycles!=b->array_stream_cycles) return a->array_stream_cycles<b->array_stream_cycles;
    if (a->payload_bound_bytes!=b->payload_bound_bytes) return a->payload_bound_bytes<b->payload_bound_bytes;
    if (a->tiling.ia_reuse!=b->tiling.ia_reuse) return a->tiling.ia_reuse<b->tiling.ia_reuse;
    return a->tiling.w_reuse<b->tiling.w_reuse;
}

static inline uint32_t gempact_frame_rows(uint32_t stream_rows, uint32_t size,
                                         uint32_t r) {
    uint64_t rows=(uint64_t)r*size;
    if (stream_rows<rows) rows=stream_rows;
    return (uint32_t)rows;
}

static inline void gempact_describe_dispatch(uint32_t rows, uint32_t cols,
    uint32_t size, gempact_dispatch_t *p) {
    p->frame_rows=gempact_frame_rows(p->is_mode?cols:rows,size,p->tiling.ia_reuse);
    p->payload_bound_bytes=p->reduction<=size?0u:
        (uint64_t)p->frame_rows*p->tiling.w_reuse*size*4u;
    gempact_workload_cost(rows,p->reduction,cols,size,p->lhs_element_bytes,p->bus_bytes,
                         p->is_mode,&p->tiling,p);
}

/* mode: 0=WS, 1=IS, 2=automatic. Both storage policies enumerate the same
 * physical R/W limits. Task-invariant byte counts and tile counts are
 * calculated once. Adaptive candidates expand either reuse axis from a
 * guaranteed RAW-safe pair and must admit one complete RAW frame. */
static inline int gempact_plan_dispatch(uint32_t rows, uint32_t reduction,
    uint32_t cols, uint32_t size, uint32_t cache, uint32_t ps,
    uint32_t req_r, uint32_t req_w, uint32_t mode, int is_supported,
    int per_channel, uint32_t lhs_bytes, uint32_t bus_bytes,
    uint32_t pool_bytes, int adaptive, gempact_dispatch_t *out) {
    gempact_dispatch_t best={0};
    uint32_t planning_pool=reduction<=size?0u:pool_bytes;
    uint64_t lhs_base_bytes=(uint64_t)rows*reduction*lhs_bytes;
    uint64_t rhs_base_bytes=(uint64_t)cols*reduction;
    int found=0;
    if (!out || !reduction || mode>2u || !lhs_bytes || !bus_bytes) return 0;
    if (planning_pool && (size!=16u || planning_pool%64u)) return 0;
    for (uint32_t m=0;m<2u;++m) {
        gempact_tiling_t cap;
        gempact_dispatch_t selected={0},p={0};
        uint32_t stream_rows=m?cols:rows, tr,tc;
        uint64_t frames_per_group;
        int safe_found=0;
        if ((mode!=2u && m!=mode) || (m && !is_supported)) continue;
        if (!gempact_plan_tiling(rows,cols,size,cache,ps,req_r,req_w,m,per_channel,&cap)) continue;
        tr=gempact_ceil_div(stream_rows,size);
        tc=gempact_ceil_div(m?rows:cols,size);
        frames_per_group=(uint64_t)tc*gempact_ceil_div(reduction,size);
        p.is_mode=m;p.reduction=reduction;p.lhs_element_bytes=lhs_bytes;p.bus_bytes=bus_bytes;
        for (uint32_t phase=0;phase<(adaptive && planning_pool?2u:1u);++phase) {
            for (uint32_t ri=0;ri<17u && gempact_reuse_at(ri)<=cap.ia_reuse;++ri) {
                uint32_t r=gempact_reuse_at(ri);
                uint64_t frame_bytes;
                if ((m && per_channel && r==25u) || (phase && r<selected.raw_safe.ia_reuse)) continue;
                p.tiling.ia_reuse=r;
                p.tiling.row_groups=gempact_groups_at(tr,ri,&p.tiling.row_tail_tiles);
                if (p.tiling.row_groups>65535u) continue;
                p.frame_rows=gempact_frame_rows(stream_rows,size,r);
                frame_bytes=(uint64_t)p.frame_rows*size*4u;
                if (phase && frame_bytes>planning_pool) continue;
                p.frame_count=(uint64_t)p.tiling.row_groups*frames_per_group;
                p.array_stream_cycles=((uint64_t)stream_rows+(uint64_t)(size-1u)*p.tiling.row_groups)*frames_per_group;
                for (uint32_t wi=0;wi<17u && gempact_reuse_at(wi)<=cap.w_reuse;++wi) {
                    uint32_t w=gempact_reuse_at(wi);
                    uint64_t transfer_cycles;
                    if (phase && w<selected.raw_safe.w_reuse) continue;
                    p.tiling.w_reuse=w;
                    p.tiling.col_groups=gempact_groups_at(tc,wi,&p.tiling.col_tail_tiles);
                    if (p.tiling.col_groups>65535u) continue;
                    p.payload_bound_bytes=reduction<=size?0u:frame_bytes*w;
                    if (!phase && planning_pool && p.payload_bound_bytes>planning_pool) continue;
                    p.lhs_read_rounds=m?p.tiling.row_groups:p.tiling.col_groups;
                    p.rhs_read_rounds=m?p.tiling.col_groups:p.tiling.row_groups;
                    p.operand_read_bytes=lhs_base_bytes*p.lhs_read_rounds+rhs_base_bytes*p.rhs_read_rounds;
                    transfer_cycles=gempact_transfer_cycles(p.operand_read_bytes,bus_bytes);
                    p.service_estimate=(transfer_cycles>p.array_stream_cycles?
                                         transfer_cycles:p.array_stream_cycles)+p.frame_count;
                    if (!safe_found || gempact_dispatch_better(&p,&selected)) {
                        gempact_tiling_t raw_safe=selected.raw_safe;
                        selected=p;
                        if (phase) selected.raw_safe=raw_safe;
                        safe_found=1;
                    }
                }
            }
            if (!safe_found) break;
            if (!phase) selected.raw_safe=selected.tiling;
        }
        if (!safe_found) continue;
        selected.adaptive_active=selected.tiling.ia_reuse!=selected.raw_safe.ia_reuse ||
                                 selected.tiling.w_reuse!=selected.raw_safe.w_reuse;
        if (!found || gempact_dispatch_better(&selected,&best)) {best=selected;found=1;}
    }
    if (!found) return 0;
    *out=best;return 1;
}

typedef struct {
    uint32_t rows,reduction,cols,size,ia_bytes,frames,pool_bytes;
    uint32_t req_r,req_w,mode,is_supported,per_channel,lhs_element_bytes;
    uint32_t compact_mode_mask,frame_capable,adaptive;
    uint32_t estimated_record_bytes,literal_record_bytes;
    uint32_t micro_setup_cycles;
    uint32_t im2col_source_bytes,im2col_pixel_channels;
    uint32_t im2col_stage_bytes_per_position,im2col_base_fraction_q8,im2col_cache_bytes;
    uint32_t directory_rows,ia_bank_count,ps_bank_count;
} gempact_device_request_t;

/* A transfer-aware caller can score each nondominated device candidate in
 * the same search. Work counts are provided when the bounded search already
 * computed them; UINT64_MAX requests the general geometry calculation. */
typedef void (*gempact_candidate_visitor_t)(const gempact_device_request_t *,
    const gempact_dispatch_t *,uint64_t,uint64_t,void *);

static inline uint32_t gempact_min_u32(uint32_t a,uint32_t b) {return a<b?a:b;}

typedef struct {
    uint32_t input_bytes,input_channels,group_channels,kernel_h,kernel_w,stride_w;
    uint32_t source_bytes,cache_bytes;
} gempact_im2col_geometry_t;

/* Prepare geometry once per operation. The Q8 fraction describes unique
 * image bytes relative to logical im2col bytes; it is not a PS value bound. */
static inline int gempact_set_im2col_geometry(gempact_device_request_t *q,
                                             const gempact_im2col_geometry_t *c)
{
    uint64_t total,stage;
    uint32_t kernel_rows;
    if(!q||!c||!q->rows||!q->reduction||!c->input_bytes||!c->input_channels||
       !c->group_channels||!c->kernel_h||!c->kernel_w||!c->stride_w||
       !c->source_bytes||c->source_bytes>2u) return 0;
    kernel_rows=gempact_min_u32(c->kernel_h,
        c->kernel_w>=16u||c->group_channels>=16u||c->kernel_w*c->group_channels>=16u?
        1u:1u+15u/(c->kernel_w*c->group_channels));
    stage=(uint64_t)c->stride_w*gempact_min_u32(c->input_channels,16u)*
          c->source_bytes*kernel_rows;
    if(stage>UINT32_MAX) return 0;
    total=(uint64_t)q->rows*q->reduction;
    if(total>UINT64_MAX/c->source_bytes) return 0;
    total*=c->source_bytes;
    q->im2col_source_bytes=c->source_bytes;
    q->im2col_pixel_channels=gempact_min_u32(c->group_channels,16u);
    q->im2col_stage_bytes_per_position=(uint32_t)stage;
    q->im2col_base_fraction_q8=c->input_bytes>=total?256u:
        c->input_bytes<=UINT32_MAX/256u&&total<=UINT32_MAX?
        (c->input_bytes<<8)/(uint32_t)total:
        (uint32_t)(((uint64_t)c->input_bytes<<8)/total);
    q->im2col_cache_bytes=c->cache_bytes;
    return 1;
}

static inline int gempact_im2col_valid(const gempact_device_request_t *q)
{
    return !q->im2col_source_bytes || (q->im2col_source_bytes<=2u &&
        q->im2col_pixel_channels && q->im2col_pixel_channels<=16u &&
        q->im2col_stage_bytes_per_position && q->im2col_base_fraction_q8<=256u);
}

static inline uint32_t gempact_image_window_sensitive(const gempact_device_request_t *q,
                                                      uint32_t max_w)
{
    return q->im2col_source_bytes&&q->im2col_base_fraction_q8<256u&&
        (uint64_t)gempact_min_u32(q->rows,max_w*16u)*q->im2col_stage_bytes_per_position>
        q->im2col_cache_bytes;
}

/* The geometry term accounts for im2col element service and cache capacity.
 * It uses no activation values or future partial sums. Reuse past the image
 * cache is estimated from the spatial footprint of one K16 stage. */
static inline uint64_t gempact_im2col_cost(const gempact_device_request_t *q,
    uint32_t mode,uint32_t r,uint32_t w,uint32_t path,uint32_t slice,uint32_t resident,
    uint64_t stream,uint64_t stationary)
{
    uint64_t elements,bytes,unreused,footprint,cost;
    uint32_t positions,overflow;
    if(!q->im2col_source_bytes) return 0;
    elements=mode?stationary:stream;
    cost=elements+6u*(1u+(elements-1u)/q->im2col_pixel_channels);
    positions=gempact_min_u32(q->rows,(mode?w:r)*16u);
    if(mode&&path&&resident) {
        uint32_t parts=gempact_ceil_div(gempact_min_u32(q->cols,r*16u),slice);
        uint32_t columns=resident/parts;
        if(!columns) columns=1u;
        positions=gempact_min_u32(positions,columns*16u);
    }
    footprint=(uint64_t)positions*q->im2col_stage_bytes_per_position;
    if(footprint<=q->im2col_cache_bytes) return cost;
    overflow=256u-(uint32_t)(((uint64_t)q->im2col_cache_bytes<<8)/footprint);
    bytes=elements*q->im2col_source_bytes;
    unreused=(bytes>>8)*(256u-q->im2col_base_fraction_q8)+
        (((bytes&255u)*(256u-q->im2col_base_fraction_q8))>>8);
    return cost+(unreused>>9)*overflow+(((unreused&511u)*overflow)>>9);
}

/* Bias and optional per-channel multiplier/shift arrays follow the loader
 * lifetime. IS long streams retain them across spatial windows. Frame IS
 * commands reload them for each spatial tile; WS reloads each row group. */
static inline uint64_t gempact_parameter_read_bytes(const gempact_device_request_t *q,
    uint32_t mode,uint32_t path,uint32_t slice_rows)
{
    uint32_t groups=mode?(path?gempact_ceil_div(q->rows,q->size):1u):
        gempact_ceil_div(q->rows,slice_rows);
    return (uint64_t)q->cols*(q->per_channel?12u:4u)*groups;
}

/* Both dataflows add bias after the final reduction block. This bound uses
 * the original input format, including Conv before its internal S16 staging.
 * The strict inequality excludes +2^23 from every retained prefix. */
static inline uint32_t gempact_literal_record_bytes(uint32_t reduction,
    uint32_t source_s8,int32_t lhs_offset,int32_t rhs_offset)
{
    uint32_t lhs_exp=!source_s8?15u:lhs_offset==0?7u:
        lhs_offset>=-128&&lhs_offset<=128?8u:15u;
    uint32_t rhs_exp=rhs_offset==0?7u:
        rhs_offset>=-128&&rhs_offset<=128?8u:15u;
    uint32_t product_exp=lhs_exp+rhs_exp;
    uint32_t retained=reduction?(reduction-1u)&~15u:0u;
    return reduction&&product_exp<23u&&retained<(1u<<(23u-product_exp))?48u:64u;
}

/* The caller supplies a proven upper bound for every retained row. */
static inline uint32_t gempact_literal_cap(const gempact_device_request_t *q)
{
    return q->literal_record_bytes==32u||q->literal_record_bytes==48u?
        q->literal_record_bytes:64u;
}

static inline uint32_t gempact_bank_reservation(uint32_t rows,uint32_t literal_bytes)
{
    return literal_bytes==32u?(rows>>1)+(rows&1u):
        literal_bytes==48u?rows-(rows>>2):rows;
}

/* A long-controller tail may configure the next power of two above the
 * actual column tiles. Only those actual tiles consume frames and payload. */
static inline uint32_t gempact_window_limit(const gempact_device_request_t *q,uint32_t tiles)
{
    uint32_t limit=q->frames,rounded=1u;
    if(q->req_w&&limit>q->req_w) limit=q->req_w;
    if(tiles>=limit) return limit;
    while(rounded<tiles) rounded*=2u;
    return rounded<=limit?rounded:tiles;
}
typedef struct {
    uint32_t total_bytes,bank_bytes,ia_bank_mask,directory_rows;
} gempact_shared_memory_t;

static inline uint32_t gempact_ps_banks(const gempact_device_request_t *q)
{
    return q->ps_bank_count?q->ps_bank_count:4u;
}

static inline uint32_t gempact_ps_bank_words(const gempact_device_request_t *q)
{
    if(!q->ps_bank_count) return q->pool_bytes>>6;
    if(q->pool_bytes==(q->ps_bank_count<<10)) return 1024u/16u;
    if(q->pool_bytes==(q->ps_bank_count<<11)) return 2048u/16u;
    if(q->pool_bytes==(q->ps_bank_count<<12)) return 4096u/16u;
    return q->pool_bytes/(q->ps_bank_count<<4);
}

static inline uint32_t gempact_reserve_bank_words(const gempact_device_request_t *q,
    uint32_t rows,uint32_t record_bytes)
{
    return gempact_ceil_div(rows*(record_bytes/16u),gempact_ps_banks(q));
}

static inline uint32_t gempact_directory_frames(const gempact_device_request_t *q,
                                               uint32_t rows)
{
    return q->directory_rows&&q->reduction>q->size?
        gempact_min_u32(q->frames,q->directory_rows/rows):q->frames;
}

static inline void gempact_raw_execution(gempact_dispatch_t *p,
                                          const gempact_dispatch_t *raw)
{
    if(!raw) {
        p->raw_safe=(gempact_tiling_t){0};p->raw_safe_is_mode=p->raw_safe_ps_control=p->raw_safe_slice_rows=0u;
        p->raw_safe_ia_bank_count=p->raw_safe_ia_bytes=p->raw_safe_pool_bytes=0u;return;
    }
    p->raw_safe=raw->tiling;p->raw_safe_is_mode=raw->is_mode;
    p->raw_safe_ps_control=raw->ps_control;p->raw_safe_slice_rows=raw->slice_rows;
    p->raw_safe_ia_bank_count=raw->ia_bank_count;
    p->raw_safe_ia_bytes=raw->ia_bytes;p->raw_safe_pool_bytes=raw->pool_bytes;
}

static inline uint32_t gempact_gcd(uint32_t a,uint32_t b) {
    while(b) {uint32_t r=a%b;a=b;b=r;} return a;
}

/* Count a normal frame sweep with a constant estimated occupancy. The cache
 * uses the exact physical (row_tile + K_tile*R) modulo slot mapping. No
 * compression estimate is used by the hardware admission rule. */
static inline void gempact_group_cost(const gempact_device_request_t *q,
    uint32_t mode,uint32_t r,uint32_t w,uint32_t rows,uint32_t slice_rows,
    uint32_t slots,uint32_t force_raw,uint32_t directory_frames,uint64_t *stream_elements,
    uint64_t *stationary_elements,uint64_t *stationary_loads,
    uint32_t *resident) {
    uint32_t stationary=mode?q->rows:q->cols;
    uint32_t ct=gempact_ceil_div(stationary,q->size);
    uint32_t parts=gempact_ceil_div(rows,slice_rows),target=w*parts;
    uint32_t count=gempact_min_u32(directory_frames,target);
    uint32_t reserve=gempact_min_u32(rows,slice_rows);
    uint32_t kt=gempact_ceil_div(q->reduction,q->size),capacity=slots/r;
    uint32_t literal=force_raw?64u:gempact_literal_cap(q);
    uint32_t estimate=force_raw?64u:gempact_min_u32(q->estimated_record_bytes,literal);
    uint32_t reserved_bank=gempact_reserve_bank_words(q,reserve,literal);
    uint64_t frame_bytes=literal+(uint64_t)(reserve-1u)*estimate;
    if(kt>1u) {
        uint32_t per_bank=(uint32_t)((frame_bytes+16u*gempact_ps_banks(q)-1u)/(16u*gempact_ps_banks(q)));
        uint32_t depth=gempact_ps_bank_words(q);
        uint32_t limit=1u+(depth-reserved_bank)/per_bank;
        if(count>limit) count=limit;
    }
    {
        uint32_t total=ct*parts,windows=gempact_ceil_div(total,count);
        uint32_t last=total-(windows-1u)*count;
        uint64_t loaded_rows;
        uint32_t boundaries=windows-1u;
        uint32_t aligned_period=parts/gempact_gcd(count,parts);
        uint32_t splits=boundaries-boundaries/aligned_period;
        uint32_t final_splits=(total-1u)/count-((ct-1u)*parts)/count;
        uint32_t tail=stationary-(ct-1u)*q->size;
        uint64_t extra=kt==1u?0u:(uint64_t)splits*q->size-(uint64_t)final_splits*(q->size-tail);
        if(kt==1u) splits=0u;
        uint64_t reload=kt<=capacity?0u:kt>=2u*capacity?q->reduction:
            (uint64_t)(2u*(kt-capacity)-1u)*q->size+(q->reduction-1u)%q->size+1u;
        if(count<parts) loaded_rows=(uint64_t)rows*ct;
        else loaded_rows=(uint64_t)(windows-1u)*rows+
            (last>=parts?rows:rows-(parts-last)*slice_rows);
        *stream_elements+=(uint64_t)rows*q->reduction+(loaded_rows-rows)*reload;
        *stationary_elements+=((uint64_t)stationary+extra)*q->reduction;
        *stationary_loads+=(uint64_t)(ct+splits)*kt;
        if(*resident<count) *resident=count;
    }
}

/* path 0 is the long-stream controller. path 1 uses whole-R frame commands;
 * paths 2 and 3 use 16- and 32-row slices. Both storage policies can select
 * every RAW-feasible path, R, W and dataflow configuration. */
static inline int gempact_device_candidate(const gempact_device_request_t *q,
    uint32_t mode,uint32_t r,uint32_t w,uint32_t path,uint32_t force_raw,
    gempact_dispatch_t *p) {
    uint32_t sr=mode?q->cols:q->rows,sc=mode?q->rows:q->cols;
    uint32_t tr=gempact_ceil_div(sr,q->size),tc=gempact_ceil_div(sc,q->size);
    uint32_t kt=gempact_ceil_div(q->reduction,q->size),groups=gempact_ceil_div(tr,r);
    uint32_t slots=q->ia_bytes/(q->size*q->size*2u);
    uint32_t rows=gempact_min_u32(sr,r*q->size),slice=rows,resident=0,frame_limit;
    uint32_t literal=force_raw?64u:gempact_literal_cap(q);
    uint64_t stream=0,stationary=0,weight_loads=0;
    uint32_t actual_w=gempact_min_u32(w,tc);
    uint64_t bound=kt>1u?(uint64_t)rows*actual_w*q->size*4u:0u;
    if(q->compact_mode_mask&(1u<<mode)) slots*=2u;
    if(q->ia_bank_count==1u&&!(q->compact_mode_mask&(1u<<mode))) return 0;
    if(kt>1u&&literal/16u>gempact_ps_banks(q)) return 0;
    if(r>slots/2u||w>q->frames||groups>65535u||gempact_ceil_div(tc,w)>65535u||
       (w>tc&&(path||(w&(w-1u))!=0u||w/2u>=tc))) return 0;
    if((!path&&((w&(w-1u))!=0u||
        (kt>1u&&(uint64_t)gempact_reserve_bank_words(q,rows,literal)*actual_w>gempact_ps_bank_words(q))))||
       (path&&!q->frame_capable)||(force_raw&&!path&&bound>q->pool_bytes)||
       (!force_raw&&(!q->adaptive||!q->frame_capable))) return 0;
    if(path==2u) slice=gempact_min_u32(rows,q->size);
    if(path==3u) slice=gempact_min_u32(rows,2u*q->size);
    if((path==2u&&slice==rows)||(path==3u&&(slice==rows||slice==q->size))) return 0;
    frame_limit=gempact_directory_frames(q,slice);
    if(!frame_limit||(!path&&actual_w>frame_limit)) return 0;
    if(kt>1u&&gempact_reserve_bank_words(q,slice,literal)>gempact_ps_bank_words(q)) return 0;
    p->raw_safe=(gempact_tiling_t){0};p->candidates_evaluated=0u;
    p->ia_bank_count=0u;p->ia_bytes=q->ia_bytes;p->pool_bytes=q->pool_bytes;
    p->raw_safe_is_mode=p->raw_safe_ps_control=p->raw_safe_slice_rows=0u;
    p->raw_safe_ia_bank_count=p->raw_safe_ia_bytes=p->raw_safe_pool_bytes=0u;
    p->tiling.ia_reuse=r;p->tiling.w_reuse=w;
    p->tiling.row_groups=groups;p->tiling.row_tail_tiles=(tr-1u)%r+1u;
    p->tiling.col_groups=gempact_ceil_div(tc,w);p->tiling.col_tail_tiles=(tc-1u)%w+1u;
    p->is_mode=mode;p->reduction=q->reduction;p->lhs_element_bytes=q->lhs_element_bytes;p->bus_bytes=4u;
    p->frame_rows=slice;p->slice_rows=slice;p->ia_slots=slots;p->payload_bound_bytes=bound;
    p->estimated_record_bytes=force_raw?64u:gempact_min_u32(q->estimated_record_bytes,literal);
    p->literal_record_bytes=literal;
    p->adaptive_active=!force_raw&&kt>1u&&(gempact_ps_banks(q)<4u||
        (uint64_t)gempact_reserve_bank_words(q,rows,64u)*actual_w>gempact_ps_bank_words(q));
    p->ps_control=(force_raw?1u:0u)|(path?2u:0u)|
        (path==1u?12u:path==2u?4u:path==3u?8u:0u);
    if(!path) {
        stream=(uint64_t)sr*q->reduction*p->tiling.col_groups;
        stationary=(uint64_t)sc*q->reduction*groups;
        weight_loads=(uint64_t)groups*tc*kt;
    } else {
        uint32_t full=sr/(r*q->size),tail=sr%(r*q->size);
        if(full) {
            uint64_t a=0,b=0,c=0;
            gempact_group_cost(q,mode,r,w,r*q->size,slice,slots,force_raw,frame_limit,&a,&b,&c,&resident);
            stream+=a*full;stationary+=b*full;weight_loads+=c*full;
        }
        if(tail) gempact_group_cost(q,mode,r,w,tail,gempact_min_u32(slice,tail),slots,force_raw,frame_limit,
                                   &stream,&stationary,&weight_loads,&resident);
        if(kt==1u&&tc==1u) {stationary=(uint64_t)sc*q->reduction;weight_loads=1u;}
    }
    p->predicted_resident_frames=resident;
    p->operand_read_bytes=mode?stationary*q->lhs_element_bytes+stream:
                                 stream*q->lhs_element_bytes+stationary;
    p->operand_read_bytes+=gempact_parameter_read_bytes(q,mode,path,slice);
    p->lhs_read_rounds=mode?groups:p->tiling.col_groups;
    p->rhs_read_rounds=mode?p->tiling.col_groups:groups;
    {
        uint32_t slice_groups=path?gempact_ceil_div(sr,slice):groups;
        uint64_t transfers=gempact_transfer_cycles(p->operand_read_bytes,4u),array;
        p->frame_count=(uint64_t)slice_groups*tc*kt;
        p->array_stream_cycles=((uint64_t)sr+(uint64_t)(q->size-1u)*slice_groups)*tc*kt;
        p->weight_shift_rows=weight_loads*q->size;
        p->micro_commands=path?p->frame_count:0u;
        array=p->array_stream_cycles+p->weight_shift_rows;
        p->service_estimate=(transfers>array?transfers:array)+
            p->micro_commands*q->micro_setup_cycles;
        p->service_estimate+=gempact_im2col_cost(q,mode,r,w,path,slice,resident,stream,stationary);
    }
    return 1;
}

static inline int gempact_device_better(const gempact_dispatch_t *a,const gempact_dispatch_t *b) {
    if(a->service_estimate!=b->service_estimate) return a->service_estimate<b->service_estimate;
    if(a->micro_commands!=b->micro_commands) return a->micro_commands<b->micro_commands;
    if(a->operand_read_bytes!=b->operand_read_bytes) return a->operand_read_bytes<b->operand_read_bytes;
    if(a->array_stream_cycles+a->weight_shift_rows!=b->array_stream_cycles+b->weight_shift_rows)
        return a->array_stream_cycles+a->weight_shift_rows<b->array_stream_cycles+b->weight_shift_rows;
    if(a->adaptive_active!=b->adaptive_active) return a->adaptive_active<b->adaptive_active;
    if(a->payload_bound_bytes!=b->payload_bound_bytes) return a->payload_bound_bytes<b->payload_bound_bytes;
    if(a->tiling.ia_reuse!=b->tiling.ia_reuse) return a->tiling.ia_reuse<b->tiling.ia_reuse;
    if(a->tiling.w_reuse!=b->tiling.w_reuse) return a->tiling.w_reuse<b->tiling.w_reuse;
    return a->is_mode<b->is_mode;
}

static inline int gempact_plan_device_exhaustive_visit(const gempact_device_request_t *q,
    gempact_dispatch_t *out,gempact_dispatch_t *raw_out,
    gempact_candidate_visitor_t visitor,void *context) {
    uint32_t evaluated=0;int found=0,raw_found=0;gempact_dispatch_t best={0},raw_best={0};
    if(!q||!out||!q->rows||!q->cols||!q->reduction||q->mode>2u||q->size!=16u||
       !q->ia_bytes||q->ia_bytes%(q->size*q->size*2u)||!q->frames||q->frames>64u||
       !q->pool_bytes||q->pool_bytes%64u||q->ps_bank_count>8u||
       (q->ps_bank_count&&q->pool_bytes%(16u*q->ps_bank_count))||!q->lhs_element_bytes||
       q->estimated_record_bytes<16u||q->estimated_record_bytes>64u||!gempact_im2col_valid(q)) return 0;
    for(uint32_t mode=0;mode<2u;++mode) {
        uint32_t slots=q->ia_bytes/(q->size*q->size*2u),ct=gempact_ceil_div(mode?q->rows:q->cols,q->size);
        if((q->mode!=2u&&q->mode!=mode)||(mode&&!q->is_supported)) continue;
        if(q->ia_bank_count==1u&&!(q->compact_mode_mask&(1u<<mode))) continue;
        if(q->compact_mode_mask&(1u<<mode)) slots*=2u;
        for(uint32_t r=1;r<=slots/2u;r*=2u) {
            if(q->req_r&&r>q->req_r) continue;
            for(uint32_t w=1;w<=gempact_window_limit(q,ct);++w) {
                if(q->req_w&&w>q->req_w) continue;
                for(uint32_t path=0;path<4u;++path) {
                    for(uint32_t raw=1;raw<=2u;++raw) {
                        gempact_dispatch_t candidate;
                        uint32_t force_raw=raw==1u;
                        if(!force_raw&&(!q->adaptive||!q->frame_capable)) continue;
                        if(!gempact_device_candidate(q,mode,r,w,path,force_raw,&candidate)) continue;
                        if(!force_raw&&!candidate.adaptive_active) continue;
                        ++evaluated;
                        if(visitor) visitor(q,&candidate,UINT64_MAX,UINT64_MAX,context);
                        if(force_raw&&(!raw_found||gempact_device_better(&candidate,&raw_best))) {raw_best=candidate;raw_found=1;}
                        if(!found||gempact_device_better(&candidate,&best)) {best=candidate;found=1;}
                    }
                }
            }
        }
    }
    if(!found) return 0;
    gempact_raw_execution(&best,raw_found?&raw_best:0);
    if(raw_out) *raw_out=raw_best;
    best.candidates_evaluated=evaluated;*out=best;return 1;
}

static inline int gempact_plan_device_exhaustive_pair(const gempact_device_request_t *q,
    gempact_dispatch_t *out,gempact_dispatch_t *raw_out)
{
    return gempact_plan_device_exhaustive_visit(q,out,raw_out,0,0);
}

static inline int gempact_plan_device_exhaustive(const gempact_device_request_t *q,gempact_dispatch_t *out)
{
    return gempact_plan_device_exhaustive_pair(q,out,0);
}

static inline uint32_t gempact_estimated_count(const gempact_device_request_t *q,
    uint32_t rows,uint32_t slice,uint32_t w,uint32_t limit)
{
    uint32_t parts=gempact_ceil_div(rows,slice),count=w*parts;
    if(count>q->frames) count=q->frames;
    return count<limit?count:limit;
}

static inline uint32_t gempact_record_limit(const gempact_device_request_t *q,
    uint32_t rows,uint32_t slice,uint32_t raw,uint32_t directory_frames)
{
    if(q->reduction<=q->size) return directory_frames;
    uint32_t reserve=gempact_min_u32(rows,slice);
    uint32_t literal=raw?64u:gempact_literal_cap(q);
    uint32_t reserved_bank=gempact_reserve_bank_words(q,reserve,literal);
    uint32_t bytes=literal+(reserve-1u)*(raw?64u:gempact_min_u32(q->estimated_record_bytes,literal));
    uint32_t per_bank=gempact_ceil_div(bytes,16u*gempact_ps_banks(q));
    return gempact_min_u32(directory_frames,
        1u+(gempact_ps_bank_words(q)-reserved_bank)/per_bank);
}

/* The wide-arithmetic implementation evaluates the complete candidate set.
 * It also serves as the reference for the bounded 32-bit search. */
static inline int gempact_plan_device_general(const gempact_device_request_t *q,
                                               gempact_dispatch_t *out)
{
    return gempact_plan_device_exhaustive(q,out);
}
#if defined(__GNUC__) || defined(__clang__)
#define GEMPACT_SCORE_INLINE static inline __attribute__((always_inline))
#else
#define GEMPACT_SCORE_INLINE static inline
#endif

typedef struct {
    uint32_t sr,sc,tc,kt,r,shift,slots,groups,rows,full,tail,reload;
    uint32_t stream_base,stationary_total,weight_total,array_total,frames_total,im2col_minimum;
    uint32_t image_sensitive,image_base,image_unreused,image_overflow;
} gempact_score_geometry_t;

typedef struct {
    uint32_t service,micro,bytes,stream,weight,bound,resident;
    uint32_t r,w,mode,path,raw,owner;
    uint32_t stream_work,stationary_work;
} gempact_score_t;

static inline void gempact_visit_score(const gempact_device_request_t *q,
    const gempact_score_t *p,gempact_candidate_visitor_t visitor,void *context);

enum { GEMPACT_SCORE_R_LEVELS = 7 };
typedef struct {uint32_t long_seen[2][2*GEMPACT_SCORE_R_LEVELS],evaluated;} gempact_search_cache_t;

GEMPACT_SCORE_INLINE uint32_t gempact_small_ceil(uint32_t a,uint32_t b)
{
    if(b==1u) return a;
    if(b==2u) return (a>>1)+(uint32_t)((a&1u)!=0u);
    if(b==4u) return (a>>2)+(uint32_t)((a&3u)!=0u);
    if(b==8u) return (a>>3)+(uint32_t)((a&7u)!=0u);
    if(b==16u) return (a>>4)+(uint32_t)((a&15u)!=0u);
    if(b==32u) return (a>>5)+(uint32_t)((a&31u)!=0u);
    if(b==64u) return (a>>6)+(uint32_t)((a&63u)!=0u);
    if(b==128u) return (a>>7)+(uint32_t)((a&127u)!=0u);
    return a?1u+(a-1u)/b:0u;
}

GEMPACT_SCORE_INLINE uint32_t gempact_small_floor(uint32_t a,uint32_t b)
{
    if(b==1u) return a;
    if(b==2u) return a>>1;
    if(b==4u) return a>>2;
    if(b==8u) return a>>3;
    if(b==16u) return a>>4;
    if(b==32u) return a>>5;
    if(b==64u) return a>>6;
    if(b==128u) return a>>7;
    return a/b;
}

GEMPACT_SCORE_INLINE uint32_t gempact_score_scaled_bytes(uint32_t elements,uint32_t bytes)
{
    return bytes==2u?elements<<1:elements;
}

GEMPACT_SCORE_INLINE uint32_t gempact_score_setup(uint32_t frames,uint32_t cycles)
{
    return cycles==32u?frames<<5:frames*cycles;
}

GEMPACT_SCORE_INLINE uint32_t gempact_score_im2col_minimum(
    const gempact_device_request_t *q,uint32_t elements)
{
    return q->im2col_source_bytes?
        elements+6u*gempact_small_ceil(elements,q->im2col_pixel_channels):0u;
}

GEMPACT_SCORE_INLINE uint32_t gempact_score_im2col(
    const gempact_device_request_t *q,const gempact_score_geometry_t *g,
    uint32_t mode,uint32_t w,uint32_t path,uint32_t slice,uint32_t resident,
    uint32_t stream,uint32_t stationary)
{
    uint32_t elements,positions,footprint,overflow,bytes,unreused,cost;
    if(!q->im2col_source_bytes) return 0;
    elements=mode?stationary:stream;
    cost=mode&&stationary==g->stationary_total?g->image_base:
        gempact_score_im2col_minimum(q,elements);
    if(q->im2col_base_fraction_q8==256u) return cost;
    if(!mode) overflow=g->image_overflow;
    else {
        if(!g->image_sensitive) return cost;
        positions=gempact_min_u32(q->rows,(mode?w:g->r)<<4);
        if(mode&&path&&resident) {
            uint32_t parts=gempact_small_ceil(g->rows,slice);
            uint32_t columns=gempact_small_floor(resident,parts);
            if(!columns) columns=1u;
            positions=gempact_min_u32(positions,columns<<4);
        }
        footprint=positions*q->im2col_stage_bytes_per_position;
        if(footprint<=q->im2col_cache_bytes) return cost;
        overflow=256u-(q->im2col_cache_bytes<<8)/footprint;
    }
    if(!overflow) return cost;
    bytes=elements*q->im2col_source_bytes;
    unreused=mode&&stationary==g->stationary_total?g->image_unreused:
        (bytes>>8)*(256u-q->im2col_base_fraction_q8)+
        (((bytes&255u)*(256u-q->im2col_base_fraction_q8))>>8);
    return cost+(unreused>>9)*overflow+(((unreused&511u)*overflow)>>9);
}

GEMPACT_SCORE_INLINE uint32_t gempact_score_parameter_bytes(const gempact_device_request_t *q,
    uint32_t mode,uint32_t path,uint32_t slice_rows)
{
    uint32_t groups=mode?(path?gempact_small_ceil(q->rows,16u):1u):
        gempact_small_ceil(q->rows,slice_rows);
    uint32_t bytes=q->cols<<2;
    if(q->per_channel) bytes+=bytes<<1;
    return groups==1u?bytes:bytes*groups;
}

static inline void gempact_score_group(const gempact_device_request_t *q,
    const gempact_score_geometry_t *g,uint32_t rows,uint32_t slice,uint32_t count,
    uint32_t *stream,uint32_t *stationary,uint32_t *loads)
{
    uint32_t parts=gempact_small_ceil(rows,slice);
    uint32_t total=g->tc*parts,windows=gempact_small_ceil(total,count);
    if(parts==1u) {
        *stream=rows*(q->reduction+(windows-1u)*g->reload);
        *stationary=g->sc*q->reduction;
        *loads=g->tc*g->kt;
    } else {
        uint32_t last=total-(windows-1u)*count,boundaries=windows-1u;
        uint32_t period=parts/gempact_gcd(count,parts);
        uint32_t splits=boundaries-gempact_small_floor(boundaries,period);
        uint32_t final_splits=boundaries-gempact_small_floor(total-parts,count);
        uint32_t tail=g->sc-((g->tc-1u)<<4);
        uint32_t extra=g->kt==1u?0u:(splits<<4)-final_splits*(16u-tail);
        if(g->kt==1u) splits=0u;
        uint32_t loaded=count<parts?rows*g->tc:
            (windows-1u)*rows+(last>=parts?rows:rows-(parts-last)*slice);
        *stream=rows*q->reduction+(loaded-rows)*g->reload;
        *stationary=(g->sc+extra)*q->reduction;
        *loads=(g->tc+splits)*g->kt;
    }
}

static inline int gempact_score_fragment(const gempact_device_request_t *q,
    const gempact_score_geometry_t *g,uint32_t mode,uint32_t w,uint32_t path,
    uint32_t raw,uint32_t full_limit,uint32_t tail_limit,gempact_score_t *p)
{
    uint32_t slice=g->rows,stream,stationary,loads,resident=0;
    uint32_t col_groups=gempact_small_ceil(g->tc,w);
    if(col_groups>65535u) return 0;
    if(path==2u) slice=gempact_min_u32(slice,16u);
    if(path==3u) slice=gempact_min_u32(slice,32u);
    if(!path) {
        stream=g->sr*q->reduction*col_groups;
        stationary=g->sc*q->reduction*g->groups;
        loads=g->groups*g->tc*g->kt;
    } else {
        stream=stationary=loads=0;
        if(g->full) {
            uint32_t count=gempact_min_u32(w*((g->r<<4)/slice),q->frames);
            uint32_t a,b,c;
            count=gempact_min_u32(count,full_limit);
            gempact_score_group(q,g,g->r<<4,slice,count,&a,&b,&c);
            stream=a*g->full;stationary=b*g->full;loads=c*g->full;resident=count;
        }
        if(g->tail) {
            uint32_t tail_slice=gempact_min_u32(slice,g->tail);
            uint32_t count=gempact_min_u32(w*gempact_small_ceil(g->tail,tail_slice),q->frames);
            uint32_t a,b,c;
            count=gempact_min_u32(count,tail_limit);
            gempact_score_group(q,g,g->tail,tail_slice,count,&a,&b,&c);
            stream+=a;stationary+=b;loads+=c;if(resident<count) resident=count;
        }
        if(g->kt==1u&&g->tc==1u) {stationary=g->sc*q->reduction;loads=1u;}
    }
    {
        uint32_t parts=path==2u?gempact_small_ceil(g->sr,16u):
                       path==3u?gempact_small_ceil(g->sr,32u):g->groups;
        uint32_t frame_count=parts*g->tc*g->kt;
        uint32_t bytes=mode?gempact_score_scaled_bytes(stationary,q->lhs_element_bytes)+stream:
                            gempact_score_scaled_bytes(stream,q->lhs_element_bytes)+stationary;
        bytes+=gempact_score_parameter_bytes(q,mode,path,slice);
        uint32_t array=(g->sr+15u*parts)*g->tc*g->kt,shift=loads<<4;
        uint32_t transfers=(bytes>>2)+(uint32_t)((bytes&3u)!=0u);
        uint32_t micro=path?frame_count:0u;
        p->service=(transfers>array+shift?transfers:array+shift)+gempact_score_setup(micro,q->micro_setup_cycles);
        p->service+=gempact_score_im2col(q,g,mode,w,path,slice,resident,stream,stationary);
        p->micro=micro;p->bytes=bytes;p->stream=array;p->weight=shift;
        p->bound=g->kt>1u?(g->rows*gempact_min_u32(w,g->tc))<<6:0u;p->resident=resident;
        p->r=g->r;p->w=w;p->mode=mode;p->path=path;p->raw=raw;
        p->stream_work=stream;p->stationary_work=stationary;
    }
    return 1;
}

GEMPACT_SCORE_INLINE void gempact_score_consider(
    uint32_t service,uint32_t micro,uint32_t bytes,uint32_t stream,uint32_t weight,
    uint32_t bound,uint32_t resident,uint32_t r,uint32_t w,uint32_t mode,uint32_t path,
    uint32_t raw,uint32_t owner,gempact_score_t *best,int *found)
{
    if(*found) {
        if(service!=best->service) {if(service>best->service) return;}
        else if(micro!=best->micro) {if(micro>best->micro) return;}
        else if(bytes!=best->bytes) {if(bytes>best->bytes) return;}
        else if(stream+weight!=best->stream+best->weight) {if(stream+weight>best->stream+best->weight) return;}
        else if(raw!=best->raw) {if(raw<best->raw) return;}
        else if(bound!=best->bound) {if(bound>best->bound) return;}
        else if(r!=best->r) {if(r>best->r) return;}
        else if(w!=best->w) {if(w>best->w) return;}
        else if(mode>=best->mode) return;
    }
    best->service=service;best->micro=micro;best->bytes=bytes;best->stream=stream;best->weight=weight;
    best->bound=bound;best->resident=resident;best->r=r;best->w=w;best->mode=mode;best->path=path;best->raw=raw;best->owner=owner;
    *found=1;
}

GEMPACT_SCORE_INLINE int gempact_score_candidate(const gempact_device_request_t *q,
    const gempact_score_geometry_t *g,uint32_t mode,uint32_t w,uint32_t path,
    uint32_t raw,uint32_t full_limit,uint32_t tail_limit,gempact_score_t *best,int *found,
    gempact_candidate_visitor_t visitor,void *context)
{
    if(path>=2u) {
        gempact_score_t p;
        if(!gempact_score_fragment(q,g,mode,w,path,raw,full_limit,tail_limit,&p)) return 0;
        if(visitor) gempact_visit_score(q,&p,visitor,context);
        gempact_score_consider(p.service,p.micro,p.bytes,p.stream,p.weight,p.bound,p.resident,
                              p.r,p.w,p.mode,p.path,p.raw,q->ia_bank_count,best,found);
        return 1;
    }
    uint32_t rounds=gempact_small_ceil(g->tc,w),resident=0,stream;
    uint32_t stationary=g->stationary_total,weight=g->weight_total;
    if(rounds>65535u) return 0;
    if(!path) stream=g->stream_base*rounds;
    else {
        uint32_t repeat_rows=0;
        {
            if(g->full) {
                uint32_t count=gempact_min_u32(w,full_limit);
                repeat_rows=(gempact_small_ceil(g->tc,count)-1u)*(g->sr-g->tail);resident=count;
            }
            if(g->tail) {
                uint32_t count=gempact_min_u32(w,tail_limit);
                repeat_rows+=(gempact_small_ceil(g->tc,count)-1u)*g->tail;
                if(resident<count) resident=count;
            }
        }
        stream=g->stream_base+repeat_rows*g->reload;
        if(g->kt==1u&&g->tc==1u) {stationary=g->sc*q->reduction;weight=16u;}
    }
    uint32_t bytes=mode?gempact_score_scaled_bytes(stationary,q->lhs_element_bytes)+stream:gempact_score_scaled_bytes(stream,q->lhs_element_bytes)+stationary;
    bytes+=gempact_score_parameter_bytes(q,mode,path,g->rows);
    uint32_t transfers=(bytes>>2)+(uint32_t)((bytes&3u)!=0u);
    uint32_t micro=path?g->frames_total:0u;
    uint32_t array=g->array_total+weight;
    uint32_t service=visitor?0u:(transfers>array?transfers:array)+
        gempact_score_setup(micro,q->micro_setup_cycles)+
        gempact_score_im2col(q,g,mode,w,path,g->rows,resident,stream,stationary);
    if(visitor) {
        gempact_score_t p={0};
        p.service=service;p.micro=micro;p.bytes=bytes;p.stream=g->array_total;p.weight=weight;
        p.bound=g->kt>1u?(g->rows*gempact_min_u32(w,g->tc))<<6:0u;p.resident=resident;
        p.r=g->r;p.w=w;p.mode=mode;p.path=path;p.raw=raw;p.owner=q->ia_bank_count;
        p.stream_work=stream;p.stationary_work=stationary;
        gempact_visit_score(q,&p,visitor,context);
    }
    gempact_score_consider(service,
        micro,bytes,g->array_total,weight,g->kt>1u?(g->rows*gempact_min_u32(w,g->tc))<<6:0u,resident,
        g->r,w,mode,path,raw,q->ia_bank_count,best,found);
    return 1;
}

GEMPACT_SCORE_INLINE int gempact_score_better(const gempact_score_t *a,const gempact_score_t *b)
{
    if(a->service!=b->service) return a->service<b->service;
    if(a->micro!=b->micro) return a->micro<b->micro;
    if(a->bytes!=b->bytes) return a->bytes<b->bytes;
    if(a->stream+a->weight!=b->stream+b->weight) return a->stream+a->weight<b->stream+b->weight;
    if(a->raw!=b->raw) return a->raw>b->raw;
    if(a->bound!=b->bound) return a->bound<b->bound;
    if(a->r!=b->r) return a->r<b->r;
    if(a->w!=b->w) return a->w<b->w;
    return a->mode<b->mode;
}

static inline gempact_tiling_t gempact_score_tiling(const gempact_device_request_t *q,
                                                   const gempact_score_t *p)
{
    uint32_t sr=p->mode?q->cols:q->rows,sc=p->mode?q->rows:q->cols;
    uint32_t tr=gempact_small_ceil(sr,16u),tc=gempact_small_ceil(sc,16u);
    gempact_tiling_t t;
    t.ia_reuse=p->r;t.w_reuse=p->w;
    t.row_groups=gempact_small_ceil(tr,p->r);t.row_tail_tiles=((tr-1u)&(p->r-1u))+1u;
    t.col_groups=gempact_small_ceil(tc,p->w);t.col_tail_tiles=tc-(t.col_groups-1u)*p->w;
    return t;
}

GEMPACT_SCORE_INLINE void gempact_score_emit(const gempact_device_request_t *q,
    const gempact_score_t *p,const gempact_score_t *raw,uint32_t evaluated,gempact_dispatch_t *out)
{
    uint32_t sr=p->mode?q->cols:q->rows,sc=p->mode?q->rows:q->cols;
    uint32_t slice=gempact_min_u32(sr,p->r<<4),slots=q->ia_bytes>>9;
    uint32_t tc=gempact_small_ceil(sc,16u),kt=gempact_small_ceil(q->reduction,16u),parts;
    if(q->compact_mode_mask&(1u<<p->mode)) slots*=2u;
    if(p->path==2u) slice=gempact_min_u32(slice,16u);
    if(p->path==3u) slice=gempact_min_u32(slice,32u);
    out->tiling=gempact_score_tiling(q,p);
    out->ia_bank_count=0u;out->ia_bytes=q->ia_bytes;out->pool_bytes=q->pool_bytes;
    gempact_raw_execution(out,0);
    if(raw) {
        out->raw_safe=gempact_score_tiling(q,raw);out->raw_safe_is_mode=raw->mode;
        out->raw_safe_ps_control=1u|(raw->path?2u:0u)|
            (raw->path==1u?12u:raw->path==2u?4u:raw->path==3u?8u:0u);
        out->raw_safe_slice_rows=gempact_min_u32(raw->mode?q->cols:q->rows,raw->r<<4);
        if(raw->path==2u) out->raw_safe_slice_rows=gempact_min_u32(out->raw_safe_slice_rows,16u);
        if(raw->path==3u) out->raw_safe_slice_rows=gempact_min_u32(out->raw_safe_slice_rows,32u);
        out->raw_safe_ia_bytes=q->ia_bytes;out->raw_safe_pool_bytes=q->pool_bytes;
    }
    out->is_mode=p->mode;out->frame_rows=slice;out->adaptive_active=!p->raw;
    out->reduction=q->reduction;out->lhs_element_bytes=q->lhs_element_bytes;out->bus_bytes=4u;
    out->payload_bound_bytes=p->bound;
    out->lhs_read_rounds=p->mode?out->tiling.row_groups:out->tiling.col_groups;
    out->rhs_read_rounds=p->mode?out->tiling.col_groups:out->tiling.row_groups;
    out->operand_read_bytes=p->bytes;
    parts=p->path?gempact_small_ceil(sr,slice):out->tiling.row_groups;
    out->frame_count=(uint32_t)(parts*tc*kt);
    out->array_stream_cycles=p->stream;out->service_estimate=p->service;
    out->ps_control=(p->raw?1u:0u)|(p->path?2u:0u)|
        (p->path==1u?12u:p->path==2u?4u:p->path==3u?8u:0u);
    out->ia_slots=slots;out->slice_rows=slice;out->predicted_resident_frames=p->resident;
    out->literal_record_bytes=p->raw?64u:gempact_literal_cap(q);
    out->estimated_record_bytes=p->raw?64u:
        gempact_min_u32(q->estimated_record_bytes,out->literal_record_bytes);
    out->candidates_evaluated=evaluated;out->micro_commands=p->micro;out->weight_shift_rows=p->weight;
}

static inline void gempact_visit_score(const gempact_device_request_t *q,
    const gempact_score_t *p,gempact_candidate_visitor_t visitor,void *context)
{
    gempact_dispatch_t candidate;
    gempact_score_emit(q,p,0,0u,&candidate);
    visitor(q,&candidate,p->stream_work,p->stationary_work,context);
}

static inline uint32_t gempact_score_frame_search(const gempact_device_request_t *q,
    const gempact_score_geometry_t *g,uint32_t mode,uint32_t max_w,uint32_t raw,
    gempact_score_t *best,int *found,gempact_candidate_visitor_t visitor,void *context)
{
    uint32_t evaluated=0u;
    if(!q->frame_capable||(!raw&&(!q->adaptive||g->kt<=1u))) return 0u;
    uint32_t literal=raw?64u:gempact_literal_cap(q);
    if(g->kt>1u&&literal/16u>gempact_ps_banks(q)) return 0u;
    uint32_t whole_fits=gempact_directory_frames(q,g->rows)&&
        (g->kt<=1u||gempact_reserve_bank_words(q,g->rows,literal)<=gempact_ps_bank_words(q));
    for(uint32_t path=1u;path<4u;++path) {
        /* With the complete K history resident, slicing adds frame work
         * without reducing operand reads or the minimum image window. */
        if(path>=2u&&!g->reload&&whole_fits) continue;
        uint32_t slice=g->rows,parts,frame_limit,full_limit=0u,tail_limit=0u;
        uint32_t upper=gempact_min_u32(max_w,g->tc),first=1u,previous=UINT32_MAX;
        if(path==2u) slice=gempact_min_u32(slice,16u);
        if(path==3u) slice=gempact_min_u32(slice,32u);
        if((path==2u&&slice==g->rows)||(path==3u&&(slice==g->rows||slice==16u))) continue;
        frame_limit=gempact_directory_frames(q,slice);
        if(!frame_limit||(g->kt>1u&&gempact_reserve_bank_words(q,slice,literal)>gempact_ps_bank_words(q))) continue;
        if(!raw&&gempact_ps_banks(q)>=4u)
            first=gempact_ps_bank_words(q)/gempact_reserve_bank_words(q,g->rows,64u)+1u;
        if(first>upper) continue;
        parts=path==1u?g->groups:gempact_small_ceil(g->sr,slice);
        uint32_t micro=parts*g->tc*g->kt;
        uint32_t stationary=g->kt==1u&&g->tc==1u?g->sc*q->reduction:g->stationary_total;
        uint32_t minimum_bytes=mode?gempact_score_scaled_bytes(stationary,q->lhs_element_bytes)+g->stream_base:
            gempact_score_scaled_bytes(g->stream_base,q->lhs_element_bytes)+stationary;
        minimum_bytes+=gempact_score_parameter_bytes(q,mode,path,slice);
        uint32_t transfers=(minimum_bytes>>2)+(uint32_t)((minimum_bytes&3u)!=0u);
        uint32_t array=(g->sr+15u*parts)*g->tc*g->kt+
            (g->kt==1u&&g->tc==1u?16u:g->weight_total);
        uint32_t lower=(transfers>array?transfers:array)+gempact_score_setup(micro,q->micro_setup_cycles)+g->im2col_minimum;
        if(!visitor&&*found&&(lower>best->service||(lower==best->service&&micro>best->micro))) continue;
        if(g->full) full_limit=gempact_record_limit(q,g->r<<4,slice,raw,frame_limit);
        if(g->tail) tail_limit=gempact_record_limit(q,g->tail,gempact_min_u32(slice,g->tail),raw,frame_limit);
        if(path==1u&&!g->image_sensitive) {
            uint32_t w=first,valid_min=gempact_small_ceil(g->tc,65535u);
            if(g->reload&&g->full) {
                uint32_t count=gempact_min_u32(upper,full_limit);
                uint32_t needed=gempact_small_ceil(g->tc,gempact_small_ceil(g->tc,count));
                if(w<needed) w=needed;
            }
            if(g->reload&&g->tail) {
                uint32_t count=gempact_min_u32(upper,tail_limit);
                uint32_t needed=gempact_small_ceil(g->tc,gempact_small_ceil(g->tc,count));
                if(w<needed) w=needed;
            }
            if(w<valid_min) w=valid_min;
            if(w<=upper) evaluated+=(uint32_t)gempact_score_candidate(q,g,mode,w,path,raw,
                full_limit,tail_limit,best,found,visitor,context);
            continue;
        }
        for(uint32_t w=first;w<=upper;++w) {
            uint32_t full_count=g->full?gempact_estimated_count(q,g->r<<4,slice,w,full_limit):0u;
            uint32_t tail_count=g->tail?gempact_estimated_count(q,g->tail,gempact_min_u32(slice,g->tail),w,tail_limit):0u;
            uint32_t equivalence=full_count*(q->frames+1u)+tail_count;
            if(equivalence==previous||gempact_small_ceil(g->tc,w)>65535u) continue;
            previous=equivalence;
            if(!visitor&&*found&&lower>best->service) continue;
            evaluated+=(uint32_t)gempact_score_candidate(q,g,mode,w,path,raw,full_limit,tail_limit,best,found,visitor,context);
        }
    }
    return evaluated;
}

GEMPACT_SCORE_INLINE int gempact_score_seed(const gempact_dispatch_t *p,
                                            gempact_score_t *s)
{
    if(!p||!p->tiling.ia_reuse||p->service_estimate>UINT32_MAX) return 0;
    s->service=(uint32_t)p->service_estimate;s->micro=(uint32_t)p->micro_commands;
    s->bytes=(uint32_t)p->operand_read_bytes;s->stream=(uint32_t)p->array_stream_cycles;
    s->weight=(uint32_t)p->weight_shift_rows;s->bound=(uint32_t)p->payload_bound_bytes;
    s->resident=p->predicted_resident_frames;s->r=p->tiling.ia_reuse;s->w=p->tiling.w_reuse;
    s->mode=p->is_mode;s->raw=p->ps_control&1u;s->owner=p->ia_bank_count;
    s->path=!(p->ps_control&2u)?0u:(p->ps_control>>2)==3u?1u:(p->ps_control>>2)==1u?2u:3u;
    return 1;
}

/* This arithmetic range covers ordinary edge-model operators. The volume
 * bound includes transfer work, array rows and command setup, so each score
 * fits in 32 bits. For V=rows*cols*reduction, transferred bytes are at most
 * 15*V including parameter arrays, array plus stationary shift rows at most
 * 32*V, image service at most 8*V, and command count at
 * most V. Larger requests use the general 64-bit implementation. */
GEMPACT_SCORE_INLINE int gempact_plan_device_seeded(const gempact_device_request_t *q,
    gempact_dispatch_t *out,gempact_dispatch_t *raw_out,const gempact_dispatch_t *global_best,
    const gempact_dispatch_t *global_raw,gempact_search_cache_t *search_cache,
    gempact_candidate_visitor_t visitor,void *context)
{
    uint32_t evaluated=0;int found=0,raw_found=0;
    gempact_score_t best,raw_best;
    if(!q||!out||!q->rows||!q->cols||!q->reduction||q->size!=16u||q->mode>2u||
       !q->frames||q->frames>64u||!q->pool_bytes||q->pool_bytes%64u||q->ps_bank_count>8u||
       (q->ps_bank_count&&q->pool_bytes%(16u*q->ps_bank_count))||
       (q->ia_bytes!=1024u&&q->ia_bytes!=2048u&&q->ia_bytes!=4096u&&
        q->ia_bytes!=8192u&&q->ia_bytes!=16384u&&q->ia_bytes!=32768u)||
       !q->lhs_element_bytes||q->lhs_element_bytes>2u||q->micro_setup_cycles>1024u||
       q->estimated_record_bytes<16u||q->estimated_record_bytes>64u||!gempact_im2col_valid(q)||
       q->im2col_stage_bytes_per_position>UINT32_MAX/1024u||q->im2col_cache_bytes>UINT32_MAX/256u||
       q->rows>1048575u||q->cols>1048575u||q->reduction>1048575u||
       (uint64_t)q->rows*q->cols*q->reduction>UINT32_MAX/(40u+q->micro_setup_cycles))
    {
        int accepted=gempact_plan_device_exhaustive_visit(q,out,raw_out,visitor,context);
        if(search_cache&&accepted) search_cache->evaluated+=out->candidates_evaluated;
        return accepted;
    }
    found=gempact_score_seed(global_best,&best);raw_found=gempact_score_seed(global_raw,&raw_best);
    for(uint32_t mode=0;mode<2u;++mode) {
        gempact_score_geometry_t g;
        uint32_t slots=q->ia_bytes>>9,max_w;
        if((q->mode!=2u&&q->mode!=mode)||(mode&&!q->is_supported)) continue;
        if(q->ia_bank_count==1u&&!(q->compact_mode_mask&(1u<<mode))) continue;
        if(q->compact_mode_mask&(1u<<mode)) slots*=2u;
        g.sr=mode?q->cols:q->rows;g.sc=mode?q->rows:q->cols;
        g.tc=gempact_small_ceil(g.sc,16u);g.kt=gempact_small_ceil(q->reduction,16u);g.slots=slots;
        g.stream_base=g.sr*q->reduction;
        max_w=gempact_window_limit(q,g.tc);
        g.image_sensitive=mode&&(gempact_image_window_sensitive(q,max_w)||
            (visitor&&q->im2col_source_bytes));
        uint32_t maximum_r=slots>>1;
        uint32_t maximum_shift=maximum_r==64u?6u:maximum_r==32u?5u:maximum_r==16u?4u:
            maximum_r==8u?3u:maximum_r==4u?2u:maximum_r==2u?1u:0u;
        for(uint32_t r=maximum_r,shift=maximum_shift;r;r>>=1,--shift) {
            uint32_t raw_max=max_w,capacity=slots/r;
            /* A larger R beyond the physical row tiles cannot reduce work;
             * its available K history is no larger than the smaller R. */
            uint32_t dominated_r=r>1u&&g.sr<=((r>>1)<<4);
            if(dominated_r||(q->req_r&&r>q->req_r)) continue;
            g.r=r;g.shift=shift;g.rows=gempact_min_u32(g.sr,r<<4);
            g.full=g.sr>>(shift+4u);g.tail=g.sr&((r<<4)-1u);
            g.groups=g.full+(g.tail!=0u);if(g.groups>65535u) continue;
            g.frames_total=g.groups*g.tc*g.kt;g.weight_total=g.frames_total<<4;
            g.array_total=(g.sr+15u*g.groups)*g.tc*g.kt;g.stationary_total=g.sc*q->reduction*g.groups;
            g.im2col_minimum=gempact_score_im2col_minimum(q,mode?
                (g.kt==1u&&g.tc==1u?g.sc*q->reduction:g.stationary_total):g.stream_base);
            g.image_base=gempact_score_im2col_minimum(q,g.stationary_total);
            g.image_unreused=g.image_overflow=0u;
            if(q->im2col_source_bytes&&q->im2col_base_fraction_q8<256u) {
                if(mode) {
                    uint32_t bytes=g.stationary_total*q->im2col_source_bytes;
                    g.image_unreused=(bytes>>8)*(256u-q->im2col_base_fraction_q8)+
                        (((bytes&255u)*(256u-q->im2col_base_fraction_q8))>>8);
                } else {
                    uint32_t footprint=gempact_min_u32(q->rows,r<<4)*q->im2col_stage_bytes_per_position;
                    if(footprint>q->im2col_cache_bytes)
                        g.image_overflow=256u-(q->im2col_cache_bytes<<8)/footprint;
                }
            }
            g.reload=g.kt<=capacity?0u:g.kt>=2u*capacity?q->reduction:
                ((2u*(g.kt-capacity)-1u)<<4)+((q->reduction-1u)&15u)+1u;
            uint32_t directory_frames=gempact_directory_frames(q,g.rows);
            if(g.kt>1u) {
                uint32_t legal=gempact_ps_banks(q)<4u?0u:
                    gempact_min_u32(gempact_ps_bank_words(q)/gempact_reserve_bank_words(q,g.rows,64u),directory_frames);
                if(legal<g.tc) raw_max=gempact_min_u32(raw_max,legal);
            }
            if(raw_max) {
                uint32_t first=1u,previous_rounds=UINT32_MAX;
                uint32_t minimum=g.array_total+g.weight_total+g.im2col_minimum;
                if(!g.image_sensitive&&!visitor) {
                    uint32_t largest=1u;while(largest<=raw_max/2u) largest*=2u;
                    uint32_t rounds=gempact_small_ceil(g.tc,largest);
                    while(gempact_small_ceil(g.tc,first)>rounds) first*=2u;
                }
                for(uint32_t w=first;w<=raw_max;w*=2u) {
                    uint32_t rounds=gempact_small_ceil(g.tc,w);
                    if((!visitor&&rounds==previous_rounds)||rounds>65535u) continue;
                    previous_rounds=rounds;
                    if(search_cache&&(search_cache->long_seen[1][mode*GEMPACT_SCORE_R_LEVELS+shift]&w)) continue;
                    if(search_cache) search_cache->long_seen[1][mode*GEMPACT_SCORE_R_LEVELS+shift]|=w;
                    if(!visitor&&raw_found&&minimum>raw_best.service) continue;
                    evaluated+=(uint32_t)gempact_score_candidate(q,&g,mode,w,0u,1u,0u,0u,&raw_best,&raw_found,visitor,context);
                    if(!g.image_sensitive&&!visitor) break;
                }
            }
            evaluated+=gempact_score_frame_search(q,&g,mode,max_w,1u,&raw_best,&raw_found,visitor,context);
            if(raw_found&&(!found||gempact_score_better(&raw_best,&best))) {best=raw_best;found=1;}
            if(!q->adaptive||!q->frame_capable||g.kt<=1u||gempact_literal_cap(q)/16u>gempact_ps_banks(q)) continue;
            {
                uint32_t bank_rows=gempact_reserve_bank_words(q,g.rows,gempact_literal_cap(q));
                uint32_t capacity=gempact_min_u32(gempact_ps_bank_words(q)/bank_rows,directory_frames);
                uint32_t long_max=capacity>=g.tc?max_w:gempact_min_u32(max_w,capacity);
                uint32_t minimum=g.array_total+g.weight_total+g.im2col_minimum;
                for(uint32_t w=1u;w<=long_max;w*=2u) {
                    if(w<=raw_max||gempact_small_ceil(g.tc,w)>65535u) continue;
                    if(search_cache&&(search_cache->long_seen[0][mode*GEMPACT_SCORE_R_LEVELS+shift]&w)) continue;
                    if(search_cache) search_cache->long_seen[0][mode*GEMPACT_SCORE_R_LEVELS+shift]|=w;
                    if(!visitor&&found&&minimum>best.service) continue;
                    evaluated+=(uint32_t)gempact_score_candidate(q,&g,mode,w,0u,0u,0u,0u,&best,&found,visitor,context);
                }
            }
            evaluated+=gempact_score_frame_search(q,&g,mode,max_w,0u,&best,&found,visitor,context);
        }
    }
    if(search_cache) search_cache->evaluated+=evaluated;
    found=found&&best.owner==q->ia_bank_count;
    raw_found=raw_found&&raw_best.owner==q->ia_bank_count;
    if(!found&&!raw_found) return 0;
    gempact_score_emit(q,found&&(!raw_found||gempact_score_better(&best,&raw_best))?&best:&raw_best,
        raw_found?&raw_best:0,evaluated,out);
    if(raw_out) {
        if(raw_found) gempact_score_emit(q,&raw_best,&raw_best,evaluated,raw_out);
        else *raw_out=(gempact_dispatch_t){0};
    }
    return 1;
}

GEMPACT_SCORE_INLINE int gempact_plan_device_pair(const gempact_device_request_t *q,
    gempact_dispatch_t *out,gempact_dispatch_t *raw_out)
{
    return gempact_plan_device_seeded(q,out,raw_out,0,0,0,0,0);
}

static inline int gempact_plan_device_visit(const gempact_device_request_t *q,
    gempact_dispatch_t *out,gempact_candidate_visitor_t visitor,void *context)
{
    return gempact_plan_device_seeded(q,out,0,0,0,0,visitor,context);
}

GEMPACT_SCORE_INLINE int gempact_plan_device(const gempact_device_request_t *q,gempact_dispatch_t *out)
{
    return gempact_plan_device_pair(q,out,0);
}


static inline int gempact_shared_valid(const gempact_shared_memory_t *memory)
{
    if(!memory||(memory->bank_bytes!=2048u&&memory->bank_bytes!=4096u&&
        memory->bank_bytes!=8192u)||!memory->ia_bank_mask||(memory->ia_bank_mask&~0x16u)||
        !memory->directory_rows||memory->total_bytes%memory->bank_bytes) return 0;
    uint32_t banks=memory->total_bytes/memory->bank_bytes;
    return banks>=6u&&banks<=9u;
}

static inline int gempact_plan_shared(const gempact_device_request_t *request,
    const gempact_shared_memory_t *memory,gempact_dispatch_t *out)
{
    int found=0,raw_found=0;gempact_dispatch_t best={0},raw_best={0};
    gempact_search_cache_t search_cache={0};
    if(!request||!out||!gempact_shared_valid(memory)) return 0;
    uint32_t banks=memory->total_bytes/memory->bank_bytes;
    for(uint32_t ia=1u;ia<banks&&ia<32u;++ia) {
        gempact_device_request_t q;gempact_dispatch_t candidate,raw;
        if(!(memory->ia_bank_mask&(1u<<ia))) continue;
        q=*request;q.ia_bytes=ia*memory->bank_bytes;
        q.pool_bytes=memory->total_bytes-q.ia_bytes;q.directory_rows=memory->directory_rows;
        q.ia_bank_count=ia;q.ps_bank_count=banks-ia;
        if(!gempact_plan_device_seeded(&q,&candidate,&raw,found?&best:0,raw_found?&raw_best:0,&search_cache,0,0)) continue;
        candidate.ia_bank_count=ia;
        if(raw.tiling.ia_reuse) {
            raw.ia_bank_count=ia;
            if(!raw_found||gempact_device_better(&raw,&raw_best)) {raw_best=raw;raw_found=1;}
        }
        if(!found||gempact_device_better(&candidate,&best)) {best=candidate;found=1;}
    }
    if(!found) return 0;
    gempact_raw_execution(&best,raw_found?&raw_best:0);
    best.candidates_evaluated=search_cache.evaluated;*out=best;return 1;
}


#undef GEMPACT_SCORE_INLINE
#endif
