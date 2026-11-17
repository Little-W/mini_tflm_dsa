/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_PS_BOUND_H
#define DSA_PS_BOUND_H

#include <stddef.h>
#include <stdint.h>

/* Bound every retained K16 prefix for all legal S8 input values. Weights
 * remain immutable after preparation. Input and weight offsets are added
 * to their stored signed bytes; bias is applied only in the final K tile.
 *
 * The corrected input interval contains zero. Each term therefore has a
 * nonpositive minimum and a nonnegative maximum, so the final retained
 * prefix encloses every earlier prefix. Positive and negative weight sums
 * give its exact interval without reading activation data.
 *
 * Return 32, 48 or 64 bytes per complete 16-lane INT32 row. Zero selects the
 * ordinary capacity estimate when no intermediate PS is needed or the
 * geometry is unsupported. Packed storage is [ceil(N/16),ceil(K/16),16,16];
 * row_stride applies only to ordinary storage. Padded rows and K lanes are
 * excluded. The function uses constant temporary storage. */
static inline uint32_t dsa_ps_bound_s8(const void *weights,
    uint32_t channels, uint32_t depth, uint32_t row_stride,
    uint32_t tile_packed, int32_t input_offset, int32_t weight_offset)
{
    uint32_t prefix, depth_tiles, result=32u;
    uint64_t span;
    int32_t input_minimum, input_maximum;
    const int8_t *source=(const int8_t *)weights;
    if (!source || !channels || channels>65535u || !depth || depth>65535u ||
        tile_packed>1u || (!tile_packed && row_stride<depth) ||
        input_offset < -127 || input_offset > 128 ||
        weight_offset < -127 || weight_offset > 128) return 0u;
    prefix=(depth-1u)&~15u;
    if (!prefix) return 0u;
    depth_tiles=(depth+15u)/16u;
    span=tile_packed ? (uint64_t)((channels+15u)/16u)*depth_tiles*256u :
        (uint64_t)(channels-1u)*row_stride+depth;
    if (span>UINTPTR_MAX-(uintptr_t)weights) return 0u;
    input_minimum=-128+input_offset;
    input_maximum=127+input_offset;
    for (uint32_t channel=0u;channel<channels;++channel) {
        int32_t positive=0,negative=0;
        const int8_t *row=source+(tile_packed ?
            (size_t)(channel/16u)*depth_tiles*256u+(channel%16u)*16u :
            (size_t)channel*row_stride);
        for (uint32_t k=0u;k<prefix;k+=16u) {
            const int8_t *fragment=row+(tile_packed ? (size_t)(k/16u)*256u:k);
            for (uint32_t lane=0u;lane<16u;++lane) {
                int32_t weight=(int32_t)fragment[lane]+weight_offset;
                if (weight>=0) positive+=weight;
                else negative+=weight;
            }
        }
        const int64_t minimum=(int64_t)input_minimum*positive+(int64_t)input_maximum*negative;
        const int64_t maximum=(int64_t)input_maximum*positive+(int64_t)input_minimum*negative;
        if (minimum < -8388608 || maximum > 8388607) return 64u;
        if (minimum < -32768 || maximum > 32767) result=48u;
    }
    return result;
}

#endif
