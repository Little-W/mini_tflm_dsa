#include "dsa_accel_mmio.h"

void soc_finish(uint32_t status) {
    dsa_mmio_write(SOC_CTRL_BASE, status);
    while (1) {
    }
}
