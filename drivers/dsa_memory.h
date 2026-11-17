/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DSA_MEMORY_H
#define DSA_MEMORY_H
#include <stdint.h>

#define NPU_REG_SHARED_TOTAL_BYTES 0x100u
#define NPU_REG_SHARED_BANK_BYTES  0x104u
#define NPU_REG_IA_BANKS           0x108u
#define NPU_REG_IA_BANK_MASK       0x10cu
#define NPU_REG_PS_DIRECTORY_ROWS  0x110u
#define NPU_REG_PS_CONTROL         0x120u
#define NPU_REG_PS_CAPS            0x124u
#define NPU_REG_PS_COMMANDS        0x128u
#define NPU_REG_PS_PRESSURE        0x12cu
#define NPU_REG_PS_EARLY_FINISH    0x130u
#define NPU_REG_PS_POOL_BYTES      0x134u
#define NPU_REG_IA_CACHE_BYTES     0x138u

#define DSA_PS_CAP_VERSION        1u
#define DSA_PS_CAP_STORE          (1u << 0)
#define DSA_PS_CAP_FRAME_SCHEDULE (1u << 1)
#define DSA_PS_CAP_IA_COMPACT     (1u << 2)
#define DSA_PS_CAP_RAW_ONLY       (1u << 3)
#define DSA_PS_CAP_SHARED         (1u << 4)
#define DSA_PS_CAP_LITERAL_BOUND  (1u << 5)
#define DSA_PS_CTRL_RAW           (1u << 0)
#define DSA_PS_CTRL_FRAME         (1u << 1)
#define DSA_PS_CTRL_SLICE_16      (1u << 2)
#define DSA_PS_CTRL_SLICE_32      (2u << 2)
#define DSA_PS_CTRL_WHOLE_R       (3u << 2)
#define DSA_PS_CTRL_BOUND_MASK    (3u << 4)
#define DSA_PS_CTRL_BOUND_S16     (1u << 4)
#define DSA_PS_CTRL_BOUND_S24     (2u << 4)

#ifndef DSA_PCR_ENGINE
#define DSA_PCR_ENGINE 0
#endif
#ifndef DSA_PS_COMPRESS
#define DSA_PS_COMPRESS DSA_PCR_ENGINE
#endif
#ifndef DSA_PS_FORCE_RAW
#define DSA_PS_FORCE_RAW 0
#endif
#ifndef DSA_PLANNER_RECORD_BYTES
#define DSA_PLANNER_RECORD_BYTES 32u
#endif
#ifndef DSA_PLANNER_MICRO_CYCLES
#define DSA_PLANNER_MICRO_CYCLES 64u
#endif
#ifndef DSA_PLANNER_CACHE_ENTRIES
#define DSA_PLANNER_CACHE_ENTRIES 8u
#endif
#ifndef DSA_IM2COL_CACHE_BYTES
#define DSA_IM2COL_CACHE_BYTES 4096u
#endif

#ifdef __cplusplus
extern "C" {
#endif
/* Set the storage policy before preparing layer descriptors. Prepared
 * descriptors retain their policy and allocation until prepared again. */
void dsa_set_ps_force_raw(uint32_t enabled);
uint32_t dsa_get_ps_force_raw(void);
uint32_t dsa_last_planning_cycles(void);
uint32_t dsa_total_planning_cycles(void);
#ifdef __cplusplus
}
#endif
#endif
