/* SPDX-License-Identifier: Apache-2.0 */
#ifndef GEMMINI_MODEL_MMIO_H
#define GEMMINI_MODEL_MMIO_H

#include <stdint.h>

#ifndef GEMMINI_MMIO_BASE
#define GEMMINI_MMIO_BASE 0x50000000u
#endif

#ifdef GEMMINI_HOST_COMMANDS
void gemmini_host_command(unsigned funct, uint64_t rs1, uint64_t rs2);
void gemmini_host_fence(void);
#define gemmini_mmio_command gemmini_host_command
#define gemmini_mmio_fence gemmini_host_fence
#else
static inline void gemmini_mmio_command(unsigned funct, uint64_t rs1,
                                        uint64_t rs2) {
  volatile uint32_t *const registers = (volatile uint32_t *)GEMMINI_MMIO_BASE;
  static uint32_t previous[4];
  static unsigned initialized;
  const uint32_t values[4] = {(uint32_t)rs1, (uint32_t)(rs1 >> 32),
                              (uint32_t)rs2, (uint32_t)(rs2 >> 32)};
  for (unsigned i = 0; i < 4; ++i) {
    if (!initialized || previous[i] != values[i]) {
      registers[i + 1] = values[i];
      previous[i] = values[i];
    }
  }
  initialized = 1;
  __asm__ volatile("" ::: "memory");
  /* The submit write completes when the RoCC command is accepted. */
  registers[5] = funct;
}

static inline void gemmini_mmio_fence(void) {
  volatile uint32_t *const registers = (volatile uint32_t *)GEMMINI_MMIO_BASE;
  /* The bridge completes this read after all accelerator AXI traffic. */
  (void)registers[6];
  __asm__ volatile("" ::: "memory");
}
#endif

#define ROCC_INSTRUCTION_0_R_R(custom, rs1, rs2, funct) \
  gemmini_mmio_command((funct), (uint64_t)(rs1), (uint64_t)(rs2));

#define ROCC_INSTRUCTION(custom, rd, rs1, rs2, funct) \
  do { gemmini_mmio_command((funct), (uint64_t)(rs1), (uint64_t)(rs2)); \
       gemmini_mmio_fence(); (rd) = 0; } while (0);

#endif
