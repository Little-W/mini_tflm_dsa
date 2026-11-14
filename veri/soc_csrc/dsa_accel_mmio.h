#ifndef DSA_ACCEL_MMIO_H
#define DSA_ACCEL_MMIO_H

#include "../../drivers/dsa_accel.h"

#define SOC_CTRL_BASE 0x20000000u
#define SOC_STATUS_PASS 1u
#define SOC_STATUS_FAIL 2u

void soc_finish(uint32_t status);

#endif
