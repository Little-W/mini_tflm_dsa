VERILATOR ?= verilator
JOBS ?= 2
ROOT := ../..
BUILD := $(ROOT)/build/bias_loader_reuse
SOURCES := tb_bias_loader_reuse.sv $(ROOT)/rtl/npu/loaders/bias_loader.sv \
           $(ROOT)/rtl/npu/loaders/bias_loader_ctrl.sv $(ROOT)/rtl/npu/loaders/bias_loader_buffer.sv

.PHONY: run
run:
	$(VERILATOR) --binary --timing --assert -Wno-fatal --top-module tb_bias_loader_reuse -j $(JOBS) --Mdir $(BUILD) $(SOURCES)
	$(BUILD)/Vtb_bias_loader_reuse
