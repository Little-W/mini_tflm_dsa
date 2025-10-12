PROJECT_ROOT := ../..
SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules
TB := tb_mma_controller.sv
VEXE := sim_mma_controller
# 指定 include 路径，确保 `*.svh` 能被找到
INCLUDES := -I$(PROJECT_ROOT)/inc -I.

# Suppress non-critical Verilator warnings to allow build
VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	-Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-UNDRIVEN -Wno-PINMISSING \
	-Wno-STMTDLY -Wno-DECLFILENAME -Wno-CASEINCOMPLETE -Wno-EOFNEWLINE

# 测试任务头文件（已合并 loader 到 test_compute_tasks.svh）
TEST_TASKS := \
	test_monitor_tasks.svh \
	test_compute_tasks.svh \
	test_arbiter_tasks.svh

SRCS := \
	mma_controller_if.sv \
	$(TB) \
	$(SUB_MODULES_DIR)/mma_controller.sv \
	$(SUB_MODULES_DIR)/icb_arbiter.sv

all: run

build: $(TB) $(TEST_TASKS)
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE)

run: build
	./obj_dir/$(VEXE)

wave: run
	gtkwave wave.vcd

clean:
	rm -rf $(VEXE) *.vcd obj_dir

.PHONY: all build run clean wave
.PHONY: all build run clean wave
