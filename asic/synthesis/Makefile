SHELL := /bin/bash
.DEFAULT_GOAL := libs
include $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../../config/npu_config.mk
export
DC_SHELL ?= dc_shell
LC_SHELL ?= lc_shell
ASIC_ROOT := $(abspath ..)
PROJ_ROOT := $(abspath ../..)
PROJ_PATH := $(CURDIR)
RTL_ROOT := $(PROJ_ROOT)/rtl
INC_ROOT := $(PROJ_ROOT)/include
BUILD_ROOT ?= $(PROJ_ROOT)/build/asic
PROJ_TEMP ?= $(BUILD_ROOT)/npu_top_axi$(NPU_BUS_WIDTH)_bank$(SHARED_BANK_BYTES)x$(SHARED_BANK_COUNT)_im2col$(IM2COL_CACHE_BYTES)_iac$(IA_COMPACT_ENABLE)_cll$(CONV_LOW_LATENCY)$(if $(filter 1,$(PCR_ENGINE)),_pcr_b$(PS_POOL_BYTES)_f$(PS_FORCE_RAW),)
STD_ROOT ?= /media/6/IC/lib/SMIC40_2025
SRAM_ROOT ?= /media/6/IC/lib/SRAM_Lib_2025
STD_DB_PATH ?= $(STD_ROOT)/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v
STD_DB_LIST ?= scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db
MEM_DB_PATH ?= $(PROJ_TEMP)/libs
MEM_DB_LIST ?= RAMTP128X16_tt_1p10v_1p10v_25c.db RAMTP1024X16_tt_1p10v_1p10v_25c.db
SYN_STD_LIB_NAME ?= scc40nll_vhsc40_rvt_tt_v1p1_25c_basic
SYN_OPER_CONDITION ?= tt_v1p1_25c
DESIGN_TOP_NAME ?= npu_top
DESIGN_TOP := $(DESIGN_TOP_NAME)
DESIGN := $(DESIGN_TOP_NAME)
DESIGN_INPUT_FILELIST := $(PROJ_PATH)/filelists/$(DESIGN_TOP_NAME).f
DESIGN_FILELIST := $(PROJ_TEMP)/sources/sources.f
DESIGN_SYN_SDC := $(PROJ_PATH)/constraints/npu_top.sdc
TARGET_FREQ_MHZ ?= 50
MAX_CORES ?= 1
COMPILE_MODE ?= quick
PCR_ENGINE ?= 0
PS_POOL_BYTES ?= 12288
DESIGN_RTL_DEFINES := $(if $(filter 1,$(PCR_ENGINE)),+define+GEMPACT_PS_COMPRESS+GEMMORA_PS_POOL_BYTES=$(PS_POOL_BYTES)$(if $(filter 1,$(PS_FORCE_RAW)),+GEMMORA_PS_FORCE_RAW,),)
DESIGN_TARGET_FREQ_MHZ := $(TARGET_FREQ_MHZ)
DESIGN_MAX_CORES := $(MAX_CORES)
DESIGN_COMPILE_MODE := $(COMPILE_MODE)
DESIGN_ELAB_ONLY ?= 0
NPU_WEIGHT_WIDTH ?= 16
NPU_DATA_WIDTH ?= 16
NPU_SIZE ?= 4
NPU_BUS_WIDTH ?= $(NPU_AXI_DATA_WIDTH)
NPU_REG_WIDTH ?= 32
NPU_ADDR_WIDTH ?= 19
NPU_IA_CACHE_BLOCKS ?= 32
NPU_PS_FRAME_COUNT ?= 4
NPU_AXI_READ_OUTSTANDING ?= 4
NPU_AXI_WRITE_OUTSTANDING ?= $(NPU_AXI_READ_OUTSTANDING)
NPU_ENABLE_IS_MODE ?= 1
NPU_ENABLE_PER_CHANNEL ?= 1
NPU_CAPACITY_SIZE = $(NPU_SIZE)
NPU_CAPACITY_CACHE = $(NPU_IA_CACHE_BLOCKS)
NPU_CAPACITY_FRAMES = $(NPU_PS_FRAME_COUNT)
NPU_CAPACITY_READ_OUTSTANDING = $(NPU_AXI_READ_OUTSTANDING)
NPU_CAPACITY_AXI_DATA_WIDTH = $(NPU_BUS_WIDTH)
DESIGN_PARAMETERS := WEIGHT_WIDTH=$(NPU_WEIGHT_WIDTH),DATA_WIDTH=$(NPU_DATA_WIDTH),SIZE=$(NPU_SIZE),BUS_WIDTH=$(NPU_BUS_WIDTH),REG_WIDTH=$(NPU_REG_WIDTH),ADDR_WIDTH=$(NPU_ADDR_WIDTH),SHARED_BANK_BYTES=$(SHARED_BANK_BYTES),SHARED_BANK_COUNT=$(SHARED_BANK_COUNT),IA_CACHE_BLOCKS=$(NPU_IA_CACHE_BLOCKS),IA_COMPACT_ENABLE=$(IA_COMPACT_ENABLE),IM2COL_CACHE_BYTES=$(IM2COL_CACHE_BYTES),CONV_LOW_LATENCY=$(CONV_LOW_LATENCY),PS_FRAME_COUNT=$(NPU_PS_FRAME_COUNT),AXI_READ_OUTSTANDING=$(NPU_AXI_READ_OUTSTANDING),AXI_WRITE_OUTSTANDING=$(NPU_AXI_WRITE_OUTSTANDING),ENABLE_IS_MODE=$(NPU_ENABLE_IS_MODE),ENABLE_PER_CHANNEL=$(NPU_ENABLE_PER_CHANNEL)
.PHONY: libs syn elaborate summary prepare-rtl
prepare-rtl: capacity-check $(NPU_CONFIG)
	python3 "$(PROJ_ROOT)/scripts/asic/prepare_dc_sources.py" --root "$(PROJ_ROOT)" \
	  --filelist "$(DESIGN_INPUT_FILELIST)" --out "$(PROJ_TEMP)/sources"
libs: capacity-check
	@mkdir -p "$(MEM_DB_PATH)"
	rm -f "$(MEM_DB_PATH)/library_compiler.log" $(foreach f,$(MEM_DB_LIST),"$(MEM_DB_PATH)/$(f)")
	@printf 'set sram_root {%s}\n' "$(SRAM_ROOT)" > "$(MEM_DB_PATH)/library_config.tcl"
	cd "$(MEM_DB_PATH)" && $(LC_SHELL) -f "$(PROJ_PATH)/scripts/compile_sram_libs.tcl" > library_compiler.log 2>&1
	@for lib in $(MEM_DB_LIST); do test -s "$(MEM_DB_PATH)/$$lib" || { echo "SRAM library conversion failed: $$lib" >&2; exit 1; }; done
syn: capacity-check libs prepare-rtl $(NPU_CONFIG)
	@mkdir -p "$(PROJ_TEMP)"
	@rm -f "$(PROJ_TEMP)/$(DESIGN_TOP_NAME)_summary.rpt"
	cd "$(PROJ_TEMP)" && $(DC_SHELL) -f "$(PROJ_PATH)/scripts/dc.tcl" 2>&1 | tee synthesis.log; status=$${PIPESTATUS[0]}; test $$status -eq 0 && test -s "$(PROJ_TEMP)/$(DESIGN_TOP_NAME)_summary.rpt"
elaborate: DESIGN_ELAB_ONLY = 1
elaborate: capacity-check libs prepare-rtl $(NPU_CONFIG)
	@mkdir -p "$(PROJ_TEMP)"
	@rm -f "$(PROJ_TEMP)/$(DESIGN_TOP_NAME)_elab_references.rpt"
	cd "$(PROJ_TEMP)" && $(DC_SHELL) -f "$(PROJ_PATH)/scripts/dc.tcl" 2>&1 | tee elaborate.log; status=$${PIPESTATUS[0]}; test $$status -eq 0 && test -s "$(PROJ_TEMP)/$(DESIGN_TOP_NAME)_elab_references.rpt"
summary:
	@cat "$(PROJ_TEMP)/$(DESIGN_TOP_NAME)_summary.rpt"
