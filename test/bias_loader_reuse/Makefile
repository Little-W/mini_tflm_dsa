VERILATOR ?= verilator
JOBS ?= 2
ROOT := ../..
BUILD := $(ROOT)/build/bias_loader_reuse
SOURCES := tb_bias_loader_reuse.sv $(ROOT)/rtl/npu/loaders/bias_loader.sv \
           $(ROOT)/rtl/npu/loaders/bias_loader_ctrl.sv $(ROOT)/rtl/npu/loaders/bias_loader_buffer.sv \
           $(ROOT)/rtl/common/regfile.v $(ROOT)/rtl/common/parallel_prefix_add.sv \
           $(ROOT)/rtl/common/parallel_unsigned_compare.sv $(ROOT)/rtl/common/add_equal.sv

.PHONY: run
run:
	$(VERILATOR) --binary --timing --assert -Wno-fatal --top-module tb_bias_loader_reuse \
		--output-groups 0 -CFLAGS "-std=c++20 -O1" \
		-MAKEFLAGS "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E" \
		-j $(JOBS) --Mdir $(BUILD) $(SOURCES)
	$(BUILD)/Vtb_bias_loader_reuse
