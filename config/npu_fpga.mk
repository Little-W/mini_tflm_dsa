# Xilinx 7 series FPGA configuration.
# Each 128-bit by 512-row shared bank uses the complete data capacity of two
# RAMB36E1 primitives. Parity bits are separate from software-visible storage.
# Model initialization assigns 1, 2 or 4 banks to IA and the remainder to PS.
PCR_ENGINE ?= 1
SIZE ?= 16
NPU_AXI_DATA_WIDTH ?= 64
SHARED_BANK_BYTES ?= 8192
SHARED_BANK_COUNT ?= 7
IA_CACHE_BLOCKS ?= 4
PS_FRAME_COUNT ?= 16
AXI_READ_OUTSTANDING ?= 4
PS_POOL_BYTES ?= 49152
PS_FORCE_RAW ?= 0
CAPACITY_BUDGET_BYTES ?= 131072
CAPACITY_BUDGET_SCOPE ?= buffer-ram
CAPACITY_REPRESENTATION ?= adaptive
