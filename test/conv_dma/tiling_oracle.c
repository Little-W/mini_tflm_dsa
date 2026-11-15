/* SPDX-License-Identifier: Apache-2.0
 * The unmodified production host planner is the descriptor oracle for the
 * standalone DMA-architecture test. No MMIO or tensor computation occurs here.
 */
#include <stdint.h>
#include "gempact_tiling.h"

int conv_dma_plan(uint32_t positions, uint32_t channels, uint32_t size,
                  uint32_t requested_r, uint32_t requested_w,
                  int is_mode, int per_channel, uint32_t values[6])
{
    gempact_tiling_t t;
    if (!gempact_plan_capacity(positions, channels, size, 4, 16,
                              requested_r, requested_w, is_mode, per_channel,
                              0, &t, 0)) return 0;
    values[0] = t.ia_reuse;
    values[1] = t.w_reuse;
    values[2] = t.row_groups;
    values[3] = t.row_tail_tiles;
    values[4] = t.col_groups;
    values[5] = t.col_tail_tiles;
    return 1;
}
