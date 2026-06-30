PROJECT_ROOT := ../..
TB_ROOT := ./
SUB_MODULES_DIR := ./sub_module
MMA_SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules
TB := tb_e203_nice.sv
VEXE := sim_e203_nice
# 指定 include 路径，确保 `*.svh` 能被找到
INCLUDES := -I$(PROJECT_ROOT)/inc -I. -I$(SUB_MODULES_DIR)

# Suppress non-critical Verilator warnings to allow build
VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	-Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-UNDRIVEN -Wno-PINMISSING \
	-Wno-STMTDLY -Wno-DECLFILENAME -Wno-CASEINCOMPLETE -Wno-EOFNEWLINE \
	-Wno-UNPACKED -Wno-TIMESCALEMOD -Wno-PINCONNECTEMPTY -Wno-WIDTHTRUNC \
	-Wno-ASCRANGE -Wno-INITIALDLY -Wno-BLKSEQ -Wno-MULTIDRIVEN \
	-Wno-SYNCASYNCNET

# RTL 源文件
RTL_SRCS := \
	$(TB_ROOT)/nice_core_top/e203_subsys_nice_core.sv \
	$(TB_ROOT)/nice_if.sv \
	$(SUB_MODULES_DIR)/decode_dispatch.v \
	$(SUB_MODULES_DIR)/icb_unalign_bridge.sv \
	$(SUB_MODULES_DIR)/csr_unit.v \
	$(SUB_MODULES_DIR)/wbu.v \
	$(SUB_MODULES_DIR)/inst_tracker.v \
	$(PROJECT_ROOT)/test/dep_modules/ddr_axi_mem_model.sv \
	$(PROJECT_ROOT)/top/mma_top.sv \
	$(shell find $(MMA_SUB_MODULES_DIR) -maxdepth 1 -type f \( -name "*.sv" -o -name "*.v" \)) \
	$(PROJECT_ROOT)/basic/pseudo_dual_port_ram.v \
	$(PROJECT_ROOT)/basic/ws_systolic_cell.sv \
	$(PROJECT_ROOT)/basic/shift_accumulator.sv

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
