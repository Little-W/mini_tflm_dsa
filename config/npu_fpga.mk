# Xilinx 7 series FPGA configuration.
# Each 128-bit by 512-row shared bank uses the complete data capacity of two
# RAMB36E1 primitives. Parity bits are separate from software-visible storage.
# Model initialization assigns 1, 2 or 4 banks to IA and the remainder to PS.
PCR_ENGINE ?= 1
SIZE ?= 16
NPU_AXI_DATA_WIDTH ?= 64
# im2col input data cache; two ways and 16-byte lines, 512..65536 bytes.
# 4 KiB holds one 3-row K16 band up to width 85 (S8) or 42 (S16),
# for aligned NHWC, channels divisible by 16, and dilation 1.
# See docs/im2col_cache_configuration.md for complete size guidance.
IM2COL_CACHE_BYTES ?= 4096
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
