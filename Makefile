SHELL := /bin/bash
.DEFAULT_GOAL := help
include $(dir $(abspath $(lastword $(MAKEFILE_LIST))))config/npu_config.mk
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
PCR_ENGINE ?= 0
ASIC_SRAM ?= 0
SRAM_ROOT ?= /media/6/IC/lib/SRAM_Lib_2025
PS_POOL_BYTES ?= 12288
PCR_DEFINES = $(if $(filter 1,$(PCR_ENGINE)),+define+GEMPACT_PS_COMPRESS+GEMMORA_PS_POOL_BYTES=$(PS_POOL_BYTES)$(if $(filter 1,$(PS_FORCE_RAW)),+GEMMORA_PS_FORCE_RAW,),) $(if $(filter 1,$(ASIC_SRAM)),+define+ASIC_SRAM,)
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
NPU_PACKAGES := $(ROOT)/rtl/npu/conv/conv_im2col_pkg.sv $(ROOT)/rtl/npu/conv/vector_engine_pkg.sv
NPU_RTL := $(NPU_PACKAGES) $(filter-out $(NPU_PACKAGES),$(sort $(shell find $(ROOT)/rtl/npu -type f \( -name '*.sv' -o -name '*.v' \))))
NPU_RTL += $(if $(filter 1,$(ASIC_SRAM)),$(ROOT)/asic/rtl/smic40_sram_1r1w.sv $(SRAM_ROOT)/RAMTP128X16/verilog/RAMTP128X16.v $(SRAM_ROOT)/RAMTP1024X16/verilog/RAMTP1024X16.v,)
RAM_RTL := $(ROOT)/rtl/common/pseudo_dual_port_ram.v
COMPUTE_RTL := $(ROOT)/rtl/npu/compute
BUFFER_RTL := $(ROOT)/rtl/npu/buffers
DMA_RTL := $(ROOT)/rtl/npu/dma
PS_CODEC_RTL := $(ROOT)/rtl/npu/ps_compact/ps_adaptive_codec.sv $(ROOT)/rtl/npu/ps_compact/ps_frame_store.sv

UNIT_DMA_PACKAGES := rtl/npu/conv/conv_im2col_pkg.sv rtl/npu/conv/vector_engine_pkg.sv
UNIT_DMA_RTL := $(UNIT_DMA_PACKAGES) $(filter-out $(UNIT_DMA_PACKAGES),$(sort $(wildcard rtl/npu/conv/*.sv rtl/npu/dma/cache/*.sv))) rtl/npu/dma/conv_window_queue.sv rtl/npu/dma/axi_linear_block_dma.sv rtl/npu/dma/axi_write_page_guard.sv rtl/npu/dma/axi_dual_block_dma.sv
SRCS_axi_dual_block_dma := $(UNIT_DMA_RTL) test/axi_dual_block_dma/tb_axi_dual_block_dma.sv
SRCS_axi_block_dma_arbiter := $(UNIT_DMA_RTL) rtl/npu/dma/axi_block_dma_arbiter.sv test/axi_block_dma_arbiter/tb_axi_block_dma_arbiter.sv
SRCS_ps_buffer := test/ps_buffer/tb_ps_buffer.sv $(BUFFER_RTL)/ps_buffer.sv $(BUFFER_RTL)/ps_buffer_fifo.sv $(COMPUTE_RTL)/de_diagonalizer.sv $(RAM_RTL) $(PS_CODEC_RTL)
SRCS_compute_core := $(COMPUTE_DATA_DIR)/test_params_pkg.sv test/compute_core/tb_compute_core_if.sv test/compute_core/compute_core_test.sv test/compute_core/tb_compute_core.sv $(COMPUTE_RTL)/compute_core.sv $(COMPUTE_RTL)/bias_mux.sv $(BUFFER_RTL)/ps_buffer.sv $(RAM_RTL) $(COMPUTE_RTL)/ws_systolic_array.sv $(COMPUTE_RTL)/ws_systolic_cell.sv $(PS_CODEC_RTL)
SRCS_npu_top := test/npu_top/tb_npu_top.sv test/npu_top/tb_sirv_stubs.v test/dep_modules/ddr_axi_mem_model.sv $(NPU_RTL) $(RAM_RTL)
PASS_axi_dual_block_dma := [AXI_DUAL_DMA] ALL PASS
PASS_axi_block_dma_arbiter := [AXI_ARB] ALL PASS
PASS_ps_buffer := PASS: partial-sum replay
PASS_compute_core := PASS: compute_core matched
PASS_npu_top := [TB] PASS
CONFIG_TAG := s$(SIZE)_c$(IA_CACHE_BLOCKS)_p$(PS_FRAME_COUNT)_ro$(AXI_READ_OUTSTANDING)_axi$(NPU_AXI_DATA_WIDTH)_bank$(SHARED_BANK_BYTES)x$(SHARED_BANK_COUNT)_im2col$(IM2COL_CACHE_BYTES)
UNIT_DIR = $(UNIT_BUILD)/$(UNIT)$(if $(filter npu_top,$(UNIT)),/$(CONFIG_TAG),)$(if $(filter 1,$(PCR_ENGINE)),_pcr_b$(PS_POOL_BYTES)_f$(PS_FORCE_RAW),)$(if $(filter 1,$(ASIC_SRAM)),_asic_sram,)$(if $(filter 1,$(DEBUG)),_debug,)
UNIT_DEFINES = $(if $(filter 1,$(PCR_ENGINE)),+define+TB_MEM_WORDS=131072,) $(if $(filter npu_top,$(UNIT)),+define+TB_SIZE=$(SIZE)+TB_IA_CACHE_BLOCKS=$(IA_CACHE_BLOCKS)+TB_PS_FRAME_COUNT=$(PS_FRAME_COUNT)+TB_AXI_READ_OUTSTANDING=$(AXI_READ_OUTSTANDING)+TB_BUS_WIDTH=$(NPU_AXI_DATA_WIDTH)+TB_SHARED_BANK_BYTES=$(SHARED_BANK_BYTES)+TB_SHARED_BANK_COUNT=$(SHARED_BANK_COUNT)+TB_IM2COL_CACHE_BYTES=$(IM2COL_CACHE_BYTES),)

.PHONY: help vcs-unit vcs-unit-% vcs-unit-build vcs-uvm vcs-axil vcs-soc vcs-top vcs-tflm vcs-nmsis-abi clean-vcs prepare-vcs-python

help:
	@echo 'make menuconfig               Edit NPU parameters in an interactive terminal menu'
	@echo 'make capacity-show/check     Show or validate effective NPU_CONFIG parameters'
	@echo 'make capacity-solve MAX_RAM_KIB=<n>    Optimize buffer RAM and update NPU_CONFIG'
	@echo 'make capacity-solve MAX_STATE_KIB=<n>  Optimize complete logical state'
	@echo 'make capacity-test           Test solver and configuration integration'
	@echo 'make pcr-backend             Build the shared-array Verilator backend from the current configuration'
	@echo 'make conv-verify VERILATOR=/path/to/verilator YOSYS=yosys  Run hardware Conv validation'
	@echo 'make vector-engine-test VERILATOR=/path/to/verilator VECTOR_PE_COUNT=8  Run DW/pooling and vector validation'
	@echo 'make vector-engine-sweep VERILATOR=/path/to/verilator  Compare PE counts with RTL cycle measurements'
	@echo 'make vector-engine-soc              Run CNN, MobileNetV1, DS-CNN and ResNet-8 on PicoRV32'
	@echo 'make conv-npu conv-reuse       Check real NPU outputs and external input reuse'
	@echo 'make conv-dma                 Check unified DMA matrix/Conv commands in WS and IS'
	@echo 'make conv-soc-perf            Compare original CPU im2col and hardware Conv on PicoRV32'
	@echo 'make ps-stream-verify         Check row codec, frame store, scheduler, AXI abort and address division'
	@echo 'make ps-compression-soc       Compare RAW and adaptive reuse on complete CNN inference'
	@echo 'make shared-memory-test       Check shared IA/PS storage and unified NPU results'
	@echo 'make shared-memory-structure  Check shared SRAM inference with Yosys and slang'
	@echo 'make open-fpga-synth         Measure FPGA module resources with open-source Yosys'
	@echo 'make conv-page-split          Check shared DMA reads at 4-KiB and address-space boundaries'
	@echo 'make conv-vectors             Generate deterministic CNN vectors under build/'
	@echo 'make conv-real-cnn             Compare five caches on real CNN layer dimensions'
	@echo 'make vcs-unit                 Run all module and NPU tests with VCS'
	@echo 'make vcs-unit-<name>          Run one test: $(UNIT_TESTS)'
	@echo 'make vcs-axil CASE=<name>     Run an AXI-Lite UVM test'
	@echo 'make vcs-soc CASE=<name>      Run a SoC UVM test'
	@echo 'make vcs-uvm DUT_MODE=<mode> CASE=<name>  Run an integrated UVM test'
	@echo 'make vcs-top                  Run the NPU top test with VCS'
	@echo 'make -C asic sram-test         Test SRAM macro wrappers'
	@echo 'make -C asic syn               Run SMIC40 synthesis'
	@echo 'make vcs-pcr-soc            Run the shared GEMM/im2col engine with PS compression in the SoC'
	@echo 'make vcs-tflm TFLM_APP=<name> Run TFLM inference on the SoC'
	@echo 'make model-list               List deployment models'
	@echo 'make model-select MODEL=<name> Select a deployment model'
	@echo 'make model-build              Build selected model firmware'
	@echo 'make vcs-nmsis-abi            Run the NMSIS driver integration test'
	@echo 'make vcs-random-npu           Run randomized NPU top tests'
	@echo 'make vcs-random-compute       Run randomized compute core tests'
	@echo 'Config: NPU_CONFIG=$(NPU_CONFIG) (command-line parameters take priority)'
	@echo 'Parameters: SIZE IA_CACHE_BLOCKS IM2COL_CACHE_BYTES PS_FRAME_COUNT AXI_READ_OUTSTANDING SEED SIM_ARGS'

vcs-unit:
	@set -e; for unit in $(UNIT_TESTS); do $(MAKE) --no-print-directory vcs-unit-$$unit; done

vcs-unit-%:
	@$(MAKE) --no-print-directory vcs-unit-run UNIT=$*

vcs-unit-build: capacity-check $(NPU_CONFIG)
	@test -n "$(SRCS_$(UNIT))" || { echo 'Unknown unit: $(UNIT)' >&2; exit 2; }
	@mkdir -p '$(UNIT_DIR)'
	@if [ '$(UNIT)' = compute_core ] && [ '$(COMPUTE_DATA_DIR)' = '$(UNIT_BUILD)/compute_case' ]; then \
	  mkdir -p '$(COMPUTE_DATA_DIR)'; \
	  cd '$(COMPUTE_DATA_DIR)' && $(PYTHON) '$(ROOT)/test/compute_core/gen_mats.py' --seed $(SEED); \
	fi
	$(VCS) -full64 -sverilog -timescale=1ns/1ps $(if $(filter 1,$(DEBUG)),-debug_access+all,) -top tb_$(UNIT) \
	  $(UNIT_DEFINES) $(PCR_DEFINES) +incdir+$(ROOT)/rtl/npu/ps_compact +incdir+$(ROOT)/test/compute_core \
	  -Mdir='$(UNIT_DIR)/csrc' -o '$(UNIT_DIR)/simv' \
	  -l '$(UNIT_DIR)/compile.log' $(foreach src,$(SRCS_$(UNIT)),$(if $(filter /%,$(src)),$(src),$(ROOT)/$(src)))

.PHONY: vcs-unit-run
vcs-unit-run: vcs-unit-build
	@if [ '$(UNIT)' = npu_top ]; then \
	  $(PYTHON) test/npu_top/gen_mem.py --out_dir '$(UNIT_DIR)/case' \
	    --size $(SIZE) --ia_cache_blocks $(IA_CACHE_BLOCKS) --ps_frame_count $(PS_FRAME_COUNT) $(GEN_ARGS) \
	    $(if $(filter 1,$(PCR_ENGINE)),--pcr-engine --ps_pool_bytes $(PS_POOL_BYTES) $(if $(filter 1,$(PS_FORCE_RAW)),--ps-force-raw,),); \
	fi
	@cd '$(UNIT_DIR)' && $(PYTHON) '$(ROOT)/veri/sim/run_checked.py' \
	  --log '$(UNIT_DIR)/$(LOG_NAME).log' --pass '$(PASS_$(UNIT))' -- \
	  '$(ROOT)/veri/sim/run_simv_lxc.sh' '$(UNIT_DIR)/simv' \
	  $(if $(filter compute_core,$(UNIT)),+DATA_DIR=$(COMPUTE_DATA_DIR),) \
	  $(if $(filter npu_top,$(UNIT)),+INIT_MEM=$(UNIT_DIR)/case/init.mem +GOLDEN_MEM=$(UNIT_DIR)/case/golden.mem +CASE_MEM=$(UNIT_DIR)/case/config.mem $(if $(filter 1,$(PCR_ENGINE)),+ACC_I32_MEM=$(UNIT_DIR)/case/acc.mem,),) $(if $(filter 1,$(ASIC_SRAM)),+notimingcheck,) $(SIM_ARGS)

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
	  SOC_AXI_READ_OUTSTANDING=$(AXI_READ_OUTSTANDING) PCR_ENGINE=$(PCR_ENGINE) PS_POOL_BYTES=$(PS_POOL_BYTES) PS_FORCE_RAW=$(PS_FORCE_RAW) DUMPOPTS=0 SIM_ARGS='$(SIM_ARGS)'

vcs-axil:
	$(MAKE) vcs-uvm DUT_MODE=axil CASE=$(CASE)

vcs-soc:
	$(MAKE) vcs-uvm DUT_MODE=axi_soc CASE=$(if $(filter ai_mem_gen_smoke_test,$(CASE)),ai_axi_soc_c_test,$(CASE))

vcs-nmsis-abi:
	$(MAKE) vcs-soc SOC_APP=nmsis_abi SOC_CASE=axi_soc_case_nmsis_abi

vcs-tflm: prepare-vcs-python
	$(MAKE) -C veri/sim tflm_$(TFLM_APP)_run SOC_CPU_MEM_DP=$(SOC_CPU_MEM_DP) MMA_SIZE=$(SIZE) \
	  MMA_IA_CACHE_BLOCKS=$(IA_CACHE_BLOCKS) MMA_PS_FRAME_COUNT=$(PS_FRAME_COUNT) \
	  SOC_AXI_READ_OUTSTANDING=$(AXI_READ_OUTSTANDING) PCR_ENGINE=$(PCR_ENGINE) PS_POOL_BYTES=$(PS_POOL_BYTES) PS_FORCE_RAW=$(PS_FORCE_RAW) DUMPOPTS=0 SIM_ARGS='$(SIM_ARGS)'

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

.PHONY: vcs-pcr-soc
vcs-pcr-soc:
	$(MAKE) vcs-soc PCR_ENGINE=1 SIZE=16 SOC_APP=pcr_nmsis SOC_CASE=axi_soc_case_pcr_nmsis

PCR_BACKEND_OUTPUT ?= $(ROOT)/build/pcr_model
PCR_BACKEND_JOBS ?= 2
PCR_BACKEND_MEM_WORDS ?= 8388608
PCR_BACKEND_REFERENCE ?= 0
.PHONY: pcr-backend
pcr-backend: capacity-check
	@test '$(PCR_ENGINE)' = 1 || { echo 'pcr-backend requires PCR_ENGINE=1; run capacity-solve first or explicitly select a valid shared-array configuration.' >&2; exit 2; }
	$(PYTHON) '$(ROOT)/veri/pcr_model/build_measured_backend.py' \
	  --size '$(SIZE)' --cache '$(IA_CACHE_BLOCKS)' --ps '$(PS_FRAME_COUNT)' \
	  --ps-pool-bytes '$(PS_POOL_BYTES)' --im2col-cache-bytes '$(IM2COL_CACHE_BYTES)' \
	  --bus-width '$(NPU_AXI_DATA_WIDTH)' --shared-bank-bytes '$(SHARED_BANK_BYTES)' --shared-bank-count '$(SHARED_BANK_COUNT)' \
	  $(if $(filter 1,$(PS_FORCE_RAW)),--force-raw,) $(if $(filter 1,$(PCR_BACKEND_REFERENCE)),--reference,) \
	  --mem-words '$(PCR_BACKEND_MEM_WORDS)' --jobs '$(PCR_BACKEND_JOBS)' --output-root '$(abspath $(PCR_BACKEND_OUTPUT))'

# Conv validation uses the production RTL and C entry points. Existing VCS
# targets remain available; these targets require Verilator, GCC and Python.
# Conv runners select explicit hardware profiles. Their command-line options
# specify storage mode and capacity independently of menuconfig.
VERILATOR ?= verilator
YOSYS ?= yosys
CONV_BUILD_DIR ?= $(ROOT)/build/conv_verify
CONV_JOBS ?= 2
CONV_SIZES ?= 4 8 16
CONV_DMA_SIZES ?= 4 16
CONV_COSIM_SIZES ?= 4 16
CONV_RISCV_GCC ?= riscv64-unknown-elf-gcc
CONV_SOC_FLAGS ?=
CONV_RUNTIME_ROOT ?=
CONV_FULL_RUN_JOBS ?= 2
CONV_FULL_FLAGS ?=
CONV_CACHE_SETS ?= $(shell expr $(IM2COL_CACHE_BYTES) / 32)
CONV_CACHE_POLICY ?= 3
CONV_BASELINE ?=
CONV_BASELINE_REF ?=
CONV_TOOL_ENV = PATH="$(dir $(abspath $(VERILATOR))):$$PATH"

.PHONY: conv-verify conv-vectors conv-model conv-frontend conv-soc-ram conv-read-guard conv-page-split conv-reuse conv-driver conv-pcr-guard conv-dma conv-operand-drain conv-npu conv-input-audit conv-capacity conv-real-cnn conv-replacement conv-cosim conv-axil-protocol conv-disabled-config conv-narrow-kernel conv-gemm-regression conv-ram-inference conv-soc-perf

conv-verify:
	@set -e; for target in conv-model conv-frontend conv-soc-ram conv-read-guard conv-page-split conv-reuse conv-driver conv-pcr-guard conv-dma conv-npu conv-input-audit conv-real-cnn conv-replacement conv-cosim conv-axil-protocol conv-disabled-config conv-narrow-kernel conv-gemm-regression conv-ram-inference; do \
	  $(MAKE) --no-print-directory $$target; \
	done

conv-model:
	$(PYTHON) test/conv_frontend/tests/run_model_tests.py

conv-vectors:
	$(PYTHON) test/conv_models/generate_vectors.py --out '$(CONV_BUILD_DIR)/vectors'

conv-frontend:
	$(CONV_TOOL_ENV) $(PYTHON) test/conv_frontend/tools/run_rtl_suite.py

conv-soc-ram:
	$(CONV_TOOL_ENV) $(PYTHON) test/conv_soc_ram/run.py

conv-read-guard:
	$(CONV_TOOL_ENV) $(PYTHON) test/conv_guard/run.py

conv-page-split:
	$(PYTHON) test/linear_dma_4k/run.py --verilator '$(VERILATOR)' --out '$(CONV_BUILD_DIR)/linear_dma_4k'
	$(PYTHON) test/dma_page_guard/run.py --verilator '$(VERILATOR)' --out '$(CONV_BUILD_DIR)/dma_page_guard'

conv-reuse:
	$(CONV_TOOL_ENV) $(PYTHON) test/conv_reuse/run.py

conv-driver:
	$(PYTHON) test/conv_driver/run.py

conv-pcr-guard:
	$(PYTHON) test/conv_pcr_guard/run.py --out '$(CONV_BUILD_DIR)/pcr_guard'

conv-dma:
	$(PYTHON) test/conv_dma/run.py --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --sizes $(CONV_DMA_SIZES) --out '$(CONV_BUILD_DIR)/dma/matrix'
	$(PYTHON) test/conv_dma/run.py --legacy-only --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/dma/legacy'
	$(PYTHON) test/conv_dma/npu_cases.py --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --sizes $(CONV_DMA_SIZES) --out '$(CONV_BUILD_DIR)/dma/npu'
	$(MAKE) conv-operand-drain

conv-operand-drain:
	$(PYTHON) test/conv_dma/operand_drain/run.py --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/dma/operand_drain'

conv-npu:
	$(PYTHON) test/conv_npu/run.py --verilator '$(VERILATOR)' --sizes $(CONV_SIZES) --cache-sets $(CONV_CACHE_SETS) --cache-policy $(CONV_CACHE_POLICY) --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/npu'

conv-input-audit:
	$(PYTHON) test/conv_npu/run.py --reuse-audit --verilator '$(VERILATOR)' --sizes $(CONV_SIZES) --cache-sets $(CONV_CACHE_SETS) --cache-policy $(CONV_CACHE_POLICY) --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/input_audit'

conv-capacity:
	$(PYTHON) test/conv_npu/capacity.py --verilator '$(VERILATOR)' --cache-policy $(CONV_CACHE_POLICY) --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/capacity'

conv-real-cnn: conv-capacity
	$(PYTHON) test/conv_npu/model_shapes.py --tiling-policy driver-auto --cache-policy $(CONV_CACHE_POLICY) --binaries-root '$(CONV_BUILD_DIR)/capacity' --out '$(CONV_BUILD_DIR)/real_cnn' --bypass

conv-replacement:
	mkdir -p '$(CONV_BUILD_DIR)/replacement'
	$(PYTHON) test/conv_replacement/trace_model.py --out '$(CONV_BUILD_DIR)/replacement/traces'
	$(PYTHON) test/conv_replacement/geometry_oracle.py --out '$(CONV_BUILD_DIR)/replacement/geometry_validation.json'
	$(PYTHON) test/conv_replacement/predictor_test.py --verilator '$(VERILATOR)' --build '$(CONV_BUILD_DIR)/replacement/predictor_build' --out '$(CONV_BUILD_DIR)/replacement/predictor_validation.json'
	$(PYTHON) test/conv_replacement/run_cache_policy.py --verilator '$(VERILATOR)' --out '$(CONV_BUILD_DIR)/replacement/cache'
	$(PYTHON) test/conv_replacement/rtl_compare.py --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/replacement/npu/core_18' --profiles 2:512 2:1024 2:2048 1:1024 0:1024 2:4096
	$(PYTHON) test/conv_replacement/rtl_compare.py --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/replacement/npu/remaining_7' --profiles 2:1024 --skip-build --reuse-builds-root '$(CONV_BUILD_DIR)/replacement/npu/core_18' --layers mnist_cnn:sg0:op0 mnist_cnn:sg0:op2 justure_detect:sg0:op1 justure_detect:sg0:op10 person_detect:sg0:op6 person_detect:sg0:op10 mobilenet_v2:sg0:op32

conv-cosim:
	@set -e; for size in $(CONV_COSIM_SIZES); do \
	  $(PYTHON) test/conv_cosim/run.py --size $$size --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --build '$(CONV_BUILD_DIR)/cosim_build' --out '$(CONV_BUILD_DIR)/cosim_s'$$size; \
	done

conv-axil-protocol:
	$(PYTHON) test/conv_cosim/run.py --axil-protocol-only --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --build '$(CONV_BUILD_DIR)/cosim_build'

conv-disabled-config:
	$(PYTHON) test/conv_cosim/run.py --disabled-per-channel --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --build '$(CONV_BUILD_DIR)/cosim_build'
	$(PYTHON) test/conv_cosim/run.py --disabled-is --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --build '$(CONV_BUILD_DIR)/cosim_build'

conv-narrow-kernel:
	$(PYTHON) test/conv_cosim/run.py --narrow-kernel --verilator '$(VERILATOR)' --jobs $(CONV_JOBS) --build '$(CONV_BUILD_DIR)/cosim_build' --out '$(CONV_BUILD_DIR)/cosim_narrow_kernel'

# Requires the pinned PicoRV32 submodule and a bare-metal RISC-V C toolchain.
# Kept separate from host-only conv-verify; see test/conv_soc_perf/README.md.
conv-soc-perf:
	$(PYTHON) test/conv_soc_perf/run.py --verilator '$(VERILATOR)' --gcc '$(CONV_RISCV_GCC)' --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/soc_perf' $(CONV_SOC_FLAGS)

conv-gemm-regression:
	$(PYTHON) test/conv_regression/run.py --root '$(ROOT)' --verilator '$(VERILATOR)' --pcr --jobs $(CONV_JOBS) --out '$(CONV_BUILD_DIR)/gemm' $(if $(strip $(CONV_BASELINE)),--compare '$(CONV_BASELINE)',$(if $(strip $(CONV_BASELINE_REF)),--baseline-ref '$(CONV_BASELINE_REF)',))

conv-ram-inference:
	$(PYTHON) test/conv_ram_inference/run.py --yosys '$(YOSYS)'

# DW/pooling runners exercise the common vector engine.
# VECTOR_PE_COUNT is a compile-time arithmetic width; VECTOR_TILE sets staging capacity.
VECTOR_BUILD_DIR ?= $(ROOT)/build/vector_engine_verify
VECTOR_PE_COUNT ?= 8
VECTOR_TILE ?= 16
VECTOR_JOBS ?= 1
VECTOR_PE_SWEEP ?= 1 2 4 8 16
MODEL_BENCHMARK_OUT ?= $(ROOT)/build/model_benchmark
MODEL_BENCHMARK_PREPARED ?= $(MODEL_BENCHMARK_OUT)/prepared
MODEL_BENCHMARK_GCC ?= riscv-none-elf-gcc
MODEL_BENCHMARK_RUN_JOBS ?= 4
MODEL_BENCHMARK_ARGS ?=

.PHONY: vector-engine-test vector-engine-driver vector-engine-unit vector-engine-regs vector-engine-cosim vector-engine-disabled vector-engine-regression vector-engine-sweep vector-engine-area vector-engine-soc

vector-engine-test:
	@set -e; for target in vector-engine-driver vector-engine-unit vector-engine-regs vector-engine-cosim vector-engine-disabled vector-engine-regression; do \
	  $(MAKE) --no-print-directory $$target; \
	done

vector-engine-driver:
	$(PYTHON) test/vector_engine_driver/run.py --out '$(VECTOR_BUILD_DIR)/driver'

vector-engine-unit:
	$(PYTHON) test/vector_engine/run.py --verilator '$(VERILATOR)' --jobs $(VECTOR_JOBS) --tile $(VECTOR_TILE) --pes $(VECTOR_PE_COUNT) --out '$(VECTOR_BUILD_DIR)/unit'

vector-engine-regs:
	$(PYTHON) test/vector_engine_regs/run.py --verilator '$(VERILATOR)' --out '$(VECTOR_BUILD_DIR)/registers'

vector-engine-cosim:
	$(PYTHON) test/vector_engine_cosim/run.py --verilator '$(VERILATOR)' --jobs $(VECTOR_JOBS) --size $(VECTOR_TILE) --pe-count $(VECTOR_PE_COUNT) --out '$(VECTOR_BUILD_DIR)/cosim'

vector-engine-disabled:
	$(PYTHON) test/vector_engine_cosim/run.py --verilator '$(VERILATOR)' --jobs $(VECTOR_JOBS) --size $(VECTOR_TILE) --pe-count $(VECTOR_PE_COUNT) --disabled --out '$(VECTOR_BUILD_DIR)/disabled'

vector-engine-regression:
	$(PYTHON) test/conv_dma/run.py --verilator '$(VERILATOR)' --jobs $(VECTOR_JOBS) --legacy-only --out '$(VECTOR_BUILD_DIR)/regression/legacy'
	$(PYTHON) test/conv_dma/run.py --verilator '$(VERILATOR)' --jobs $(VECTOR_JOBS) --sizes 4 16 --out '$(VECTOR_BUILD_DIR)/regression/matrix'
	$(PYTHON) test/conv_npu/run.py --verilator '$(VERILATOR)' --jobs $(VECTOR_JOBS) --sizes 4 --out '$(VECTOR_BUILD_DIR)/regression/conv'

vector-engine-sweep:
	$(PYTHON) test/vector_engine/run.py --verilator '$(VERILATOR)' --jobs $(VECTOR_JOBS) --tile $(VECTOR_TILE) --pes $(VECTOR_PE_SWEEP) --perf --out '$(VECTOR_BUILD_DIR)/pe_sweep'

vector-engine-area:
	$(PYTHON) test/vector_engine/synth_pe.py --yosys '$(YOSYS)' --counts $(VECTOR_PE_SWEEP) --out '$(VECTOR_BUILD_DIR)/pe_area'

vector-engine-soc:
	$(PYTHON) test/model_benchmark/run_suite.py --out '$(MODEL_BENCHMARK_OUT)' \
	  --prepared '$(MODEL_BENCHMARK_PREPARED)' --gcc '$(MODEL_BENCHMARK_GCC)' \
	  --verilator '$(VERILATOR)' --jobs $(VECTOR_JOBS) \
	  --run-jobs $(MODEL_BENCHMARK_RUN_JOBS) $(MODEL_BENCHMARK_ARGS)
PS_VERIFY_DIR ?= $(ROOT)/build/ps_frame_verify
PS_SOC_DIR ?= $(ROOT)/build/ps_compression/soc
PS_SOC_FLAGS ?=
.PHONY: ps-stream-verify ps-compression-soc shared-memory-test shared-memory-structure dip-array-test
dip-array-test:
	$(PYTHON) test/dip_array/run.py --verilator '$(VERILATOR)' --jobs '$(CONV_JOBS)' --out '$(PS_VERIFY_DIR)/dip_array'
	$(PYTHON) test/dip_weights/run.py --verilator '$(VERILATOR)' --out '$(PS_VERIFY_DIR)/dip_weights'

ps-stream-verify:
	$(PYTHON) test/ps_compression/run_stream_rtl.py --verilator '$(VERILATOR)' --target codec --out '$(PS_VERIFY_DIR)/codec'
	$(PYTHON) test/ps_compression/run_frame_store.py --verilator '$(VERILATOR)' --out '$(PS_VERIFY_DIR)/store'
	$(PYTHON) test/ps_compression/run_frame_store.py --verilator '$(VERILATOR)' --force-raw --out '$(PS_VERIFY_DIR)/store_raw'
	$(PYTHON) test/ps_compression/run_window_scheduler.py --verilator '$(VERILATOR)' --out '$(PS_VERIFY_DIR)/scheduler'
	$(PYTHON) test/run_cpp_rtl.py dma_abort --verilator '$(VERILATOR)' --out '$(PS_VERIFY_DIR)/dma_abort'

ps-compression-soc:
	$(PYTHON) test/ps_compression/run_soc.py --verilator '$(VERILATOR)' --gcc '$(MODEL_BENCHMARK_GCC)' --prepared '$(MODEL_BENCHMARK_PREPARED)' --out '$(PS_SOC_DIR)' --pool-bytes '$(PS_POOL_BYTES)' --jobs '$(CONV_JOBS)' $(PS_SOC_FLAGS)

shared-memory-test:
	$(PYTHON) test/ia_shared/run.py --verilator '$(VERILATOR)' --out '$(PS_VERIFY_DIR)/ia_shared'
	$(PYTHON) test/shared_ia_ps/run.py --verilator '$(VERILATOR)' --out '$(PS_VERIFY_DIR)/shared_store'
	$(PYTHON) test/shared_ia_ps/run.py --verilator '$(VERILATOR)' --force-raw --out '$(PS_VERIFY_DIR)/shared_store_raw'
	$(PYTHON) test/capacity/run_shared_bank_registers.py --verilator '$(VERILATOR)' --out '$(PS_VERIFY_DIR)/shared_registers'
	$(PYTHON) test/ps_compression/run_shared_npu.py --verilator '$(VERILATOR)' --jobs '$(CONV_JOBS)' --out '$(PS_VERIFY_DIR)/shared_npu'
	$(PYTHON) test/ps_compression/run_literal_bound_npu.py --sim '$(PS_VERIFY_DIR)/shared_npu/sim' --out '$(PS_VERIFY_DIR)/literal_bound_npu'

shared-memory-structure:
	$(PYTHON) test/shared_ia_ps/check_structure.py --yosys '$(YOSYS)' --out '$(PS_VERIFY_DIR)/shared_structure'

.PHONY: check-rtl-observers
check-rtl-observers:
	python3 test/monitors/check_rtl.py

OPEN_FPGA_SYNTH_DIR ?= $(ROOT)/build/open_fpga_synth
OPEN_FPGA_SYNTH_CASES ?= array shared_ram vector_writeback conv_cache_ram vector_engine
.PHONY: open-fpga-synth
open-fpga-synth:
	$(PYTHON) scripts/fpga/open_fpga_synth.py --out $(OPEN_FPGA_SYNTH_DIR) --cases $(OPEN_FPGA_SYNTH_CASES)
