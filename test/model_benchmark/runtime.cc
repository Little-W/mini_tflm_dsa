/* SPDX-License-Identifier: Apache-2.0 */
/* Use the existing UART/syscall runtime verbatim. Its _sbrk limit is the
 * supplied symbol minus 4096, so this test-only name keeps heap allocations
 * below the read-only model overlay without moving the actual CPU stack. */
#define _stack_top full_network_heap_stack_top
#include "../../veri/soc_csrc/tflm_soc_runtime.cc"
