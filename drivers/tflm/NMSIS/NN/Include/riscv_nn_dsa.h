/* SPDX-License-Identifier: Apache-2.0 */
#ifndef RISCV_NN_DSA_H
#define RISCV_NN_DSA_H

#include <stdint.h>

/* Runtime selection applies to the s8 Conv, DW, pooling, FC, Add and Softmax paths.
 * Set the mask while the accelerator is idle, before invoking a layer.
 * Compile-time DSA_NN_*_ENABLE settings remain authoritative.
 */
#define DSA_NN_ACCEL_CONV (1u << 0)
#define DSA_NN_ACCEL_DW   (1u << 1)
#define DSA_NN_ACCEL_POOL (1u << 2)
#define DSA_NN_ACCEL_FC   (1u << 3)
#define DSA_NN_ACCEL_ADD  (1u << 4)
#define DSA_NN_ACCEL_SOFTMAX (1u << 5)
#define DSA_NN_ACCEL_ALL (DSA_NN_ACCEL_CONV | DSA_NN_ACCEL_DW | \
                          DSA_NN_ACCEL_POOL | DSA_NN_ACCEL_FC | DSA_NN_ACCEL_ADD | DSA_NN_ACCEL_SOFTMAX)

#ifndef DSA_NN_RUNTIME_CONTROL
#define DSA_NN_RUNTIME_CONTROL 0
#endif

#ifdef __cplusplus
extern "C" {
#endif

#if DSA_NN_RUNTIME_CONTROL
void dsa_nn_set_accelerators(uint32_t mask);
uint32_t dsa_nn_get_accelerators(void);
static inline int dsa_nn_accelerator_enabled(uint32_t accelerator)
{
    return (dsa_nn_get_accelerators() & accelerator) != 0u;
}
#else
static inline int dsa_nn_accelerator_enabled(uint32_t accelerator)
{
    (void)accelerator;
    return 1;
}
#endif

#ifdef __cplusplus
}
#endif
#endif
