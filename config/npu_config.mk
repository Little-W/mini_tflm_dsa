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
include $(NPU_CONFIG)

# The legacy entry points have different historical array-size defaults. Only
# the PCR mode shares SIZE across them; the panel engine requires SIZE=16.
ifeq ($(PCR_ENGINE),1)
MMA_SIZE ?= $(SIZE)
MMA_IA_CACHE_BLOCKS ?= $(IA_CACHE_BLOCKS)
MMA_PS_FRAME_COUNT ?= $(PS_FRAME_COUNT)
SOC_AXI_READ_OUTSTANDING ?= $(AXI_READ_OUTSTANDING)
NPU_SIZE ?= $(SIZE)
NPU_IA_CACHE_BLOCKS ?= $(IA_CACHE_BLOCKS)
NPU_PS_FRAME_COUNT ?= $(PS_FRAME_COUNT)
NPU_AXI_READ_OUTSTANDING ?= $(AXI_READ_OUTSTANDING)
endif

CAPACITY_SOLVER := $(NPU_CONFIG_ROOT)/scripts/capacity/solve.py
CAPACITY_OUTPUT ?= $(NPU_CONFIG_ROOT)/build/capacity/solution.json
WORKLOADS ?= $(NPU_CONFIG_ROOT)/config/capacity_workloads.json
CAPACITY_SHAPES = $(strip $(SHAPE) $(SHAPES))
CAPACITY_TASK_ARGS = $(if $(CAPACITY_SHAPES),$(foreach shape,$(CAPACITY_SHAPES),--shape '$(shape)'),--workloads '$(abspath $(WORKLOADS))')
CAPACITY_LIMIT_ARGS = $(if $(MAX_RAM_KIB),--max-ram-kib '$(MAX_RAM_KIB)',$(if $(MAX_STATE_KIB),--max-state-kib '$(MAX_STATE_KIB)',))
CAPACITY_REPR_ARGS = $(if $(REPRESENTATION),--representation '$(REPRESENTATION)',)

# Each build entry point may map these four values to its actual top-level
# parameter names before using capacity-check; all other keys are common.
NPU_CAPACITY_SIZE ?= $(SIZE)
NPU_CAPACITY_CACHE ?= $(IA_CACHE_BLOCKS)
NPU_CAPACITY_FRAMES ?= $(PS_FRAME_COUNT)
NPU_CAPACITY_READ_OUTSTANDING ?= $(AXI_READ_OUTSTANDING)
NPU_EFFECTIVE_CONFIG_VALUES = PCR_ENGINE=$(PCR_ENGINE) SIZE=$(NPU_CAPACITY_SIZE) \
  IA_CACHE_BLOCKS=$(NPU_CAPACITY_CACHE) PS_FRAME_COUNT=$(NPU_CAPACITY_FRAMES) \
  AXI_READ_OUTSTANDING=$(NPU_CAPACITY_READ_OUTSTANDING) \
  PANEL_MAX_R=$(PANEL_MAX_R) PANEL_MAX_W=$(PANEL_MAX_W) \
  PS_POOL_BYTES=$(PS_POOL_BYTES) PS_FORCE_RAW=$(PS_FORCE_RAW) \
  CAPACITY_BUDGET_BYTES=$(CAPACITY_BUDGET_BYTES) \
  CAPACITY_BUDGET_SCOPE=$(CAPACITY_BUDGET_SCOPE) \
  CAPACITY_REPRESENTATION=$(CAPACITY_REPRESENTATION)
NPU_CAPACITY_SET_ARGS = $(foreach setting,$(NPU_EFFECTIVE_CONFIG_VALUES),--set '$(setting)')

ifneq ($(filter capacity-solve,$(MAKECMDGOALS)),)
ifneq ($(words $(MAKECMDGOALS)),1)
$(error capacity-solve cannot share a Make invocation with other targets; run it first, then invoke the build so the new configuration is read)
endif
ifneq ($(strip $(MAX_RAM_KIB)),)
ifneq ($(strip $(MAX_STATE_KIB)),)
$(error choose MAX_RAM_KIB for buffer RAM or MAX_STATE_KIB for complete logical state, not both)
endif
endif
endif

.PHONY: capacity-solve capacity-show capacity-check capacity-test npu-config-force
capacity-solve:
	$(PYTHON) '$(CAPACITY_SOLVER)' --config '$(NPU_CONFIG)' $(NPU_CAPACITY_SET_ARGS) \
	  $(CAPACITY_LIMIT_ARGS) $(CAPACITY_REPR_ARGS) $(CAPACITY_TASK_ARGS) \
	  --apply --output '$(abspath $(CAPACITY_OUTPUT))' $(CAPACITY_ARGS)

capacity-show:
	$(PYTHON) '$(CAPACITY_SOLVER)' --config '$(NPU_CONFIG)' $(NPU_CAPACITY_SET_ARGS) --show

capacity-check:
	$(PYTHON) '$(CAPACITY_SOLVER)' --config '$(NPU_CONFIG)' $(NPU_CAPACITY_SET_ARGS) --check

capacity-test:
	$(PYTHON) -m unittest discover -s '$(NPU_CONFIG_ROOT)/test/capacity' -p 'test_*.py' -v

npu-config-force:
endif
