/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_SCHEDULE_IMPL_H
#define DSA_SCHEDULE_IMPL_H

static uint32_t dsa_ps_runtime_force_raw=DSA_PS_FORCE_RAW!=0;
static uint32_t dsa_planning_cycles, dsa_planning_cycles_total;

void dsa_set_ps_force_raw(uint32_t enabled)
{
    dsa_ps_runtime_force_raw=DSA_PS_FORCE_RAW || enabled!=0u;
}
uint32_t dsa_get_ps_force_raw(void) { return dsa_ps_runtime_force_raw; }
uint32_t dsa_last_planning_cycles(void) { return dsa_planning_cycles; }
uint32_t dsa_total_planning_cycles(void) { return dsa_planning_cycles_total; }

static uint32_t dsa_planner_clock(void)
{
#if defined(__riscv)
    uint32_t value;
    __asm__ volatile("rdcycle %0" : "=r"(value));
    return value;
#else
    return 0u;
#endif
}

typedef struct {
    dsa_schedule_config_t configuration;
    dsa_schedule_t schedule;
    uint32_t valid;
} dsa_schedule_cache_entry_t;
static dsa_schedule_cache_entry_t dsa_schedule_cache[DSA_PLANNER_CACHE_ENTRIES];
static uint32_t dsa_schedule_cache_next;

static int dsa_schedule_cached_plan(const dsa_schedule_config_t *configuration,
                                     dsa_schedule_t *schedule)
{
    uint32_t started=dsa_planner_clock();
    dsa_schedule_config_t key=*configuration;
    /* Operand transfer padding depends on the physical beat residue for both
     * row-major and packed layouts. Output grouping also uses the page offset. */
    key.lhs_address&=dsa_schedule_bus_bytes(&key)-1u;
    key.rhs_address&=dsa_schedule_bus_bytes(&key)-1u;
    key.output_address&=4095u;
    for (uint32_t i=0u;i<DSA_PLANNER_CACHE_ENTRIES;++i) {
        const dsa_schedule_cache_entry_t *entry=&dsa_schedule_cache[i];
        const unsigned char *a=(const unsigned char *)&key;
        const unsigned char *b=(const unsigned char *)&entry->configuration;
        uint32_t equal=entry->valid;
        for (uint32_t j=0u;equal && j<sizeof(*configuration);++j) equal=a[j]==b[j];
        if (equal) {
            *schedule=entry->schedule;
            dsa_planning_cycles=dsa_planner_clock()-started;
            dsa_planning_cycles_total+=dsa_planning_cycles;
            return 1;
        }
    }
    int result=dsa_schedule_plan(configuration,schedule);
    if (result) {
        dsa_schedule_cache_entry_t *entry=&dsa_schedule_cache[dsa_schedule_cache_next];
        entry->configuration=key;entry->schedule=*schedule;entry->valid=1u;
        if (++dsa_schedule_cache_next==DSA_PLANNER_CACHE_ENTRIES) dsa_schedule_cache_next=0u;
    }
    dsa_planning_cycles=dsa_planner_clock()-started;
    dsa_planning_cycles_total+=dsa_planning_cycles;
    return result;
}

static void dsa_matrix_default_limits(dsa_matrix_limits_t *limits)
{
    *limits=(dsa_matrix_limits_t){0};
    limits->flags=DSA_ENABLE_IS_MODE ? DSA_MATRIX_CAP_IS_SUPPORTED:0u;
    limits->ia_cache_blocks=DSA_IA_CACHE_BLOCKS;
    limits->ps_frame_count=DSA_PS_FRAME_COUNT;
    limits->ps_storage_rows=DSA_PS_STORAGE_ROWS;
    limits->tile_size=DSA_TILE_SIZE;
    limits->output_banks_s8=0u;
    limits->output_banks_s16=0u;
    limits->axi_data_bits=DSA_SCHEDULE_AXI_DATA_BITS;
    limits->dma_max_bytes=256u*(limits->axi_data_bits/8u);
    limits->ps_pool_bytes=DSA_PS_POOL_BYTES;
    limits->ia_cache_bytes=DSA_IA_CACHE_BLOCKS*DSA_TILE_SIZE*DSA_TILE_SIZE*2u;
#if DSA_PS_COMPRESS
    limits->ps_caps=(DSA_PS_CAP_VERSION<<24)|(DSA_PS_FRAME_COUNT<<16)|
        DSA_PS_CAP_STORE|DSA_PS_CAP_FRAME_SCHEDULE|DSA_PS_CAP_IA_COMPACT;
#endif
}

void dsa_matrix_query(dsa_matrix_limits_t *limits)
{
    uint32_t caps,banks,dma,bus,ps_caps;
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
    ps_caps=dsa_reg_read(NPU_REG_PS_CAPS);
    if ((ps_caps>>24)!=DSA_PS_CAP_VERSION || !(ps_caps&DSA_PS_CAP_STORE)) {
        limits->ps_caps=0u;
        return;
    }
    limits->ps_caps=ps_caps;
    if ((ps_caps>>16)&255u) limits->ps_frame_count=(ps_caps>>16)&255u;
    limits->ps_pool_bytes=dsa_reg_read(NPU_REG_PS_POOL_BYTES);
    limits->ia_cache_bytes=dsa_reg_read(NPU_REG_IA_CACHE_BYTES);
    limits->ps_directory_rows=dsa_reg_read(NPU_REG_PS_DIRECTORY_ROWS);
    if (ps_caps&DSA_PS_CAP_SHARED) {
        limits->shared_total_bytes=dsa_reg_read(NPU_REG_SHARED_TOTAL_BYTES);
        limits->shared_bank_bytes=dsa_reg_read(NPU_REG_SHARED_BANK_BYTES);
        limits->shared_ia_bank_mask=dsa_reg_read(NPU_REG_IA_BANK_MASK);
    }
}

static void dsa_schedule_set_limits(dsa_schedule_config_t *c,
    const dsa_matrix_limits_t *limits)
{
    c->size=limits->tile_size;
    c->ia_blocks=limits->ia_cache_blocks;
    c->ps_frames=limits->ps_frame_count;
    c->ps_storage_rows=limits->ps_storage_rows;
    c->ps_pool_bytes=limits->ps_pool_bytes;
    c->ps_caps=limits->ps_caps;c->ia_cache_bytes=limits->ia_cache_bytes;
    c->shared_total_bytes=limits->shared_total_bytes;c->shared_bank_bytes=limits->shared_bank_bytes;
    c->shared_ia_bank_mask=limits->shared_ia_bank_mask;c->ps_directory_rows=limits->ps_directory_rows;
    c->force_raw=dsa_ps_runtime_force_raw;
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
    c.source_s8=config->lhs_dtype==DSA_DTYPE_S8;
    c.lhs_offset=config->lhs_offset;c.rhs_offset=config->rhs_offset;
    c.compact_mode_mask=(c.source_s8 && config->lhs_offset>=-127 && config->lhs_offset<=128 ? 1u:0u)|
        (config->rhs_offset>=-127 && config->rhs_offset<=128 ? 2u:0u);
    if ((c.output_bytes==2u && !mode16x8) ||
        (c.lhs_tile_packed && ((c.lhs_address&3u) ||
         !dsa_matrix_packed_bytes(c.rows,c.depth,c.lhs_bytes))) ||
        (c.rhs_tile_packed && ((c.rhs_address&3u) ||
         !dsa_matrix_packed_bytes(c.cols,c.depth,c.rhs_bytes)))) return DSA_ERR_INVALID_DIM;
    return dsa_schedule_cached_plan(&c,schedule) ? DSA_SUCCESS:DSA_ERR_INVALID_DIM;
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
    c.source_s8=1u;c.lhs_offset=config->input_offset;c.rhs_offset=0;
    c.compact_mode_mask=(config->input_offset>=-127 && config->input_offset<=128 ? 1u:0u)|2u;
    c.im2col.input_bytes=config->input_h*config->input_w*config->input_c;
    c.im2col.input_channels=config->input_c;c.im2col.group_channels=config->group_c;
    c.im2col.kernel_h=config->kernel_h;c.im2col.kernel_w=config->kernel_w;
    c.im2col.stride_w=config->stride_w;c.im2col.source_bytes=1u;
    c.im2col.cache_bytes=config->bypass_cache?0u:DSA_IM2COL_CACHE_BYTES;
    c.im2col_input_width=config->input_w;c.im2col_output_width=config->output_w;
    c.im2col_stride_h=config->stride_h;
    return dsa_schedule_cached_plan(&c,schedule) ? DSA_SUCCESS:DSA_ERR_INVALID_DIM;
}

#endif
