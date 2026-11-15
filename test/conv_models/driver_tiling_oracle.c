/* SPDX-License-Identifier: Apache-2.0
 * Uses the production planner unchanged. Input: rows cols requested_r requested_w.
 * Output: R W row_groups row_tail_tiles col_groups col_tail_tiles.
 */
#include <inttypes.h>
#include <stdio.h>
#include "gempact_tiling.h"

int main(void)
{
    uint32_t rows, cols, requested_r, requested_w;
    int count;
    while ((count = scanf("%" SCNu32 " %" SCNu32 " %" SCNu32 " %" SCNu32,
                          &rows, &cols, &requested_r, &requested_w)) == 4) {
        gempact_tiling_t tiling;
        if (!gempact_plan_capacity(rows, cols, 16, 4, 16, requested_r,
                                  requested_w, 0, 1, 0, &tiling, NULL)) {
            fprintf(stderr, "Planner rejected rows=%" PRIu32 " cols=%" PRIu32 "\n", rows, cols);
            return 2;
        }
        printf("%" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 "\n",
               tiling.ia_reuse, tiling.w_reuse, tiling.row_groups,
               tiling.row_tail_tiles, tiling.col_groups, tiling.col_tail_tiles);
    }
    return count == EOF ? 0 : 3;
}
