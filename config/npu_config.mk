# Common configuration loader and capacity commands. Include before defaults.
# This file contains Make logic; npu.mk is the user-editable configuration.
ifneq ($(origin NPU_CONFIG_INCLUDED),file)
NPU_CONFIG_INCLUDED := 1
unexport NPU_CONFIG_INCLUDED
NPU_CONFIG_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
PYTHON ?= python3
ifneq ($(origin CONFIG),undefined)
NPU_CONFIG ?= $(CONFIG)
endif
NPU_CONFIG ?= $(NPU_CONFIG_ROOT)/config/npu.mk
override NPU_CONFIG := $(abspath $(NPU_CONFIG))
export NPU_CONFIG
ifneq ($(filter menuconfig,$(MAKECMDGOALS)),)
# An interactive editor may create a new configuration when the user saves.
-include $(NPU_CONFIG)
else
include $(NPU_CONFIG)
endif

# Shared array/cache/frame parameters apply to every PS storage mode.
NPU_AXI_DATA_WIDTH ?= 64
IM2COL_CACHE_BYTES ?= 4096
CONV_LOW_LATENCY ?= 0
SHARED_BANK_BYTES ?= 2048
SHARED_BANK_COUNT ?= 7
IA_COMPACT_ENABLE ?= 0
ifeq ($(filter 0 1,$(strip $(IA_COMPACT_ENABLE))),)
$(error IA_COMPACT_ENABLE must be 0 or 1)
endif
ifneq ($(words $(IA_COMPACT_ENABLE)),1)
$(error IA_COMPACT_ENABLE must be 0 or 1)
endif
ifeq ($(filter 0 1,$(strip $(CONV_LOW_LATENCY))),)
$(error CONV_LOW_LATENCY must be 0 or 1)
endif
ifneq ($(words $(CONV_LOW_LATENCY)),1)
$(error CONV_LOW_LATENCY must be 0 or 1)
endif
export NPU_AXI_DATA_WIDTH IM2COL_CACHE_BYTES SHARED_BANK_BYTES SHARED_BANK_COUNT IA_COMPACT_ENABLE CONV_LOW_LATENCY
NPU_BUS_WIDTH ?= $(NPU_AXI_DATA_WIDTH)
MMA_SIZE ?= $(SIZE)
MMA_IA_CACHE_BLOCKS ?= $(IA_CACHE_BLOCKS)
MMA_PS_FRAME_COUNT ?= $(PS_FRAME_COUNT)
SOC_AXI_READ_OUTSTANDING ?= $(AXI_READ_OUTSTANDING)
NPU_SIZE ?= $(SIZE)
NPU_IA_CACHE_BLOCKS ?= $(IA_CACHE_BLOCKS)
NPU_PS_FRAME_COUNT ?= $(PS_FRAME_COUNT)
NPU_AXI_READ_OUTSTANDING ?= $(AXI_READ_OUTSTANDING)

CAPACITY_SOLVER := $(NPU_CONFIG_ROOT)/scripts/capacity/solve.py
NPU_MENUCONFIG := $(NPU_CONFIG_ROOT)/scripts/capacity/menuconfig.py
CAPACITY_OUTPUT ?= $(NPU_CONFIG_ROOT)/build/capacity/solution.json
WORKLOADS ?= $(NPU_CONFIG_ROOT)/config/capacity_workloads.json
CAPACITY_SHAPES = $(strip $(SHAPE) $(SHAPES))
CAPACITY_TASK_ARGS = $(if $(CAPACITY_SHAPES),$(foreach shape,$(CAPACITY_SHAPES),--shape '$(shape)'),--workloads '$(abspath $(WORKLOADS))')
CAPACITY_LIMIT_ARGS = $(if $(MAX_RAM_KIB),--max-ram-kib '$(MAX_RAM_KIB)',$(if $(MAX_STATE_KIB),--max-state-kib '$(MAX_STATE_KIB)',))
CAPACITY_REPR_ARGS = $(if $(REPRESENTATION),--representation '$(REPRESENTATION)',)
CAPACITY_VERILATOR ?= $(if $(VERILATOR),$(VERILATOR),verilator)
CAPACITY_SOLVE_SCOPE = $(if $(MAX_RAM_KIB),buffer-ram,$(if $(MAX_STATE_KIB),logical-state,$(CAPACITY_BUDGET_SCOPE)))
CAPACITY_SOLVE_MEASURE_ARGS = $(if $(filter logical-state,$(CAPACITY_SOLVE_SCOPE)),--measure-state,)
CAPACITY_INSPECT_MEASURE_ARGS = $(if $(filter logical-state,$(CAPACITY_BUDGET_SCOPE)),--measure-state,)

# Each build entry point may map these four values to its actual top-level
# parameter names before using capacity-check; all other keys are common.
NPU_CAPACITY_SIZE ?= $(SIZE)
NPU_CAPACITY_CACHE ?= $(IA_CACHE_BLOCKS)
NPU_CAPACITY_FRAMES ?= $(PS_FRAME_COUNT)
NPU_CAPACITY_READ_OUTSTANDING ?= $(AXI_READ_OUTSTANDING)
NPU_CAPACITY_AXI_DATA_WIDTH ?= $(NPU_AXI_DATA_WIDTH)
NPU_EFFECTIVE_CONFIG_VALUES = PCR_ENGINE=$(PCR_ENGINE) SIZE=$(NPU_CAPACITY_SIZE) \
  NPU_AXI_DATA_WIDTH=$(NPU_CAPACITY_AXI_DATA_WIDTH) \
  IM2COL_CACHE_BYTES=$(IM2COL_CACHE_BYTES) CONV_LOW_LATENCY=$(CONV_LOW_LATENCY) \
  SHARED_BANK_BYTES=$(SHARED_BANK_BYTES) SHARED_BANK_COUNT=$(SHARED_BANK_COUNT) \
  IA_CACHE_BLOCKS=$(NPU_CAPACITY_CACHE) IA_COMPACT_ENABLE=$(IA_COMPACT_ENABLE) PS_FRAME_COUNT=$(NPU_CAPACITY_FRAMES) \
  AXI_READ_OUTSTANDING=$(NPU_CAPACITY_READ_OUTSTANDING) \
  PS_POOL_BYTES=$(PS_POOL_BYTES) PS_FORCE_RAW=$(PS_FORCE_RAW) \
  CAPACITY_BUDGET_BYTES=$(CAPACITY_BUDGET_BYTES) \
  CAPACITY_BUDGET_SCOPE=$(CAPACITY_BUDGET_SCOPE) \
  CAPACITY_REPRESENTATION=$(CAPACITY_REPRESENTATION)
NPU_CAPACITY_SET_ARGS = $(foreach setting,$(NPU_EFFECTIVE_CONFIG_VALUES),--set '$(setting)')

# The editor starts from the persistent file. Import only explicit common-key
# command-line overrides; the persistent file supplies all other values.
NPU_CONFIG_KEYS := PCR_ENGINE SIZE NPU_AXI_DATA_WIDTH IA_CACHE_BLOCKS IA_COMPACT_ENABLE PS_FRAME_COUNT AXI_READ_OUTSTANDING \
  IM2COL_CACHE_BYTES CONV_LOW_LATENCY \
  SHARED_BANK_BYTES SHARED_BANK_COUNT \
  PS_POOL_BYTES PS_FORCE_RAW CAPACITY_BUDGET_BYTES \
  CAPACITY_BUDGET_SCOPE CAPACITY_REPRESENTATION
NPU_MENUCONFIG_SET_ARGS = $(foreach key,$(NPU_CONFIG_KEYS),$(if $(filter command line,$(origin $(key))),--set '$(key)=$($(key))',))
MENUCONFIG_ARGS ?=

ifneq ($(filter capacity-solve menuconfig,$(MAKECMDGOALS)),)
ifneq ($(words $(MAKECMDGOALS)),1)
$(error $(filter capacity-solve menuconfig,$(MAKECMDGOALS)) cannot share a Make invocation with other targets; run it first, then invoke the build so the new configuration is read)
endif
ifneq ($(strip $(MAX_RAM_KIB)),)
ifneq ($(strip $(MAX_STATE_KIB)),)
$(error choose MAX_RAM_KIB for buffer RAM or MAX_STATE_KIB for complete logical state, not both)
endif
endif
endif

.PHONY: menuconfig capacity-solve capacity-show capacity-check capacity-test npu-config-force
menuconfig:
	@$(PYTHON) '$(NPU_MENUCONFIG)' --config '$(NPU_CONFIG)' $(NPU_MENUCONFIG_SET_ARGS) \
	  $(CAPACITY_LIMIT_ARGS) $(CAPACITY_REPR_ARGS) $(CAPACITY_TASK_ARGS) \
	  --output '$(abspath $(CAPACITY_OUTPUT))' --verilator '$(CAPACITY_VERILATOR)' $(MENUCONFIG_ARGS)

capacity-solve:
	$(PYTHON) '$(CAPACITY_SOLVER)' --config '$(NPU_CONFIG)' $(NPU_CAPACITY_SET_ARGS) \
	  $(CAPACITY_LIMIT_ARGS) $(CAPACITY_REPR_ARGS) $(CAPACITY_TASK_ARGS) \
	  --apply --output '$(abspath $(CAPACITY_OUTPUT))' $(CAPACITY_SOLVE_MEASURE_ARGS) \
	  --verilator '$(CAPACITY_VERILATOR)' $(CAPACITY_ARGS)

capacity-show:
	$(PYTHON) '$(CAPACITY_SOLVER)' --config '$(NPU_CONFIG)' $(NPU_CAPACITY_SET_ARGS) --show \
	  $(CAPACITY_INSPECT_MEASURE_ARGS) --verilator '$(CAPACITY_VERILATOR)'

capacity-check:
	$(PYTHON) '$(CAPACITY_SOLVER)' --config '$(NPU_CONFIG)' $(NPU_CAPACITY_SET_ARGS) --check \
	  $(CAPACITY_INSPECT_MEASURE_ARGS) --verilator '$(CAPACITY_VERILATOR)'

capacity-test:
	$(PYTHON) -m unittest discover -s '$(NPU_CONFIG_ROOT)/test/capacity' -p 'test_*.py' -v

npu-config-force:
endif
