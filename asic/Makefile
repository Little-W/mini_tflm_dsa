SHELL := /bin/bash
.DEFAULT_GOAL := sram-test
include $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../config/npu_config.mk
ROOT := $(abspath ..)
SRAM_ROOT ?= /media/6/IC/lib/SRAM_Lib_2025
IVERILOG ?= iverilog
VVP ?= vvp
.PHONY: sram-test npu-test pcr-test syn summary
sram-test:
	mkdir -p "$(ROOT)/build/asic/tests"
	$(IVERILOG) -g2012 -s tb_sram_1r1w -o "$(ROOT)/build/asic/tests/sram" \
	  tests/tb_sram_1r1w.sv rtl/smic40_sram_1r1w.sv \
	  "$(SRAM_ROOT)/RAMTP128X16/verilog/RAMTP128X16.v" \
	  "$(SRAM_ROOT)/RAMTP1024X16/verilog/RAMTP1024X16.v"
	$(VVP) "$(ROOT)/build/asic/tests/sram"
	$(IVERILOG) -g2012 -DASIC_SRAM -s tb_ia_buffer -o "$(ROOT)/build/asic/tests/ia_buffer" \
	  tests/tb_sram_1r1w.sv rtl/smic40_sram_1r1w.sv "$(ROOT)/rtl/npu/loaders/ia_buffer_wrapper.sv" \
	  "$(SRAM_ROOT)/RAMTP128X16/verilog/RAMTP128X16.v" \
	  "$(SRAM_ROOT)/RAMTP1024X16/verilog/RAMTP1024X16.v"
	$(VVP) "$(ROOT)/build/asic/tests/ia_buffer"
npu-test:
	$(MAKE) -C "$(ROOT)" vcs-top ASIC_SRAM=1 SRAM_ROOT="$(SRAM_ROOT)"
pcr-test:
	$(MAKE) -C "$(ROOT)" vcs-top ASIC_SRAM=1 SRAM_ROOT="$(SRAM_ROOT)" PCR_ENGINE=1 SIZE=16 GEN_ARGS='--K 32 --N 32 --M 32 --lhs_dtype 1 --no_bias --lhs_zp 0 --rhs_zp 0 --tight_strides'
syn summary:
	$(MAKE) -C synthesis $@
