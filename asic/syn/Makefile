SHELL := /bin/bash
export

DC_SHELL ?= dc_shell

DESIGN_TOP_NAME ?= npu_top
TARGET_FREQ_MHZ ?= 400
MAX_CORES ?= 1
COMPILE_MODE ?= ultra

NPU_WEIGHT_WIDTH ?= 8
NPU_DATA_WIDTH ?= 8
NPU_SIZE ?= 4
NPU_BUS_WIDTH ?= 32
NPU_REG_WIDTH ?= 32
NPU_ADDR_WIDTH ?= 19
NPU_IA_CACHE_BLOCKS ?= 32
NPU_PS_FRAME_COUNT ?= 4
NPU_AXI_READ_OUTSTANDING ?= 4
NPU_AXI_WRITE_OUTSTANDING ?= $(NPU_AXI_READ_OUTSTANDING)
NPU_ENABLE_IS_MODE ?= 0
NPU_ENABLE_PER_CHANNEL ?= 0

DATE := $(shell date +%y%m%d_%H%M%S)
PROJ := tflm_ai_dsa
PROJ_PATH := $(CURDIR)
ASIC_ROOT := $(abspath $(PROJ_PATH)/..)
PROJ_ROOT := $(abspath $(ASIC_ROOT)/..)
PRJ_HOME := $(ASIC_ROOT)
RTL_ROOT := $(PROJ_ROOT)/rtl
INC_ROOT := $(PROJ_ROOT)/inc
PROJ_TEMP ?= $(PROJ_PATH)/output/$(DATE)_$(DESIGN_TOP_NAME)_$(TARGET_FREQ_MHZ)m

DESIGN := $(DESIGN_TOP_NAME)
DESIGN_TOP := $(DESIGN)
DESIGN_FILELIST ?= $(ASIC_ROOT)/filelist/$(DESIGN_TOP_NAME).f

DESIGN_SCR := $(PROJ_PATH)/scr/dc.tcl
DESIGN_DEBUG_SCR := $(PROJ_PATH)/scr/dc_debug.tcl
DESIGN_SYN_SDC := $(ASIC_ROOT)/sdc/$(DESIGN_TOP_NAME)_400m.sdc

PDK_ROOT ?= /home/yusen/opt/xinyuan/xinyuan-syn/syn/lib/FreePDK45
STD_DB_PATH1 := $(PDK_ROOT)/osu_soc/lib/files
STD_DB_PATH ?= $(STD_DB_PATH1)
STD_DB_LIST ?= gscl45nm.db
SYNC_DB_PATH ?= $(STD_DB_PATH)
SYNC_DB_LIST ?= $(STD_DB_LIST)
SYN_STD_LIB_NAME ?= gscl45nm
SYN_OPER_CONDITION ?= typical
SYN_CONER ?=
PROCE ?= gscl45nm

DW_DB_PATH ?=
MEM_DB_PATH ?=
MEM_DB_LIST ?=
IO_DB_PATH ?=
IO_DB_LIST ?=
LPK_DB_PATH ?=
LPK_DB_LIST ?=
AFE_DB_PATH ?=
AFE_DB_LIST ?=

INTERRUPT ?= 0
DCT ?= 0
postCTS ?= 0
clockGate ?= 0
enableDFT ?= 0

DESIGN_PARAMETERS := WEIGHT_WIDTH=$(NPU_WEIGHT_WIDTH),DATA_WIDTH=$(NPU_DATA_WIDTH),SIZE=$(NPU_SIZE),BUS_WIDTH=$(NPU_BUS_WIDTH),REG_WIDTH=$(NPU_REG_WIDTH),ADDR_WIDTH=$(NPU_ADDR_WIDTH),IA_CACHE_BLOCKS=$(NPU_IA_CACHE_BLOCKS),PS_FRAME_COUNT=$(NPU_PS_FRAME_COUNT),AXI_READ_OUTSTANDING=$(NPU_AXI_READ_OUTSTANDING),AXI_WRITE_OUTSTANDING=$(NPU_AXI_WRITE_OUTSTANDING),ENABLE_IS_MODE=$(NPU_ENABLE_IS_MODE),ENABLE_PER_CHANNEL=$(NPU_ENABLE_PER_CHANNEL)

.PHONY: env syn debug summary clean

env:
	@env | sort

syn:
	mkdir -p "$(PROJ_TEMP)"
	$(DC_SHELL) -f "$(DESIGN_SCR)" 2>&1 | tee syn.log; status=$${PIPESTATUS[0]}; exit $$status

debug:
	mkdir -p "$(PROJ_TEMP)"
	$(DC_SHELL) -f "$(DESIGN_DEBUG_SCR)"

summary:
	@latest=$$(ls -td output/* 2>/dev/null | head -1); \
	test -n "$$latest" || { echo "No synthesis output found"; exit 1; }; \
	summary="$$latest/$(DESIGN_TOP_NAME)_summary.rpt"; \
	test -f "$$summary" || { echo "Missing $$summary"; exit 1; }; \
	cat "$$summary"

clean:
	rm -rf WORK alib-52 output *.log *.svf command.log filenames.log
