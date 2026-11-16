/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_MATRIX_H
#define DSA_MATRIX_H

#include <stdint.h>
#include <stddef.h>
#include "dsa_schedule.h"

#define NPU_REG_MATRIX_CAPS 0x0e4u
#define NPU_REG_MATRIX_PS_ROWS 0x0e8u
#define NPU_REG_MATRIX_OUTPUT_BANKS 0x0ecu
#define NPU_CTRL_LHS_TILE_PACKED (1u << 9)
#define NPU_CTRL_RHS_TILE_PACKED (1u << 10)
#define DSA_MATRIX_CAP_LHS_TILE_PACKED (1u << 0)
#define DSA_MATRIX_CAP_RHS_TILE_PACKED (1u << 1)
#define DSA_MATRIX_CAP_IS_SUPPORTED (1u << 2)

#ifndef DSA_ENABLE_IS_MODE
#define DSA_ENABLE_IS_MODE 1
#endif

#ifndef DSA_NN_PACKED_WEIGHTS
#define DSA_NN_PACKED_WEIGHTS 1
#endif

typedef struct {
    uint32_t flags, ia_cache_blocks, ps_frame_count, ps_storage_rows, tile_size;
    uint32_t output_banks_s8, output_banks_s16;
} dsa_matrix_limits_t;

#ifdef __cplusplus
extern "C" {
#endif

/* A zero capability register selects the platform's compile-time limits. */
void dsa_matrix_query(dsa_matrix_limits_t *limits);

/* Each physical matrix is [ceil(rows/16),ceil(depth/16),16,16].
 * The last index is reduction depth. Every padded element is zero.
 * The byte count is zero for an unsupported width or a 32-bit overflow. */
static inline uint32_t dsa_matrix_packed_bytes(uint32_t rows,
    uint32_t depth, uint32_t element_bytes)
{
    uint64_t bytes;
    if (!rows || !depth || (element_bytes!=1u && element_bytes!=2u)) return 0u;
    bytes=(uint64_t)gempact_ceil_div(rows,16u)*gempact_ceil_div(depth,16u);
    if (bytes>UINT32_MAX/(256u*element_bytes)) return 0u;
    return (uint32_t)bytes*256u*element_bytes;
}

/* The source is a strided row-major matrix. Source and destination storage
 * must be disjoint; element copies also support unaligned 16-bit sources. */
static inline int dsa_matrix_pack(void *destination, uint32_t destination_bytes,
    const void *source, uint32_t rows, uint32_t depth,
    uint32_t source_stride, uint32_t element_bytes)
{
    uint32_t bytes=dsa_matrix_packed_bytes(rows,depth,element_bytes);
    uint64_t span=(uint64_t)(rows ? rows-1u:0u)*source_stride+(uint64_t)depth*element_bytes;
    uintptr_t dst=(uintptr_t)destination,src=(uintptr_t)source;
    uint8_t *out=(uint8_t *)destination;
    const uint8_t *in=(const uint8_t *)source;
    uint32_t kt=gempact_ceil_div(depth,16u),rt=gempact_ceil_div(rows,16u);
    if (!bytes || !out || !in || destination_bytes<bytes ||
        (uint64_t)source_stride<(uint64_t)depth*element_bytes ||
        span>UINTPTR_MAX-src || bytes>UINTPTR_MAX-dst ||
        (dst<src+span && src<dst+bytes)) return 0;
    for (uint32_t row_tile=0;row_tile<rt;++row_tile)
        for (uint32_t depth_tile=0;depth_tile<kt;++depth_tile)
            for (uint32_t row=0;row<16u;++row)
                for (uint32_t k=0;k<16u;++k) {
                    uint32_t r=row_tile*16u+row,d=depth_tile*16u+k;
                    for (uint32_t b=0;b<element_bytes;++b)
                        *out++=(r<rows && d<depth) ?
                            in[(size_t)r*source_stride+(size_t)d*element_bytes+b]:0u;
                }
    return 1;
}

#ifdef __cplusplus
}
#endif
#endif
