/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "dsa_accel.h"

static uint32_t bus_bits, max_bytes;
static int present=1;

uint32_t dsa_mmio_read(uint32_t address)
{
    switch (address-DSA_MMIO_BASE) {
    case NPU_REG_ID: return present ? 0x4e505531u:0u;
    case NPU_REG_CONFIG_ABI: return 2u;
    case NPU_REG_MATRIX_CAPS: return (16u<<24)|(16u<<16)|(8u<<8)|7u;
    case NPU_REG_MATRIX_PS_ROWS: return 720u;
    case NPU_REG_MATRIX_OUTPUT_BANKS: return (4u<<16)|32u;
    case NPU_REG_AXI_DATA_BITS: return bus_bits;
    case NPU_REG_DMA_MAX_BYTES: return max_bytes;
    default: return 0u;
    }
}

void dsa_mmio_write(uint32_t address, uint32_t value)
{
    (void)address;(void)value;
    assert(0 && "capability queries and schedule planning are read-only");
}

int main(void)
{
    const uint32_t cases[][4]={
        {0,0,32,1024},{32,1024,32,1024},{64,2048,64,2048},
        {64,0,64,2048},{64,64,64,64},{64,4096,64,2048},
        {64,4,64,2048},{32,2048,32,1024},{128,0,32,1024}
    };
    for (unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);++i) {
        dsa_matrix_limits_t limits;
        dsa_matmul_config_t config;
        dsa_schedule_t plan;
        bus_bits=cases[i][0];max_bytes=cases[i][1];
        dsa_matrix_query(&limits);
        assert(limits.axi_data_bits==cases[i][2]);
        assert(limits.dma_max_bytes==cases[i][3]);
        assert(limits.ps_storage_rows==720u && limits.ia_cache_blocks==8u);
        dsa_matmul_config_init(&config);
        config.K=1;config.N=256;config.M=2;
        config.lhs_row_stride=config.rhs_row_stride=256;
        config.dst_row_stride=2;
        config.lhs_ptr=0x1000;config.rhs_ptr=0x2000;config.dst_ptr=0x3000;
        assert(dsa_matmul_plan(&config,&limits,&plan)==DSA_SUCCESS);
        assert(plan.read_words==plan.read_beats*(limits.axi_data_bits/32u));
        assert(plan.write_words==plan.write_beats*(limits.axi_data_bits/32u));
    }
    present=0;
    dsa_matrix_limits_t limits;
    dsa_matrix_query(&limits);
    assert(limits.axi_data_bits==32u && limits.dma_max_bytes==1024u);
    puts("BUS_CAPABILITIES_PASS cases=10");
    return 0;
}
