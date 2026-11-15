# Hardware defaults shared by the Make entry points.
# Values are literal ?= assignments; command-line Make variables take priority.
# `make capacity-solve` updates the PCR/capacity fields atomically.
PCR_ENGINE ?= 1
SIZE ?= 16
IA_CACHE_BLOCKS ?= 4
PS_FRAME_COUNT ?= 8
AXI_READ_OUTSTANDING ?= 4
PANEL_MAX_R ?= 8
PANEL_MAX_W ?= 16
PS_POOL_BYTES ?= 81920
PS_FORCE_RAW ?= 0
CAPACITY_BUDGET_BYTES ?= 131072
CAPACITY_BUDGET_SCOPE ?= buffer-ram
CAPACITY_REPRESENTATION ?= nominal3
