SHELL := /bin/bash
ROOT := $(abspath .)
VCS ?= vcs
PYTHON ?= python3
SIZE ?= 4
IA_CACHE_BLOCKS ?= 4
PS_FRAME_COUNT ?= 8
AXI_READ_OUTSTANDING ?= 4
CASE ?= ai_mem_gen_smoke_test
SEED ?= 1
DUT_MODE ?= axil
SIM_ARGS ?=
GEN_ARGS ?=
DEBUG ?= 0
PAPER_ENGINE ?= 0
PS_POOL_BYTES ?= 179200
PANEL_MAX_R ?= 16
PANEL_MAX_W ?= 16
PAPER_DEFINES = $(if $(filter 1,$(PAPER_ENGINE)),+define+GEMPACT_PANEL_ENGINE+GEMPACT_PCR_PS+GEMMORA_PS_POOL_BYTES=$(PS_POOL_BYTES)+GEMPACT_PANEL_MAX_R=$(PANEL_MAX_R)+GEMPACT_PANEL_MAX_W=$(PANEL_MAX_W),)
LOG_NAME ?= sim
COUNT ?= 20
RANDOM_GEN_ARGS ?= --random --random_quant --lhs_dtype 0 --min_dim 1 --max_dim 32
SIZES ?= 4 8 16
CACHE_BLOCKS_LIST ?= 2 4 8
COMPUTE_DATA_DIR ?= $(UNIT_BUILD)/compute_case
-include drivers/tflm/model_selection.mk
DEPLOY_TFLM_APP ?= mnist_mlp_int16x8
DEPLOY_BUILD_TARGET ?= tflm_mnist_mlp_int16x8_soc_c
DEPLOY_CPU_MEM_WORDS ?= 65536
SOC_CPU_MEM_DP ?= $(DEPLOY_CPU_MEM_WORDS)
TFLM_APP ?= $(DEPLOY_TFLM_APP)

UNIT_TESTS := axi_dual_block_dma axi_block_dma_arbiter ps_buffer compute_core npu_top
UNIT_BUILD := $(ROOT)/build/vcs/unit
NPU_RTL := $(sort $(shell find $(ROOT)/rtl/npu -type f \( -name '*.sv' -o -name '*.v' \)))
RAM_RTL := $(ROOT)/rtl/common/pseudo_dual_port_ram.v
COMPUTE_RTL := $(ROOT)/rtl/npu/compute
BUFFER_RTL := $(ROOT)/rtl/npu/buffers
DMA_RTL := $(ROOT)/rtl/npu/dma

SRCS_axi_dual_block_dma := test/axi_dual_block_dma/tb_axi_dual_block_dma.sv rtl/npu/dma/axi_dual_block_dma.sv
SRCS_axi_block_dma_arbiter := test/axi_block_dma_arbiter/tb_axi_block_dma_arbiter.sv rtl/npu/dma/axi_block_dma_arbiter.sv rtl/npu/dma/axi_dual_block_dma.sv
SRCS_ps_buffer := test/ps_buffer/tb_ps_buffer.sv $(BUFFER_RTL)/ps_buffer.sv $(BUFFER_RTL)/ps_buffer_fifo.sv $(COMPUTE_RTL)/de_diagonalizer.sv $(RAM_RTL)
SRCS_compute_core := $(COMPUTE_DATA_DIR)/test_params_pkg.sv test/compute_core/tb_compute_core.sv test/compute_core/tb_compute_core_if.sv test/compute_core/compute_core_test.sv $(COMPUTE_RTL)/bias_mux.sv $(BUFFER_RTL)/ps_buffer.sv $(BUFFER_RTL)/ps_buffer_fifo.sv $(COMPUTE_RTL)/de_diagonalizer.sv $(RAM_RTL) $(COMPUTE_RTL)/ws_systolic_array.sv $(COMPUTE_RTL)/ws_systolic_cell.sv
SRCS_npu_top := $(if $(filter 1,$(PAPER_ENGINE)),test/paper/tb_npu_top.sv test/paper/ddr_axi_mem_model.sv,test/npu_top/tb_npu_top.sv test/npu_top/tb_sirv_stubs.v test/dep_modules/ddr_axi_mem_model.sv) $(NPU_RTL) $(RAM_RTL)
PASS_axi_dual_block_dma := [AXI_DUAL_DMA] ALL PASS
PASS_axi_block_dma_arbiter := [AXI_ARB] ALL PASS
PASS_ps_buffer := PASS: diagonal partial-sum
PASS_compute_core := PASS: compute_core matched
PASS_npu_top := [TB] PASS
CONFIG_TAG := s$(SIZE)_c$(IA_CACHE_BLOCKS)_p$(PS_FRAME_COUNT)_ro$(AXI_READ_OUTSTANDING)
UNIT_DIR = $(UNIT_BUILD)/$(UNIT)$(if $(filter npu_top,$(UNIT)),/$(CONFIG_TAG),)$(if $(filter 1,$(PAPER_ENGINE)),_paper_b$(PS_POOL_BYTES)_r$(PANEL_MAX_R)_w$(PANEL_MAX_W),)$(if $(filter 1,$(DEBUG)),_debug,)
UNIT_DEFINES = $(if $(filter 1,$(PAPER_ENGINE)),+define+TB_MEM_WORDS=131072,) $(if $(filter npu_top,$(UNIT)),+define+TB_SIZE=$(SIZE)+TB_IA_CACHE_BLOCKS=$(IA_CACHE_BLOCKS)+TB_PS_FRAME_COUNT=$(PS_FRAME_COUNT)+TB_AXI_READ_OUTSTANDING=$(AXI_READ_OUTSTANDING),)

.PHONY: help vcs-unit vcs-unit-% vcs-unit-build vcs-uvm vcs-axil vcs-soc vcs-top vcs-tflm vcs-nmsis-abi clean-vcs prepare-vcs-python

help:
	@echo 'make vcs-unit                 Run all module and NPU tests with VCS'
	@echo 'make vcs-unit-<name>          Run one test: $(UNIT_TESTS)'
	@echo 'make vcs-axil CASE=<name>     Run an AXI-Lite UVM test'
	@echo 'make vcs-soc CASE=<name>      Run a SoC UVM test'
	@echo 'make vcs-uvm DUT_MODE=<mode> CASE=<name>  Run an integrated UVM test'
	@echo 'make vcs-top                  Run the NPU top test with VCS'
	@echo 'make vcs-paper-soc            Run the paper engine in the SoC'
	@echo 'make vcs-tflm TFLM_APP=<name> Run TFLM inference on the SoC'
	@echo 'make model-list               List deployment models'
	@echo 'make model-select MODEL=<name> Select a deployment model'
	@echo 'make model-build              Build selected model firmware'
	@echo 'make vcs-nmsis-abi            Run the NMSIS driver integration test'
	@echo 'make vcs-random-npu           Run randomized NPU top tests'
	@echo 'make vcs-random-compute       Run randomized compute core tests'
	@echo 'Parameters: SIZE IA_CACHE_BLOCKS PS_FRAME_COUNT AXI_READ_OUTSTANDING SEED SIM_ARGS'

vcs-unit:
	@set -e; for unit in $(UNIT_TESTS); do $(MAKE) --no-print-directory vcs-unit-$$unit; done

vcs-unit-%:
	@$(MAKE) --no-print-directory vcs-unit-run UNIT=$*

vcs-unit-build:
	@test -n "$(SRCS_$(UNIT))" || { echo 'Unknown unit: $(UNIT)' >&2; exit 2; }
	@mkdir -p '$(UNIT_DIR)'
	@if [ '$(UNIT)' = compute_core ] && [ '$(COMPUTE_DATA_DIR)' = '$(UNIT_BUILD)/compute_case' ]; then \
	  mkdir -p '$(COMPUTE_DATA_DIR)'; \
	  cd '$(COMPUTE_DATA_DIR)' && $(PYTHON) '$(ROOT)/test/compute_core/gen_mats.py' --seed $(SEED); \
	fi
	$(VCS) -full64 -sverilog -timescale=1ns/1ps $(if $(filter 1,$(DEBUG)),-debug_access+all,) -top tb_$(UNIT) \
	  $(UNIT_DEFINES) $(PAPER_DEFINES) +incdir+$(ROOT)/rtl/npu/gempact +incdir+$(ROOT)/test/compute_core \
	  -Mdir='$(UNIT_DIR)/csrc' -o '$(UNIT_DIR)/simv' \
	  -l '$(UNIT_DIR)/compile.log' $(foreach src,$(SRCS_$(UNIT)),$(if $(filter /%,$(src)),$(src),$(ROOT)/$(src)))

.PHONY: vcs-unit-run
vcs-unit-run: vcs-unit-build
	@if [ '$(UNIT)' = npu_top ]; then \
	  $(PYTHON) test/npu_top/gen_mem.py --out_dir '$(UNIT_DIR)/case' \
	    --size $(SIZE) --ia_cache_blocks $(IA_CACHE_BLOCKS) --ps_frame_count $(PS_FRAME_COUNT) $(GEN_ARGS); \
	fi
	@cd '$(UNIT_DIR)' && $(PYTHON) '$(ROOT)/veri/sim/run_checked.py' \
	  --log '$(UNIT_DIR)/$(LOG_NAME).log' --pass '$(PASS_$(UNIT))' -- \
	  '$(ROOT)/veri/sim/run_simv_lxc.sh' '$(UNIT_DIR)/simv' \
	  $(if $(filter compute_core,$(UNIT)),+DATA_DIR=$(COMPUTE_DATA_DIR),) \
	  $(if $(filter npu_top,$(UNIT)),+INIT_MEM=$(UNIT_DIR)/case/init.mem +GOLDEN_MEM=$(UNIT_DIR)/case/golden.mem +CASE_MEM=$(UNIT_DIR)/case/config.mem,) $(SIM_ARGS)

vcs-top: vcs-unit-npu_top

.PHONY: vcs-random-npu vcs-random-compute vcs-param-npu
vcs-random-npu:
	@set -e; for ((i=0; i<$(COUNT); i++)); do \
	  current_seed=$$(( $(SEED) + i )); \
	  $(MAKE) --no-print-directory vcs-top LOG_NAME=random_$$current_seed GEN_ARGS='$(RANDOM_GEN_ARGS)'" --seed $$current_seed"; \
	done

vcs-param-npu:
	@set -e; for size in $(SIZES); do for cache in $(CACHE_BLOCKS_LIST); do \
	  $(MAKE) --no-print-directory vcs-random-npu SIZE=$$size IA_CACHE_BLOCKS=$$cache; \
	done; done

vcs-random-compute:
	@set -e; for ((i=0; i<$(COUNT); i++)); do \
	  current_seed=$$(( $(SEED) + i )); dir='$(UNIT_BUILD)/compute_random/'$$current_seed; \
	  mkdir -p "$$dir"; (cd "$$dir" && $(PYTHON) '$(ROOT)/test/compute_core/gen_mats.py' --seed $$current_seed --random-shape); \
	  $(MAKE) --no-print-directory vcs-unit-run UNIT=compute_core COMPUTE_DATA_DIR="$$dir" LOG_NAME=random_$$current_seed; \
	done

prepare-vcs-python:
	$(PYTHON) scripts/prepare_vcs_python.py

vcs-uvm: prepare-vcs-python
	$(MAKE) -C veri/sim run DUT_MODE=$(DUT_MODE) case=$(CASE) seed=$(SEED) \
	  MMA_SIZE=$(SIZE) MMA_IA_CACHE_BLOCKS=$(IA_CACHE_BLOCKS) MMA_PS_FRAME_COUNT=$(PS_FRAME_COUNT) \
	  SOC_AXI_READ_OUTSTANDING=$(AXI_READ_OUTSTANDING) PAPER_ENGINE=$(PAPER_ENGINE) PS_POOL_BYTES=$(PS_POOL_BYTES) PANEL_MAX_R=$(PANEL_MAX_R) PANEL_MAX_W=$(PANEL_MAX_W) DUMPOPTS=0 SIM_ARGS='$(SIM_ARGS)'

vcs-axil:
	$(MAKE) vcs-uvm DUT_MODE=axil CASE=$(CASE)

vcs-soc:
	$(MAKE) vcs-uvm DUT_MODE=axi_soc CASE=$(if $(filter ai_mem_gen_smoke_test,$(CASE)),ai_axi_soc_c_test,$(CASE))

vcs-nmsis-abi:
	$(MAKE) vcs-soc SOC_APP=nmsis_abi SOC_CASE=axi_soc_case_nmsis_abi

vcs-tflm: prepare-vcs-python
	$(MAKE) -C veri/sim tflm_$(TFLM_APP)_run SOC_CPU_MEM_DP=$(SOC_CPU_MEM_DP) MMA_SIZE=$(SIZE) \
	  MMA_IA_CACHE_BLOCKS=$(IA_CACHE_BLOCKS) MMA_PS_FRAME_COUNT=$(PS_FRAME_COUNT) \
	  SOC_AXI_READ_OUTSTANDING=$(AXI_READ_OUTSTANDING) PAPER_ENGINE=$(PAPER_ENGINE) PS_POOL_BYTES=$(PS_POOL_BYTES) PANEL_MAX_R=$(PANEL_MAX_R) PANEL_MAX_W=$(PANEL_MAX_W) DUMPOPTS=0 SIM_ARGS='$(SIM_ARGS)'

clean-vcs:
	rm -rf '$(UNIT_BUILD)'

.PHONY: model-list model-select model-build
model-list:
	$(PYTHON) drivers/tflm/select_model.py --list

model-select:
	$(PYTHON) drivers/tflm/select_model.py $(if $(MODEL),--select $(MODEL),)

model-build:
	$(MAKE) -C veri/sim $(DEPLOY_BUILD_TARGET) SOC_CASE=axi_soc_tflm_deploy SOC_CPU_MEM_DP=$(SOC_CPU_MEM_DP) \
	  MMA_SIZE=$(SIZE) MMA_IA_CACHE_BLOCKS=$(IA_CACHE_BLOCKS) MMA_PS_FRAME_COUNT=$(PS_FRAME_COUNT)

.PHONY: vcs-paper-soc
vcs-paper-soc:
	$(MAKE) vcs-soc PAPER_ENGINE=1 SIZE=16 IA_CACHE_BLOCKS=64 PS_FRAME_COUNT=25 SOC_APP=paper_nmsis SOC_CASE=axi_soc_case_paper_nmsis
