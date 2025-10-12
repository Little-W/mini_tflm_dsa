PROJECT_ROOT := ../..
SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules
BASIC_MODULES_DIR := $(PROJECT_ROOT)/basic
TB := tb_compute_core.sv
VEXE := sim_compute_core
# INCLUDES := -I $(PROJECT_ROOT)/inc

# Suppress non-critical Verilator warnings to allow build
VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL -Wno-UNUSED -Wno-UNUSEDGENVAR

SRCS := \
	$(TB) \
	tb_compute_core_if.sv \
	$(SUB_MODULES_DIR)/compute_core.sv \
	$(SUB_MODULES_DIR)/ws_systolic_array.sv \
	$(BASIC_MODULES_DIR)/ws_systolic_cell.sv \
	$(BASIC_MODULES_DIR)/shift_accumulator.sv \
	$(SUB_MODULES_DIR)/accumulator_array.sv \
	$(SUB_MODULES_DIR)/data_setup.sv

all: run

gen: gen_mats.py
	python3 gen_mats.py

build: gen $(TB)
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE)

run: build
	./obj_dir/$(VEXE)

wave: run
	# 波形文件为wave.vcd（在当前目录下），可用gtkwave等工具查看

clean:
	rm -rf $(VEXE) *.vcd *.hex *.txt obj_dir tiles
.PHONY: all gen build run clean
