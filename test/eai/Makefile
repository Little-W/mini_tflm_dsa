PROJECT_ROOT := ../..
TB_ROOT := ./
SUB_MODULES_DIR := ./sub_module
TB := tb_e203_nice.sv
VEXE := sim_e203_nice
# 指定 include 路径，确保 `*.svh` 能被找到
INCLUDES := -I$(PROJECT_ROOT)/inc -I. -I$(PROJECT_ROOT)/rtl -I$(SUB_MODULES_DIR)

# Suppress non-critical Verilator warnings to allow build
VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	-Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-UNDRIVEN -Wno-PINMISSING \
	-Wno-STMTDLY -Wno-DECLFILENAME -Wno-CASEINCOMPLETE -Wno-EOFNEWLINE \
	-Wno-UNPACKED -Wno-TIMESCALEMOD

# RTL 源文件
RTL_SRCS := \
	$(TB_ROOT)/nice_core_top/e203_subsys_nice_core.sv \
	$(TB_ROOT)/nice_if.sv \
	$(SUB_MODULES_DIR)/decode_dispatch.v \
	$(SUB_MODULES_DIR)/dummy_mma_top.v \
	$(SUB_MODULES_DIR)/icb_unalign_bridge.sv \
	$(SUB_MODULES_DIR)/csr_unit.v \
	$(SUB_MODULES_DIR)/wbu.v \
	$(SUB_MODULES_DIR)/inst_tracker.v

# 测试任务头文件（已合并 loader 到 test_compute_tasks.svh）
TEST_TASKS := 

SRCS := \
	$(TB) \
	$(RTL_SRCS)

all: run

build: $(TB) $(RTL_SRCS)
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_e203_nice

run: build
	./obj_dir/$(VEXE)

wave: run
	gtkwave wave.vcd

clean:
	rm -rf $(VEXE) *.vcd obj_dir

.PHONY: all build run clean wave
