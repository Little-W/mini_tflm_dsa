/* SPDX-License-Identifier: Apache-2.0 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "include/gemmini.h"

static FILE *commands;

void gemmini_trace_instruction(unsigned custom, uint64_t rs1, uint64_t rs2,
                               unsigned funct) {
    if (custom != XCUSTOM_ACC || !commands) abort();
    fprintf(commands, "%u 0x%016" PRIx64 " 0x%016" PRIx64 "\n", funct, rs1, rs2);
}

void gemmini_trace_fence(void) {
    if (!commands) abort();
    fputs("FENCE\n", commands);
}

uint32_t gemmini_trace_result_instruction(unsigned custom, uint64_t rs1,
                                          unsigned funct) {
    (void)custom; (void)rs1; (void)funct;
    abort();
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--describe") == 0) {
        printf("{\"dim\":%u,\"bank_num\":%u,\"bank_rows\":%u,"
               "\"acc_rows\":%u,\"max_bytes\":%u}\n",
               DIM, BANK_NUM, BANK_ROWS, ACC_ROWS, MAX_BYTES);
        return 0;
    }
    if (argc != 5 && argc != 6) return 2;
    const uintptr_t input = strtoull(argv[1], NULL, 0);
    const uintptr_t output = strtoull(argv[2], NULL, 0);
    const unsigned columns = strtoul(argv[3], NULL, 0);
    const unsigned rows = argc == 6 ? strtoul(argv[5], NULL, 0) : 1;
    if (!columns || columns > MAX_BYTES || !rows || rows > DIM ||
            ((columns + DIM - 1) / DIM - 1) * DIM + rows > BANK_NUM * BANK_ROWS) return 2;
    commands = fopen(argv[4], "w");
    if (!commands) return 2;
    gemmini_flush(0);
    gemmini_fence();
    gemmini_config_ld(columns * sizeof(elem_t));
    gemmini_config_st(columns * sizeof(elem_t));
    gemmini_extended_mvin((const void *)input, 0, columns, rows);
    gemmini_fence();
    gemmini_extended_mvout((void *)output, 0, columns, rows);
    gemmini_fence();
    return fclose(commands) != 0;
}
