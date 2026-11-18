/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include "dsa_accel.h"
#include "dsa_prepared.h"

static uint32_t registers[128], starts, active, hardware_raw_only, hardware_literal_bound;
static uint32_t hardware_axi_data_bits=32u,hardware_dma_max_bytes=1024u;
static uint32_t hardware_ps_available=1u;
static uint32_t hardware_bank_bytes=2048u,hardware_bank_count=7u;
static uint32_t checks;
void dsa_mmio_write(uint32_t address,uint32_t value)
{
    uint32_t offset=address-DSA_MMIO_BASE;
    assert(offset<sizeof(registers) && !(offset&3u));
    if (offset==NPU_REG_STATUS) {active=0u;return;}
    registers[offset/4u]=value;
    if (offset==NPU_REG_CTRL && (value&1u)) {++starts;active=1u;}
}
uint32_t dsa_mmio_read(uint32_t address)
{
    uint32_t offset=address-DSA_MMIO_BASE;
    assert(offset<sizeof(registers) && !(offset&3u));
    switch (offset) {
    case NPU_REG_ID: return 0x4e505531u;
    case NPU_REG_CONFIG_ABI: return 2u;
    case NPU_REG_STATUS: return active?5u:1u;
    case NPU_REG_WB_DATA: return 0u;
    case NPU_REG_MATRIX_CAPS: return (16u<<24)|(16u<<16)|(4u<<8)|7u;
    case NPU_REG_MATRIX_PS_ROWS: return 0u;
    case NPU_REG_MATRIX_OUTPUT_BANKS: return 8u|(8u<<16);
    case NPU_REG_AXI_DATA_BITS: return hardware_axi_data_bits;
    case NPU_REG_DMA_MAX_BYTES: return hardware_dma_max_bytes;
    case NPU_REG_CONV_CAPS: return (DSA_CONV_CAP_VERSION<<16)|7u;
    case NPU_REG_PS_CAPS: return hardware_ps_available ?
        (1u<<24)|(16u<<16)|23u|(hardware_raw_only?DSA_PS_CAP_RAW_ONLY:0u)|
        (hardware_literal_bound?DSA_PS_CAP_LITERAL_BOUND:0u):0u;
    case NPU_REG_PS_POOL_BYTES: return (hardware_bank_count-1u)*hardware_bank_bytes;
    case NPU_REG_IA_CACHE_BYTES: return hardware_bank_bytes;
    case NPU_REG_SHARED_TOTAL_BYTES: return hardware_bank_count*hardware_bank_bytes;
    case NPU_REG_SHARED_BANK_BYTES: return hardware_bank_bytes;
    case NPU_REG_IA_BANK_MASK: return hardware_bank_count>=8u?0x16u:0x6u;
    case NPU_REG_PS_DIRECTORY_ROWS: return 1024u;
    default: return registers[offset/4u];
    }
}

static void safe(const dsa_schedule_config_t *c,const dsa_schedule_t *p)
{
    uint32_t ia=p->ia_bank_count,ps=c->shared_total_bytes/c->shared_bank_bytes-ia;
    uint32_t compact=(c->compact_mode_mask>>p->dataflow_mode)&1u;
    uint32_t slots=ia*c->shared_bank_bytes/(compact?256u:512u);
    uint32_t literal=(p->ps_control&DSA_PS_CTRL_RAW)?64u:
        gempact_literal_record_bytes(c->depth,c->source_s8,c->lhs_offset,c->rhs_offset);
    if ((p->ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S16) literal=32u;
    if ((p->ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S24) literal=48u;
    uint32_t rows=p->frame_rows;
    assert(p->memory_policy_valid && (ia==1u || ia==2u || ia==4u));
    assert(p->ia_cache_bytes+p->ps_pool_bytes==c->shared_total_bytes);
    assert(p->read_words==p->read_beats*(c->axi_data_bits/32u));
    assert(p->write_words==p->write_beats*(c->axi_data_bits/32u));
    assert(p->tiling.ia_reuse<=slots/2u);
    assert(compact || ia>=2u);
    if (c->depth>16u) {
        uint32_t words=gempact_ceil_div(rows*(literal/16u),ps);
        assert(ps>=literal/16u && words<=c->shared_bank_bytes/16u);
        if (!(p->ps_control&DSA_PS_CTRL_FRAME)) {
            uint32_t stationary=p->dataflow_mode?c->rows:c->cols;
            uint32_t frames=dsa_schedule_min(p->tiling.w_reuse,gempact_ceil_div(stationary,16u));
            assert((uint64_t)words*frames<=c->shared_bank_bytes/16u);
        }
        assert(rows<=1024u);
    }
    if (c->force_raw || (c->ps_caps&DSA_PS_CAP_RAW_ONLY)) {
        assert(p->ps_control&DSA_PS_CTRL_RAW);
        assert(!(p->ps_control&DSA_PS_CTRL_BOUND_MASK));
    }
    else if ((c->ps_caps&DSA_PS_CAP_FRAME_SCHEDULE) && c->depth>c->size)
        assert(!(p->ps_control&DSA_PS_CTRL_RAW));
    ++checks;
}

static void planner_checks(void)
{
    const uint32_t shapes[][3]={{1,800,32},{37,67,83},{256,128,256},
        {49,27,32},{64,16,128},{4096,256,16},{17,1025,19},{1,16,128}};
    for (uint32_t i=0u;i<sizeof(shapes)/sizeof(shapes[0]);++i)
        for (uint32_t mode=0u;mode<3u;++mode)
            for (uint32_t raw=0u;raw<2u;++raw)
                for (uint32_t compact=0u;compact<4u;++compact) {
                    dsa_schedule_config_t c;
                    dsa_schedule_t p;
                    dsa_schedule_init(&c,shapes[i][0],shapes[i][1],shapes[i][2],16u,4u,16u);
                    c.ps_caps=(1u<<24)|(16u<<16)|23u;c.ps_pool_bytes=(hardware_bank_count-1u)*hardware_bank_bytes;
                    c.ia_cache_bytes=hardware_bank_bytes;c.shared_total_bytes=hardware_bank_count*hardware_bank_bytes;c.shared_bank_bytes=hardware_bank_bytes;
                    c.shared_ia_bank_mask=hardware_bank_count>=8u?0x16u:0x6u;c.ps_directory_rows=1024u;
                    c.flow=mode;c.force_raw=raw;c.compact_mode_mask=compact;c.source_s8=1u;
                    c.axi_data_bits=hardware_axi_data_bits;c.dma_max_bytes=hardware_dma_max_bytes;
                    assert(dsa_schedule_plan(&c,&p));safe(&c,&p);
                    if (mode<2u) assert(p.dataflow_mode==mode);
                    if (i==2u && mode==2u && compact==3u)
                        printf("POLICY axi=%u raw=%u ia=%u r=%u w=%u flow=%u ctrl=%u candidates=%u estimate=%llu\n",
                            c.axi_data_bits,raw,p.ia_bank_count,p.tiling.ia_reuse,p.tiling.w_reuse,p.dataflow_mode,
                            p.ps_control,p.candidates,(unsigned long long)p.estimated_cycles);
                }
}

static void literal_bound_checks(void)
{
    dsa_schedule_config_t c;
    dsa_schedule_t p;
    dsa_schedule_init(&c,1u,784u,64u,16u,4u,16u);
    c.ps_caps=(1u<<24)|(16u<<16)|23u;c.ps_pool_bytes=12288u;
    c.ia_cache_bytes=2048u;c.shared_total_bytes=14336u;c.shared_bank_bytes=2048u;
    c.shared_ia_bank_mask=0x16u;c.ps_directory_rows=1024u;
    c.source_s8=1u;c.compact_mode_mask=3u;c.lhs_offset=128;c.rhs_tile_packed=1u;
    const uint32_t sizes[]={0u,32u,48u,64u};
    for (uint32_t capability=0u;capability<2u;++capability)
        for (uint32_t i=0u;i<4u;++i)
            for (uint32_t raw=0u;raw<2u;++raw)
                for (uint32_t raw_only=0u;raw_only<2u;++raw_only) {
                    c.ps_caps=((1u<<24)|(16u<<16)|23u)|
                        (capability?DSA_PS_CAP_LITERAL_BOUND:0u)|
                        (raw_only?DSA_PS_CAP_RAW_ONLY:0u);
                    c.ps_literal_bytes=sizes[i];c.force_raw=raw;
                    assert(dsa_schedule_plan(&c,&p));safe(&c,&p);
                    uint32_t expected=0u;
                    if (capability && !raw && !raw_only) {
                        if(sizes[i]==32u)expected=DSA_PS_CTRL_BOUND_S16;
                        if(sizes[i]==48u)expected=DSA_PS_CTRL_BOUND_S24;
                    }
                    assert((p.ps_control&DSA_PS_CTRL_BOUND_MASK)==expected);
                }
    c.shared_ia_bank_mask=1u<<4;c.force_raw=0u;
    c.ps_caps=(1u<<24)|(16u<<16)|23u|DSA_PS_CAP_LITERAL_BOUND;
    c.ps_literal_bytes=48u;
    assert(dsa_schedule_plan(&c,&p));safe(&c,&p);assert(p.ia_bank_count==4u);
    c.ps_caps&=~DSA_PS_CAP_LITERAL_BOUND;
    assert(!dsa_schedule_plan(&c,&p));
    c.ps_caps|=DSA_PS_CAP_LITERAL_BOUND;c.force_raw=1u;
    assert(!dsa_schedule_plan(&c,&p));
    c.force_raw=0u;c.ps_caps|=DSA_PS_CAP_RAW_ONLY;
    assert(!dsa_schedule_plan(&c,&p));
    c.ps_caps&=~DSA_PS_CAP_RAW_ONLY;c.shared_ia_bank_mask=0x16u;c.ps_literal_bytes=16u;
    assert(!dsa_schedule_plan(&c,&p));
    checks+=4u;
}

static void prepared_checks(void)
{
    uint32_t initial_starts=starts;
    unsigned char *memory=mmap(0,1u<<20,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0);
    assert(memory!=MAP_FAILED && (uintptr_t)memory<=UINT32_MAX-(1u<<20));
    uint32_t base=(uint32_t)(uintptr_t)memory;
    int32_t *bias=(int32_t *)(memory+0x30000),*mult=(int32_t *)(memory+0x31000),*shift=(int32_t *)(memory+0x32000);
    for (uint32_t i=0u;i<256u;++i) {bias[i]=(int32_t)i-128;mult[i]=1073741824;shift[i]=-8;}
    dsa_prepared_matmul_s8_config_t c={0};
    c.filter_base=base+0x10000;c.bias_base=base+0x30000;c.multiplier_base=base+0x31000;c.shift_base=base+0x32000;
    c.rows=256u;c.depth=c.input_stride=c.filter_stride=128u;c.channels=c.output_stride=256u;
    c.per_channel=1u;c.dataflow_mode=2u;c.activation_min=-128;c.activation_max=127;
    c.rhs_tile_packed=1u;
    dsa_prepared_t compressed,raw;
    dsa_set_ps_force_raw(0u);
    assert(dsa_prepare_matmul_s8(&compressed,&c)==DSA_SUCCESS);
    assert(compressed.memory_policy_valid && compressed.ia_bank_count);
    assert(!(compressed.ps_control&DSA_PS_CTRL_RAW));
    assert(compressed.ctrl&NPU_CTRL_RHS_TILE_PACKED);
    dsa_set_ps_force_raw(1u);
    assert(dsa_prepare_matmul_s8(&raw,&c)==DSA_SUCCESS);
    assert(raw.ps_control&DSA_PS_CTRL_RAW);
    assert(dsa_prepared_execute(&raw,memory,memory+0x40000)==DSA_SUCCESS);
    assert(registers[NPU_REG_PS_CONTROL/4u]==raw.ps_control);
    assert(registers[NPU_REG_IA_BANKS/4u]==raw.ia_bank_count);
    assert(dsa_prepared_execute(&compressed,memory,memory+0x40000)==DSA_SUCCESS);
    assert(registers[NPU_REG_PS_CONTROL/4u]==compressed.ps_control);
    assert(registers[NPU_REG_IA_BANKS/4u]==compressed.ia_bank_count);
    assert(dsa_prepared_execute(&raw,memory,memory+16)==DSA_ERR_INVALID_DIM);
    dsa_set_ps_force_raw(0u);
    dsa_prepared_t repeated;
    assert(dsa_prepare_matmul_s8(&repeated,&c)==DSA_SUCCESS);
    assert(repeated.ps_control==compressed.ps_control && repeated.ia_bank_count==compressed.ia_bank_count);
    assert(memcmp(repeated.registers,compressed.registers,compressed.register_count*sizeof(compressed.registers[0]))==0);
    hardware_raw_only=1u;
    assert(dsa_prepare_matmul_s8(&repeated,&c)==DSA_SUCCESS);
    assert(repeated.ps_control&DSA_PS_CTRL_RAW);
    hardware_raw_only=0u;
    dsa_conv_s8_config_t conv={0};
    conv.filter_base=c.filter_base;conv.bias_base=c.bias_base;
    conv.multiplier_base=c.multiplier_base;conv.shift_base=c.shift_base;
    conv.input_h=conv.output_h=5u;conv.input_w=conv.output_w=7u;
    conv.input_c=conv.group_c=3u;conv.kernel_h=conv.kernel_w=3u;
    conv.stride_h=conv.stride_w=conv.dilation_h=conv.dilation_w=1u;
    conv.pad_top=conv.pad_left=1u;conv.output_channels=conv.dst_row_stride=32u;
    conv.input_offset=128;conv.activation_min=-128;conv.activation_max=127;conv.dataflow_mode=2u;
    assert(dsa_prepare_conv_s8(&repeated,&conv)==DSA_SUCCESS);
    assert(repeated.ctrl&NPU_CTRL_HW_CONV);
    assert(repeated.memory_policy_valid && repeated.ia_bank_count);
    assert(dsa_prepared_execute(&repeated,memory,memory+0x40000)==DSA_SUCCESS);
    assert(registers[NPU_REG_PS_CONTROL/4u]==repeated.ps_control);
    conv.input_base=base;conv.output_base=base+0x40000;
    assert(dsa_conv_s8_execute(&conv)==DSA_SUCCESS);
    assert(starts==initial_starts+4u);
    c.rows=1u;c.depth=c.input_stride=c.filter_stride=64u;
    c.channels=c.output_stride=10u;
    dsa_set_ps_force_raw(0u);
    assert(dsa_prepare_matmul_s8(&compressed,&c)==DSA_SUCCESS);
    assert(!(compressed.ps_control&DSA_PS_CTRL_RAW));
    dsa_set_ps_force_raw(1u);
    assert(dsa_prepare_matmul_s8(&raw,&c)==DSA_SUCCESS);
    assert(raw.ps_control&DSA_PS_CTRL_RAW);
    assert(dsa_prepared_execute(&compressed,memory,memory+0x40000)==DSA_SUCCESS);
    assert(!(registers[NPU_REG_PS_CONTROL/4u]&DSA_PS_CTRL_RAW));
    assert(dsa_prepared_execute(&raw,memory,memory+0x40000)==DSA_SUCCESS);
    assert(registers[NPU_REG_PS_CONTROL/4u]&DSA_PS_CTRL_RAW);
    hardware_raw_only=1u;dsa_set_ps_force_raw(0u);
    assert(dsa_prepare_matmul_s8(&repeated,&c)==DSA_SUCCESS);
    assert(repeated.ps_control&DSA_PS_CTRL_RAW);
    assert(dsa_prepared_execute(&repeated,memory,memory+0x40000)==DSA_SUCCESS);
    assert(registers[NPU_REG_PS_CONTROL/4u]&DSA_PS_CTRL_RAW);
    hardware_raw_only=0u;
    assert(starts==initial_starts+7u);
    c.depth=c.input_stride=c.filter_stride=784u;c.channels=c.output_stride=64u;
    c.input_offset=128;
    hardware_literal_bound=1u;dsa_set_ps_force_raw(0u);
    memset(memory+0x10000,0,0x10000);
    assert(dsa_prepare_matmul_s8(&compressed,&c)==DSA_SUCCESS);
    assert((compressed.ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S16);
    assert(mprotect(memory+0x10000,0x10000,PROT_NONE)==0);
    dsa_set_ps_force_raw(1u);
    assert(dsa_prepared_execute(&compressed,memory,memory+0x40000)==DSA_SUCCESS);
    assert(registers[NPU_REG_PS_CONTROL/4u]==compressed.ps_control);
    assert(dsa_prepare_matmul_s8(&raw,&c)==DSA_SUCCESS);
    assert((raw.ps_control&(DSA_PS_CTRL_RAW|DSA_PS_CTRL_BOUND_MASK))==DSA_PS_CTRL_RAW);
    dsa_set_ps_force_raw(0u);hardware_raw_only=1u;
    assert(dsa_prepare_matmul_s8(&raw,&c)==DSA_SUCCESS);
    assert((raw.ps_control&(DSA_PS_CTRL_RAW|DSA_PS_CTRL_BOUND_MASK))==DSA_PS_CTRL_RAW);
    hardware_raw_only=0u;hardware_literal_bound=0u;
    assert(dsa_prepare_matmul_s8(&repeated,&c)==DSA_SUCCESS);
    assert(!(repeated.ps_control&DSA_PS_CTRL_BOUND_MASK));
    assert(mprotect(memory+0x10000,0x10000,PROT_READ|PROT_WRITE)==0);
    hardware_literal_bound=1u;
    memset(memory+0x10000,1,0x10000);
    assert(dsa_prepare_matmul_s8(&repeated,&c)==DSA_SUCCESS);
    assert((repeated.ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S24);
    memset(memory+0x10000,127,0x10000);
    assert(dsa_prepare_matmul_s8(&repeated,&c)==DSA_SUCCESS);
    assert(!(repeated.ps_control&(DSA_PS_CTRL_RAW|DSA_PS_CTRL_BOUND_MASK)));
    memset(memory+0x10000,0,0x10000);
    assert(dsa_prepare_matmul_s8(&repeated,&c)==DSA_SUCCESS);
    assert(repeated.ps_control==compressed.ps_control && repeated.ia_bank_count==compressed.ia_bank_count);
    assert(starts==initial_starts+8u);
    assert(dsa_prepare_conv_s8(&repeated,&conv)==DSA_SUCCESS);
    assert(repeated.ctrl&NPU_CTRL_HW_CONV);
    assert((repeated.ps_control&DSA_PS_CTRL_BOUND_MASK)==DSA_PS_CTRL_BOUND_S16);
    assert(mprotect(memory+0x10000,0x10000,PROT_NONE)==0);
    assert(dsa_prepared_execute(&repeated,memory,memory+0x40000)==DSA_SUCCESS);
    assert(registers[NPU_REG_PS_CONTROL/4u]==repeated.ps_control);
    assert(mprotect(memory+0x10000,0x10000,PROT_READ|PROT_WRITE)==0);
    assert(starts==initial_starts+9u);
    hardware_literal_bound=0u;
    assert(munmap(memory,1u<<20)==0);
    checks+=57u;
}
int main(void)
{
    dsa_matrix_limits_t limits;
    for (uint32_t bits=32u;bits<=64u;bits*=2u) {
        hardware_axi_data_bits=bits;hardware_dma_max_bytes=256u*(bits/8u);
        for (uint32_t bytes=2048u;bytes<=8192u;bytes*=2u) {
            hardware_bank_bytes=bytes;hardware_bank_count=bytes==2048u?6u:bytes==4096u?7u:9u;
            dsa_matrix_query(&limits);
            assert(limits.shared_total_bytes==hardware_bank_count*bytes && limits.shared_bank_bytes==bytes && limits.shared_ia_bank_mask==(hardware_bank_count>=8u?0x16u:0x6u));
            assert(limits.axi_data_bits==bits && limits.dma_max_bytes==hardware_dma_max_bytes);
            planner_checks();prepared_checks();
        }
    }
    literal_bound_checks();
    hardware_ps_available=0u;hardware_dma_max_bytes=64u;
    dsa_matrix_query(&limits);
    assert(limits.ps_caps==0u && limits.axi_data_bits==64u && limits.dma_max_bytes==64u);
    checks+=3u;
    printf("MEMORY_POLICY_PASS checks=%u starts=%u\n",checks,starts);
    return 0;
}
