/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_MEMORY_SCHEDULE_H
#define DSA_MEMORY_SCHEDULE_H

static inline uint64_t dsa_schedule_scale(uint64_t count, uint64_t work,
                                           uint64_t original)
{
    uint64_t product=dsa_schedule_mul(count,work);
    if (!original || product==UINT64_MAX) return UINT64_MAX;
    if (product<=UINT32_MAX && original<=UINT32_MAX)
        return (uint32_t)product/(uint32_t)original+
            ((uint32_t)product%(uint32_t)original!=0u);
    if (work<=UINT32_MAX && original<=UINT32_MAX &&
        (uint32_t)work%(uint32_t)original==0u)
        return count*((uint32_t)work/(uint32_t)original);
    return product/original+(product%original!=0u);
}

/* 按输入缓存的实际行宽计算空间窗口占用。同一缓存行内的相邻像素
 * 共用一个位置，跨输入行的步幅决定各组的最大占用数量。 */
static inline void dsa_schedule_window_footprints(const dsa_schedule_config_t *c,
    uint32_t *footprints)
{
    uint32_t line_bytes=DSA_IM2COL_CACHE_LINE_BYTES;
    uint32_t sets=c->im2col.cache_bytes/(2u*line_bytes);
    uint32_t pixel_bytes=c->im2col.input_channels*c->im2col.source_bytes;
    uint32_t pixel_shift=0u;
    uint32_t peak=0u,points=dsa_schedule_min(c->rows,1024u);
    for (uint32_t i=0u;i<=64u;++i) footprints[i]=0u;
    if (!c->im2col_input_width || !c->im2col_output_width || !c->im2col_stride_h ||
        c->im2col.group_channels<16u || !pixel_bytes ||
        c->lhs_address%line_bytes ||
        (pixel_bytes>=line_bytes ? pixel_bytes%line_bytes : pixel_bytes&(pixel_bytes-1u)) ||
        sets<2u || sets>2048u || (sets&(sets-1u))) return;
    if (pixel_bytes<line_bytes)
        for (uint32_t pixels=line_bytes/pixel_bytes;pixels>1u;pixels>>=1u) ++pixel_shift;
    uint64_t row_step=(uint64_t)c->im2col_stride_h*c->im2col_input_width;
    /* 分段累计缓存组占用，限制初始化所需的栈空间。 */
    for (uint32_t first=0u;first<sets;first+=256u) {
        uint16_t occupancy[256]={0};
        uint32_t x=0u,range_peak=0u;
        uint64_t row_base=0u,pixel=0u,previous_line=UINT64_MAX;
        for (uint32_t point=1u;point<=points;++point) {
            uint64_t line=pixel>>pixel_shift;
            uint32_t index=(uint32_t)line&(sets-1u);
            if (line!=previous_line && index>=first && index-first<256u) {
                uint32_t count=++occupancy[index-first];
                if (range_peak<count) range_peak=count;
            }
            previous_line=line;
            uint32_t footprint=range_peak*sets*line_bytes;
            uint32_t window=(point+15u)>>4;
            if (footprints[window]<footprint) footprints[window]=footprint;
            if (++x==c->im2col_output_width) {
                x=0u;row_base+=row_step;pixel=row_base;
            } else pixel+=c->im2col.stride_w;
        }
        if (peak<range_peak) peak=range_peak;
    }
    for (uint32_t i=(points+15u)/16u+1u;i<=64u;++i)
        footprints[i]=peak*sets*line_bytes;
}

static inline uint64_t dsa_schedule_image_cost(const dsa_schedule_config_t *c,
    const gempact_device_request_t *q,
    const gempact_dispatch_t *p,const uint32_t *footprints,
    uint64_t stream,uint64_t stationary)
{
    uint64_t elements,bytes,unreused,footprint,cost,descriptors;
    uint32_t positions,overflow,mode=p->is_mode,lanes;
    if (!q->im2col_source_bytes) return 0u;
    elements=mode?stationary:stream;
    if (!elements) return 0u;
    // 输入片段并行度受原始字宽和 IA 写端口限制，描述符保存和接收另计四个周期。
    lanes=gempact_min_u32(q->im2col_pixel_channels,16u/q->im2col_source_bytes);
    if (!mode && !(q->compact_mode_mask&1u))
        lanes=gempact_min_u32(lanes,dsa_schedule_bus_bytes(c));
    cost=1u+(elements-1u)/lanes;
    // 空间维与归约维分别向上取整，每个尾块具有独立描述符。
    descriptors=dsa_schedule_mul(gempact_ceil_div(q->rows,q->size),
        gempact_ceil_div(q->reduction,q->size));
    descriptors=dsa_schedule_scale(descriptors,elements,(uint64_t)q->rows*q->reduction);
    cost=dsa_schedule_add(cost,dsa_schedule_mul(descriptors,4u));
    if (!q->im2col_cache_bytes) return cost;
    positions=gempact_min_u32(q->rows,(mode?p->tiling.w_reuse:p->tiling.ia_reuse)*16u);
    if (mode&&(p->ps_control&DSA_PS_CTRL_FRAME)&&p->predicted_resident_frames) {
        uint32_t parts=gempact_ceil_div(gempact_min_u32(q->cols,p->tiling.ia_reuse*16u),p->slice_rows);
        uint32_t columns=p->predicted_resident_frames/parts;
        if (!columns) columns=1u;
        positions=gempact_min_u32(positions,columns*16u);
    }
    footprint=(uint64_t)positions*q->im2col_stage_bytes_per_position;
    if (footprints && positions<=1024u && footprints[(positions+15u)>>4]>footprint)
        footprint=footprints[(positions+15u)>>4];
    if (footprint<=q->im2col_cache_bytes) return cost;
    overflow=256u-(uint32_t)(((uint64_t)q->im2col_cache_bytes<<8)/footprint);
    bytes=elements*q->im2col_source_bytes;
    unreused=(bytes>>8)*(256u-q->im2col_base_fraction_q8)+
        (((bytes&255u)*(256u-q->im2col_base_fraction_q8))>>8);
    return cost+(unreused>>9)*overflow+(((unreused&511u)*overflow)>>9);
}

/* IA tile descriptors and cache admission add control work around each
 * stream-side load. Per-channel groups require serial parameter service
 * before IA can advance; the first group also follows the stationary
 * block in DMA priority. WS reloads parameters for each output-channel
 * tile and row group. IS retains an R-channel group across spatial tiles.
 * Frame schedules include this work in their command setup estimate. */
static inline uint64_t dsa_schedule_loader_cost(const dsa_schedule_config_t *c,
    const gempact_dispatch_t *p)
{
    uint32_t mode=p->is_mode;
    uint32_t sr=mode?c->cols:c->rows,sc=mode?c->rows:c->cols;
    uint64_t tiles,cost;
    if (p->ps_control&DSA_PS_CTRL_FRAME) return 0u;
    tiles=dsa_schedule_mul(gempact_ceil_div(sr,16u),gempact_ceil_div(c->depth,16u));
    tiles=dsa_schedule_mul(tiles,p->tiling.col_groups);
    cost=dsa_schedule_mul(tiles,DSA_SCHEDULE_IA_TILE_SETUP_CYCLES);
    if (c->per_channel) {
        uint32_t bytes=mode?c->lhs_bytes:c->rhs_bytes;
        uint32_t packed=mode?c->lhs_tile_packed:c->rhs_tile_packed;
        uint32_t depth=packed?16u:dsa_schedule_min(c->depth,16u);
        uint32_t lanes=dsa_schedule_min(sc,16u);
        uint32_t channels=c->cols;
        uint32_t passes=mode?1u:p->tiling.row_groups;
        uint32_t beat_bytes=dsa_schedule_bus_bytes(c);
        uint64_t groups=mode?p->tiling.row_groups:
            (uint64_t)p->tiling.row_groups*gempact_ceil_div(c->cols,16u);
        uint64_t first_beats=(uint64_t)lanes*gempact_ceil_div(depth*bytes,beat_bytes);
        uint64_t parameter_beats=2u*((uint64_t)(channels/16u)*(64u/beat_bytes)+
            gempact_ceil_div((channels%16u)*4u,beat_bytes))*passes;
        cost=dsa_schedule_add(cost,dsa_schedule_mul(
            dsa_schedule_add(first_beats,parameter_beats),c->read_beat_cycles));
        cost=dsa_schedule_add(cost,dsa_schedule_mul(groups,
            DSA_SCHEDULE_QUANT_GROUP_SETUP_CYCLES));
    }
    return cost;
}

/* Reuse decisions retain the current DMA request and output coalescing
 * estimates. Frame schedules also account for K-history residency and
 * partial row groups through the constant-size geometry model. */
static inline void dsa_schedule_memory_score_work(const dsa_schedule_config_t *c,
    const gempact_device_request_t *q, const gempact_dispatch_t *p,
    uint64_t a_words, uint64_t a_requests, uint64_t b_words,
    uint64_t b_requests,const uint32_t *footprints,
    uint64_t stream,uint64_t stationary,dsa_schedule_t *out)
{
    uint32_t mode=p->is_mode, r=p->tiling.ia_reuse, w=p->tiling.w_reuse;
    uint32_t sr=mode?c->cols:c->rows, sc=mode?c->rows:c->cols;
    uint32_t path=(p->ps_control&DSA_PS_CTRL_FRAME)!=0u;
    uint32_t beat_bytes=dsa_schedule_bus_bytes(c), words_per_beat=beat_bytes/4u;
    uint32_t max_bytes=dsa_schedule_dma_bytes(c);
    uint64_t weights=0u,read_cycles,write_cycles,parameter_beats,parameter_requests;
    uint64_t a_work,b_work,a_beats,b_beats,a_reads,b_reads,stream_cycles;
    uint32_t parameter_passes,resident=p->predicted_resident_frames;
    *out=(dsa_schedule_t){0};
    if (stream!=UINT64_MAX && stationary!=UINT64_MAX) {
        /* The bounded candidate search already computed these work counts. */
    } else if (!path) {
        stream=(uint64_t)sr*c->depth*p->tiling.col_groups;
        stationary=(uint64_t)sc*c->depth*p->tiling.row_groups;
    } else {
        uint32_t full=sr/(r*c->size),tail=sr%(r*c->size);
        uint32_t frame_limit=gempact_directory_frames(q,p->slice_rows);
        stream=stationary=0u;
        if (full) {
            uint64_t a=0u,b=0u,loads=0u;
            gempact_group_cost(q,mode,r,w,r*c->size,p->slice_rows,p->ia_slots,
                p->ps_control&DSA_PS_CTRL_RAW,frame_limit,&a,&b,&loads,&resident);
            stream=a*full;stationary=b*full;weights=loads*full;
        }
        if (tail) gempact_group_cost(q,mode,r,w,tail,
            dsa_schedule_min(p->slice_rows,tail),p->ia_slots,
            p->ps_control&DSA_PS_CTRL_RAW,frame_limit,&stream,&stationary,&weights,&resident);
        if (c->depth<=c->size && sc<=c->size) stationary=(uint64_t)sc*c->depth;
    }
    a_work=mode?stationary:stream;b_work=mode?stream:stationary;
    parameter_passes=mode ? (path?gempact_ceil_div(c->rows,c->size):1u):
        gempact_ceil_div(c->rows,p->slice_rows);
    parameter_beats=((uint64_t)(c->cols/16u)*(64u/beat_bytes)+
        gempact_ceil_div((c->cols%16u)*4u,beat_bytes))*parameter_passes*
        (c->has_bias+2u*c->per_channel);
    parameter_requests=((uint64_t)(c->cols/16u)*gempact_ceil_div(64u,max_bytes)+
        gempact_ceil_div((c->cols%16u)*4u,max_bytes))*parameter_passes*
        (c->has_bias+2u*c->per_channel);
    /* Scale complete physical beats so partial row groups never produce a
     * fractional AXI64 beat. Public word counts remain in 32-bit units. */
    a_beats=dsa_schedule_scale(a_words/words_per_beat,a_work,(uint64_t)c->rows*c->depth);
    b_beats=dsa_schedule_scale(b_words/words_per_beat,b_work,(uint64_t)c->cols*c->depth);
    a_reads=dsa_schedule_scale(a_requests,a_work,(uint64_t)c->rows*c->depth);
    b_reads=dsa_schedule_scale(b_requests,b_work,(uint64_t)c->cols*c->depth);
    if (c->spatial && c->im2col.input_bytes && c->im2col.cache_bytes) {
        // 图像由原始输入缓存按行读取，矩阵元素由前端生成。
        // 原图读取次数随输出通道分组增加，空间窗口超出缓存的代价在 image_cost 中计算。
        uint64_t image_bytes=c->im2col.input_bytes;
        uint32_t line_bytes=DSA_IM2COL_CACHE_LINE_BYTES;
        a_beats=dsa_schedule_scale((image_bytes+beat_bytes-1u)/beat_bytes,
            a_work,(uint64_t)c->rows*c->depth);
        a_reads=dsa_schedule_scale((image_bytes+c->lhs_address%line_bytes+line_bytes-1u)/line_bytes,
            a_work,(uint64_t)c->rows*c->depth);
    } else if (c->spatial && c->im2col.input_bytes) {
        // 缓存旁路按每次窗口访问读取原始数据字，读取数量随生成的矩阵规模增长。
        uint32_t word_bytes=16u,word_lanes=word_bytes/c->im2col.source_bytes;
        a_reads=a_work ? 1u+(a_work-1u)/word_lanes : 0u;
        a_beats=dsa_schedule_mul(a_reads,gempact_ceil_div(word_bytes,beat_bytes));
    }
    out->read_beats=dsa_schedule_add(dsa_schedule_add(a_beats,b_beats),parameter_beats);
    out->read_words=dsa_schedule_mul(out->read_beats,words_per_beat);
    out->read_requests=dsa_schedule_add(dsa_schedule_add(a_reads,b_reads),parameter_requests);
    /* A frame emits one output tile at a time; the long path can coalesce
     * adjacent output tiles according to the configured output banks. */
    out->write_requests=dsa_schedule_write_traffic(c,path?0u:mode,
        path?1u:r,path?1u:w,&out->write_beats);
    out->write_words=dsa_schedule_mul(out->write_beats,words_per_beat);
    out->compute_cycles=p->array_stream_cycles+p->weight_shift_rows+3u*p->frame_count;
    read_cycles=dsa_schedule_add(dsa_schedule_mul(out->read_beats,c->read_beat_cycles),
        dsa_schedule_mul(out->read_requests,c->read_request_cycles));
    write_cycles=dsa_schedule_add(dsa_schedule_mul(out->write_beats,c->write_beat_cycles),
        dsa_schedule_mul(out->write_requests,c->write_request_cycles));
    /* Stream refills and stationary installation share a serial dependency,
     * even when the other operand's DMA is hidden by array execution. */
    stream_cycles=dsa_schedule_add(
        dsa_schedule_mul(mode?b_beats:a_beats,c->read_beat_cycles),
        dsa_schedule_add(dsa_schedule_mul(mode?b_reads:a_reads,c->read_request_cycles),
                         p->weight_shift_rows));
    out->estimated_cycles=dsa_schedule_max(read_cycles,
        dsa_schedule_max(out->compute_cycles,stream_cycles));
    if (path) {
        /* A final-K frame completes its output writes before the following
         * command starts. Length-dependent service is separate from setup. */
        out->estimated_cycles=dsa_schedule_add(out->estimated_cycles,write_cycles);
    } else {
        /* 输出在最后一个归约分块完成后产生。写回只能与该分块的工作重叠，
         * 超出可重叠时间的总线服务会延长执行时间。 */
        uint32_t reduction_tiles=gempact_ceil_div(c->depth,c->size);
        uint64_t overlap_cycles=out->estimated_cycles/reduction_tiles;
        if (write_cycles>overlap_cycles)
            out->estimated_cycles=dsa_schedule_add(out->estimated_cycles,
                write_cycles-overlap_cycles);
    }
    out->estimated_cycles=dsa_schedule_add(out->estimated_cycles,
        p->micro_commands*q->micro_setup_cycles);
    out->estimated_cycles=dsa_schedule_add(out->estimated_cycles,
        dsa_schedule_loader_cost(c,p));
    out->estimated_cycles=dsa_schedule_add(out->estimated_cycles,
        dsa_schedule_image_cost(c,q,p,footprints,stream,stationary));
    out->tiling=p->tiling;out->dataflow_mode=mode;
    out->ps_payload_bytes=p->payload_bound_bytes;
    out->ps_control=p->ps_control;out->ia_bank_count=q->ia_bank_count;
    out->ia_cache_bytes=q->ia_bytes;out->ps_pool_bytes=q->pool_bytes;
    out->memory_policy_valid=1u;out->frame_rows=p->slice_rows;
    out->predicted_resident_frames=p->predicted_resident_frames;
}

static inline void dsa_schedule_memory_score(const dsa_schedule_config_t *c,
    const gempact_device_request_t *q,const gempact_dispatch_t *p,
    uint64_t a_words,uint64_t a_requests,uint64_t b_words,
    uint64_t b_requests,dsa_schedule_t *out)
{
    uint32_t footprints[65];
    dsa_schedule_window_footprints(c,footprints);
    dsa_schedule_memory_score_work(c,q,p,a_words,a_requests,b_words,b_requests,
        footprints,UINT64_MAX,UINT64_MAX,out);
}

typedef struct {
    const dsa_schedule_config_t *configuration;
    dsa_schedule_t *best;
    uint64_t a_words,a_requests,b_words,b_requests;
    uint32_t footprints[65];
    int found;
} dsa_schedule_search_t;

static void dsa_schedule_visit_candidate(const gempact_device_request_t *q,
    const gempact_dispatch_t *p,uint64_t stream,uint64_t stationary,void *context)
{
    dsa_schedule_search_t *search=(dsa_schedule_search_t *)context;
    dsa_schedule_t candidate;
    dsa_schedule_memory_score_work(search->configuration,q,p,
        search->a_words,search->a_requests,search->b_words,search->b_requests,
        search->footprints,stream,stationary,&candidate);
    if (!search->found || dsa_schedule_better(&candidate,search->best)) {
        *search->best=candidate;search->found=1;
    }
}

static inline int dsa_schedule_memory_plan(const dsa_schedule_config_t *c,
                                            dsa_schedule_t *out)
{
    gempact_device_request_t request={0};
    gempact_shared_memory_t memory={0};
    dsa_schedule_search_t search={0};
    uint32_t candidates=0u,banks=0u;
    if (!c || !out || c->size!=16u || !c->rows || !c->cols || !c->depth ||
        c->flow>DSA_SCHEDULE_AUTO || !c->ps_frames || c->ps_frames>64u ||
        c->lhs_bytes<1u || c->lhs_bytes>2u || c->rhs_bytes!=1u ||
        c->output_bytes<1u || c->output_bytes>2u ||
        c->per_channel>1u || c->has_bias>1u || c->lhs_tile_packed>1u ||
        c->rhs_tile_packed>1u || (c->spatial && c->lhs_tile_packed) ||
        (c->ps_literal_bytes && c->ps_literal_bytes!=32u &&
         c->ps_literal_bytes!=48u && c->ps_literal_bytes!=64u) ||
        !c->read_beat_cycles || !c->write_beat_cycles ||
        (c->axi_data_bits && c->axi_data_bits!=32u && c->axi_data_bits!=64u) ||
        (c->dma_max_bytes && (c->dma_max_bytes<dsa_schedule_bus_bytes(c) ||
         c->dma_max_bytes>256u*dsa_schedule_bus_bytes(c) ||
         (c->dma_max_bytes&(c->dma_max_bytes-1u)))) ||
        (c->flow==DSA_SCHEDULE_IS && !c->allow_is)) return 0;
    request.rows=c->rows;request.reduction=c->depth;request.cols=c->cols;
    request.size=c->size;request.frames=c->ps_frames;
    request.ia_bytes=c->ia_cache_bytes;request.pool_bytes=c->ps_pool_bytes;
    request.req_r=c->requested_r;request.req_w=c->requested_w;
    request.mode=c->flow;request.is_supported=c->allow_is;
    request.per_channel=c->per_channel;request.lhs_element_bytes=c->lhs_bytes;
    request.compact_mode_mask=(c->ps_caps&DSA_PS_CAP_IA_COMPACT)?c->compact_mode_mask:0u;
    request.frame_capable=(c->ps_caps&DSA_PS_CAP_FRAME_SCHEDULE)!=0u;
    request.adaptive=request.frame_capable && !c->force_raw && !(c->ps_caps&DSA_PS_CAP_RAW_ONLY);
    request.estimated_record_bytes=c->source_s8?DSA_PLANNER_RECORD_BYTES:64u;
    request.literal_record_bytes=request.adaptive?
        gempact_literal_record_bytes(c->depth,c->source_s8,c->lhs_offset,c->rhs_offset):64u;
    if (request.adaptive && (c->ps_caps&DSA_PS_CAP_LITERAL_BOUND) && c->ps_literal_bytes)
        request.literal_record_bytes=c->ps_literal_bytes;
    request.micro_setup_cycles=DSA_PLANNER_MICRO_CYCLES;
    request.directory_rows=c->ps_directory_rows;
    if (c->im2col.input_bytes && !gempact_set_im2col_geometry(&request,&c->im2col)) return 0;
    if (c->ps_caps&DSA_PS_CAP_SHARED) {
        memory.total_bytes=c->shared_total_bytes;memory.bank_bytes=c->shared_bank_bytes;
        memory.ia_bank_mask=c->shared_ia_bank_mask;memory.directory_rows=c->ps_directory_rows;
        if (!gempact_shared_valid(&memory)) return 0;
        banks=memory.total_bytes/memory.bank_bytes;
    }
    search.configuration=c;search.best=out;
    dsa_schedule_window_footprints(c,search.footprints);
    dsa_schedule_operand(c,c->rows,c->lhs_bytes,c->lhs_stride,c->lhs_address,
        !c->spatial,c->lhs_tile_packed,&search.a_words,&search.a_requests);
    dsa_schedule_operand(c,c->cols,c->rhs_bytes,c->rhs_stride,c->rhs_address,
        1,c->rhs_tile_packed,&search.b_words,&search.b_requests);
    for (uint32_t ia=banks?1u:0u;ia<(banks?banks:1u);++ia) {
        if (banks && !(memory.ia_bank_mask&(1u<<ia))) continue;
        gempact_device_request_t q=request;
        gempact_dispatch_t plan;
        if (banks) {
            q.ia_bytes=ia*memory.bank_bytes;q.pool_bytes=memory.total_bytes-q.ia_bytes;
            q.ia_bank_count=ia;q.ps_bank_count=banks-ia;
        }
        if (c->output_bytes==2u && c->output_banks_s16 &&
            (!q.req_r || q.req_r>c->output_banks_s16)) q.req_r=c->output_banks_s16;
        if (gempact_plan_device_visit(&q,&plan,dsa_schedule_visit_candidate,&search))
            candidates+=plan.candidates_evaluated;
    }
    if (search.found) {
        out->candidates=candidates;
        /* Lossless row coding also applies when the selected window fits
         * RAW32 capacity. Both encodings have the same stream throughput. */
        if (request.adaptive && c->depth>c->size) {
            out->ps_control&=~DSA_PS_CTRL_RAW;
            if (c->ps_caps&DSA_PS_CAP_LITERAL_BOUND) {
                if (c->ps_literal_bytes==32u) out->ps_control|=DSA_PS_CTRL_BOUND_S16;
                if (c->ps_literal_bytes==48u) out->ps_control|=DSA_PS_CTRL_BOUND_S24;
            }
        }
    }
    return search.found;
}

static inline int dsa_schedule_plan(const dsa_schedule_config_t *c,
                                     dsa_schedule_t *out)
{
    if (out) *out=(dsa_schedule_t){0};
    if (c && (c->ps_caps>>24)==DSA_PS_CAP_VERSION && (c->ps_caps&DSA_PS_CAP_STORE))
        return dsa_schedule_memory_plan(c,out);
    return dsa_schedule_plan_legacy(c,out);
}
#endif
