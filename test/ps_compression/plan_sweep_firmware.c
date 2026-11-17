/* SPDX-License-Identifier: Apache-2.0 */
#include <stdint.h>

/* The host supplies register values and tensor addresses for one operator. */
volatile uint32_t plan_sweep_result[4];

static uint32_t cycle(void)
{
    uint32_t value;
    __asm__ volatile("rdcycle %0" : "=r"(value));
    return value;
}

static void marker(uint32_t value)
{
    __asm__ volatile("" ::: "memory");
    *(volatile uint32_t *)(uintptr_t)0x2000000cu = value;
    __asm__ volatile("" ::: "memory");
}

int main(void)
{
    const volatile uint32_t *config = (const volatile uint32_t *)(uintptr_t)0x001e0000u;
    volatile uint32_t *npu = (volatile uint32_t *)(uintptr_t)0x10000000u;
    uint32_t start, end, status;
    if (config[0] != 0x504c414eu || config[4] > 64u) return 1;
    npu[0] = 0;
    npu[1] = 4u;
    for (uint32_t i = 0; i < config[4]; ++i)
        npu[config[5u + 2u * i] / 4u] = config[6u + 2u * i];
    marker(0xc0f10001u);
    start = cycle();
    npu[0] = config[1] | 1u;
    do {
        status = npu[1];
    } while (!(status & 4u));
    end = cycle();
    marker(0xc0f10002u);
    plan_sweep_result[0] = end - start;
    plan_sweep_result[1] = (status >> 3u) & 3u;
    plan_sweep_result[2] = config[2];
    plan_sweep_result[3] = config[3];
    return plan_sweep_result[1] ? 2 : 0;
}
