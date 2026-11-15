/* SPDX-License-Identifier: Apache-2.0 */
#include "riscv_nn_dsa.h"

#if DSA_NN_RUNTIME_CONTROL
static uint32_t dsa_nn_accelerators = DSA_NN_ACCEL_ALL;

void dsa_nn_set_accelerators(uint32_t mask)
{
    dsa_nn_accelerators = mask & DSA_NN_ACCEL_ALL;
}

uint32_t dsa_nn_get_accelerators(void)
{
    return dsa_nn_accelerators;
}
#endif
