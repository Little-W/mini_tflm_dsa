/* SPDX-License-Identifier: Apache-2.0 */
#ifndef GEMMINI_HOST_TRACE_XCUSTOM_H
#define GEMMINI_HOST_TRACE_XCUSTOM_H

#include <stdint.h>

void gemmini_trace_instruction(unsigned custom, uint64_t rs1, uint64_t rs2,
                               unsigned funct);
void gemmini_trace_fence(void);
uint32_t gemmini_trace_result_instruction(unsigned custom, uint64_t rs1,
                                          unsigned funct);

/* The official scheduler supplies all operands and instruction functions. */
#define ROCC_INSTRUCTION_0_R_R(custom, rs1, rs2, funct) \
    gemmini_trace_instruction((custom), (uint64_t)(rs1), (uint64_t)(rs2), (funct));

/* Counter results cannot guide a trace generated without running hardware. */
#define ROCC_INSTRUCTION(custom, rd, rs1, rs2, funct) \
    (rd) = gemmini_trace_result_instruction((custom), (uint64_t)(rs1), (funct));

#endif
