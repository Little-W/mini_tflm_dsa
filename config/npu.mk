# Shared compute array and addressable PS frame storage defaults.
# Shared data capacity is SHARED_BANK_BYTES * SHARED_BANK_COUNT.
# Model initialization assigns 1, 2 or 4 banks to IA and the remainder to PS.
# ASIC banks use complete RAMTP128X16 macros; FPGA uses config/npu_fpga.mk.
# Literal assignments allow command-line Make variables to override values.
PCR_ENGINE ?= 1
SIZE ?= 16
# NPU AXI4 DMA, shared memory interconnect and RAM data width: 32 or 64 bits.
# The CPU and NPU AXI-Lite register data interfaces remain 32 bits.
NPU_AXI_DATA_WIDTH ?= 64
SHARED_BANK_BYTES ?= 2048
SHARED_BANK_COUNT ?= 7
IA_CACHE_BLOCKS ?= 4
PS_FRAME_COUNT ?= 16
AXI_READ_OUTSTANDING ?= 4
PS_POOL_BYTES ?= 12288
PS_FORCE_RAW ?= 0
CAPACITY_BUDGET_BYTES ?= 131072
CAPACITY_BUDGET_SCOPE ?= buffer-ram
CAPACITY_REPRESENTATION ?= adaptive
