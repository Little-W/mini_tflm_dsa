# Xilinx 7 series FPGA configuration.
# Each 128-bit by 512-row shared bank uses the complete data capacity of two
# RAMB36E1 primitives. Parity bits are separate from software-visible storage.
# Model initialization assigns 1 or 2 banks to IA, or 4 when at least 8 banks are present.
PCR_ENGINE ?= 1
SIZE ?= 16
NPU_AXI_DATA_WIDTH ?= 64
# im2col 使用两路缓存，容量为 512..65536 字节，缓存行长度由硬件顶层参数指定。
# 4 KiB holds one 3-row K16 band up to width 85 (S8) or 42 (S16),
# for aligned NHWC, channels divisible by 16, and dilation 1.
# See docs/im2col_cache_configuration.md for complete size guidance.
IM2COL_CACHE_BYTES ?= 4096
SHARED_BANK_BYTES ?= 8192
SHARED_BANK_COUNT ?= 7
IA_CACHE_BLOCKS ?= 4
# IA 紧凑存储开关：0 为十六位存储，1 允许八位输入紧凑存储。
IA_COMPACT_ENABLE ?= 0
PS_FRAME_COUNT ?= 16
AXI_READ_OUTSTANDING ?= 4
PS_POOL_BYTES ?= 49152
PS_FORCE_RAW ?= 1
CAPACITY_BUDGET_BYTES ?= 131072
CAPACITY_BUDGET_SCOPE ?= buffer-ram
CAPACITY_REPRESENTATION ?= raw32
