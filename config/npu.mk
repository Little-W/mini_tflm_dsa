# Shared compute array and addressable PS frame storage defaults.
# Shared data capacity is SHARED_BANK_BYTES * SHARED_BANK_COUNT.
# Model initialization assigns 1 or 2 banks to IA, or 4 when at least 8 banks are present.
# ASIC banks use complete RAMTP128X16 macros; FPGA uses config/npu_fpga.mk.
# Literal assignments allow command-line Make variables to override values.
PCR_ENGINE ?= 1
SIZE ?= 16
# NPU AXI4 DMA, shared memory interconnect and RAM data width: 32 or 64 bits.
# The CPU and NPU AXI-Lite register data interfaces remain 32 bits.
NPU_AXI_DATA_WIDTH ?= 64
# Original-image cache used by hardware im2col and vector image reads.
# Data bytes only; two ways, 128-byte lines. Power of two: 512..65536.
# 4 KiB holds one 3-row K16 band up to width 85 (S8) or 42 (S16),
# for aligned NHWC, channels divisible by 16, and dilation 1.
# See docs/im2col_cache_configuration.md for convolution-size guidance.
IM2COL_CACHE_BYTES ?= 4096
SHARED_BANK_BYTES ?= 2048
SHARED_BANK_COUNT ?= 9
IA_CACHE_BLOCKS ?= 2
# IA 紧凑存储开关：0 为十六位存储，1 允许八位输入紧凑存储。
IA_COMPACT_ENABLE ?= 0
PS_FRAME_COUNT ?= 4
AXI_READ_OUTSTANDING ?= 4
PS_POOL_BYTES ?= 16384
PS_FORCE_RAW ?= 1
CAPACITY_BUDGET_BYTES ?= 131072
CAPACITY_BUDGET_SCOPE ?= buffer-ram
CAPACITY_REPRESENTATION ?= raw32
