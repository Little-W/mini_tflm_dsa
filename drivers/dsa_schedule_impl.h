/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_SCHEDULE_IMPL_H
#define DSA_SCHEDULE_IMPL_H

static void dsa_matrix_default_limits(dsa_matrix_limits_t *limits)
{
    limits->flags=DSA_ENABLE_IS_MODE ? DSA_MATRIX_CAP_IS_SUPPORTED:0u;
    limits->ia_cache_blocks=DSA_IA_CACHE_BLOCKS;
    limits->ps_frame_count=DSA_PS_FRAME_COUNT;
    limits->ps_storage_rows=DSA_PS_STORAGE_ROWS;
    limits->tile_size=DSA_TILE_SIZE;
    limits->output_banks_s8=0u;
    limits->output_banks_s16=0u;
    limits->axi_data_bits=DSA_SCHEDULE_AXI_DATA_BITS;
    limits->dma_max_bytes=256u*(limits->axi_data_bits/8u);
}

void dsa_matrix_query(dsa_matrix_limits_t *limits)
{
    uint32_t caps,banks,dma,bus;
    if (!limits) return;
    dsa_matrix_default_limits(limits);
    if (dsa_reg_read(NPU_REG_ID)!=0x4e505531u ||
        dsa_reg_read(NPU_REG_CONFIG_ABI)!=2u) return;
    caps=dsa_reg_read(NPU_REG_MATRIX_CAPS);
    if (!((caps>>8)&255u) || !((caps>>16)&255u)) return;
    limits->flags=caps&7u;
    limits->ia_cache_blocks=(caps>>8)&255u;
    limits->ps_frame_count=(caps>>16)&255u;
    if (caps>>24) limits->tile_size=caps>>24;
    limits->ps_storage_rows=dsa_reg_read(NPU_REG_MATRIX_PS_ROWS);
    banks=dsa_reg_read(NPU_REG_MATRIX_OUTPUT_BANKS);
    limits->output_banks_s8=banks&65535u;
    limits->output_banks_s16=banks>>16;
    bus=dsa_reg_read(NPU_REG_AXI_DATA_BITS);
    if (bus==32u || bus==64u) limits->axi_data_bits=bus;
    limits->dma_max_bytes=256u*(limits->axi_data_bits/8u);
    dma=dsa_reg_read(NPU_REG_DMA_MAX_BYTES);
    if (dma>=limits->axi_data_bits/8u && dma<=limits->dma_max_bytes &&
        !(dma&(dma-1u))) limits->dma_max_bytes=dma;
}

static void dsa_schedule_set_limits(dsa_schedule_config_t *c,
    const dsa_matrix_limits_t *limits)
{
    c->size=limits->tile_size;
    c->ia_blocks=limits->ia_cache_blocks;
    c->ps_frames=limits->ps_frame_count;
    c->ps_storage_rows=limits->ps_storage_rows;
    c->ps_pool_bytes=DSA_PS_POOL_BYTES;
    c->output_banks_s8=limits->output_banks_s8;
    c->output_banks_s16=limits->output_banks_s16;
    c->axi_data_bits=limits->axi_data_bits ? limits->axi_data_bits:DSA_SCHEDULE_AXI_DATA_BITS;
    c->dma_max_bytes=limits->dma_max_bytes ? limits->dma_max_bytes:256u*dsa_schedule_bus_bytes(c);
    c->allow_is=(limits->flags&DSA_MATRIX_CAP_IS_SUPPORTED)!=0u;
}

uint32_t dsa_matmul_plan(const dsa_matmul_config_t *config,
    const dsa_matrix_limits_t *hardware, dsa_schedule_t *schedule)
{
    dsa_schedule_config_t c;
    dsa_matrix_limits_t defaults;
    int mode16x8;
    if (!config || !schedule) return DSA_ERR_NULL_PTR;
    if (!hardware) {dsa_matrix_default_limits(&defaults);hardware=&defaults;}
    if (config->dataflow_mode>DSA_DATAFLOW_AUTO ||
        config->lhs_tile_packed>1u || config->rhs_tile_packed>1u ||
        (config->lhs_dtype!=DSA_DTYPE_S8 && config->lhs_dtype!=DSA_DTYPE_S16) ||
        config->rhs_dtype!=DSA_DTYPE_S8 || config->bias_dtype!=DSA_DTYPE_S32 ||
        (config->out_dtype!=DSA_DTYPE_S8 && config->out_dtype!=DSA_DTYPE_S16))
        return DSA_ERR_INVALID_DIM;
    if ((config->lhs_tile_packed && !(hardware->flags&DSA_MATRIX_CAP_LHS_TILE_PACKED)) ||
        (config->rhs_tile_packed && !(hardware->flags&DSA_MATRIX_CAP_RHS_TILE_PACKED)) ||
        (config->dataflow_mode==DSA_DATAFLOW_IS && !(hardware->flags&DSA_MATRIX_CAP_IS_SUPPORTED)))
        return DSA_ERR_UNSUPPORTED;
    mode16x8=config->lhs_dtype==DSA_DTYPE_S16 && config->out_dtype==DSA_DTYPE_S16;
    dsa_schedule_init(&c,config->K,config->N,config->M,DSA_TILE_SIZE,
                      hardware->ia_cache_blocks,hardware->ps_frame_count);
    dsa_schedule_set_limits(&c,hardware);
    c.flow=mode16x8 ? DSA_SCHEDULE_WS:(uint32_t)config->dataflow_mode;
    c.allow_is=c.allow_is && !mode16x8;
    c.requested_r=config->ia_reuse_num;c.requested_w=config->w_reuse_num;
    c.lhs_bytes=config->lhs_dtype==DSA_DTYPE_S16 ? 2u:1u;
    c.output_bytes=config->out_dtype==DSA_DTYPE_S16 ? 2u:1u;
    c.lhs_stride=config->lhs_row_stride;c.rhs_stride=config->rhs_row_stride;
    c.output_stride=config->dst_row_stride;
    c.lhs_address=(uint32_t)(uintptr_t)config->lhs_ptr;
    c.rhs_address=(uint32_t)(uintptr_t)config->rhs_ptr;
    c.output_address=(uint32_t)(uintptr_t)config->dst_ptr;
    c.per_channel=config->quant_mode==DSA_QUANT_PER_CHANNEL;
    c.has_bias=config->bias_ptr!=0;
    c.lhs_tile_packed=config->lhs_tile_packed;c.rhs_tile_packed=config->rhs_tile_packed;
    if ((c.output_bytes==2u && !mode16x8) ||
        (c.lhs_tile_packed && ((c.lhs_address&3u) ||
         !dsa_matrix_packed_bytes(c.rows,c.depth,c.lhs_bytes))) ||
        (c.rhs_tile_packed && ((c.rhs_address&3u) ||
         !dsa_matrix_packed_bytes(c.cols,c.depth,c.rhs_bytes)))) return DSA_ERR_INVALID_DIM;
#if DSA_PCR_ENGINE
    /* The panel engine has independent group and partial-sum capacities. */
    {
        int found=0;
        dsa_schedule_t best={0};
        for (uint32_t flow=0;flow<2u;++flow) {
            dsa_schedule_t p={0};
            if ((c.flow!=DSA_SCHEDULE_AUTO && c.flow!=flow) || (flow && !c.allow_is)) continue;
            if (!gempact_plan_panel(c.rows,c.cols,DSA_PANEL_MAX_R,DSA_PANEL_MAX_W,
                DSA_PS_POOL_BYTES,c.requested_r,c.requested_w,flow,
                DSA_PS_FORCE_RAW,&p.tiling,&p.ps_payload_bytes)) continue;
            p.dataflow_mode=flow;
            p.read_beats=((uint64_t)c.rows*c.depth*p.tiling.col_groups+
                          (uint64_t)c.cols*c.depth*p.tiling.row_groups+dsa_schedule_bus_bytes(&c)-1u)/
                          dsa_schedule_bus_bytes(&c);
            p.read_words=p.read_beats*(dsa_schedule_bus_bytes(&c)/4u);
            p.estimated_cycles=p.read_beats*c.read_beat_cycles;
            if (!found || dsa_schedule_better(&p,&best)) {best=p;found=1;}
        }
        if (!found) return DSA_ERR_INVALID_DIM;
        *schedule=best;
        return DSA_SUCCESS;
    }
#else
    return dsa_schedule_plan(&c,schedule) ? DSA_SUCCESS:DSA_ERR_INVALID_DIM;
#endif
}

static uint32_t dsa_conv_plan(const dsa_conv_s8_config_t *config,
    const dsa_matrix_limits_t *hardware, uint32_t allow_is,
    dsa_schedule_t *schedule)
{
    dsa_schedule_config_t c;
    dsa_matrix_limits_t defaults;
    uint32_t depth=config->kernel_h*config->kernel_w*config->group_c;
    if (!hardware) {dsa_matrix_default_limits(&defaults);hardware=&defaults;}
    if (config->rhs_tile_packed && !(hardware->flags&DSA_MATRIX_CAP_RHS_TILE_PACKED))
        return DSA_ERR_UNSUPPORTED;
    dsa_schedule_init(&c,config->output_h*config->output_w,depth,
        config->output_channels,DSA_TILE_SIZE,hardware->ia_cache_blocks,hardware->ps_frame_count);
    dsa_schedule_set_limits(&c,hardware);
    c.flow=config->dataflow_mode;c.allow_is=c.allow_is && allow_is;
    if (c.flow==DSA_SCHEDULE_IS && !c.allow_is) return DSA_ERR_UNSUPPORTED;
    c.requested_r=config->ia_reuse_num;c.requested_w=config->w_reuse_num;
    c.lhs_bytes=2u;c.lhs_stride=gempact_ceil_div(depth,DSA_TILE_SIZE)*DSA_TILE_SIZE*2u;
    c.rhs_stride=depth;c.output_stride=config->dst_row_stride;
    c.lhs_address=config->input_base;c.rhs_address=config->filter_base;
    c.output_address=config->output_base;
    c.per_channel=1u;c.has_bias=config->bias_base!=0u;c.spatial=1u;
    c.rhs_tile_packed=config->rhs_tile_packed;
    return dsa_schedule_plan(&c,schedule) ? DSA_SUCCESS:DSA_ERR_INVALID_DIM;
}

#endif
