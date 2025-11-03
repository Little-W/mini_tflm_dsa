PROJECT_ROOT := ../..
SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules

# 顶层tb与可执行名
TB := tb_mma_top.sv
VEXE := sim_mma_top

# 头文件路径
INCLUDES := -I$(PROJECT_ROOT)/inc -I.

# Verilator参数
VERILATOR_FLAGS := -sv -Wall --trace --timing --top-module tb_mma_top \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	-Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-UNDRIVEN -Wno-PINMISSING \
	-Wno-STMTDLY -Wno-DECLFILENAME -Wno-CASEINCOMPLETE -Wno-EOFNEWLINE

# 测试任务头文件
TEST_TASKS :=

# 工程源：tb、bridge、mma_top 以及 sub_modules
MMA_TOP_SRC ?= $(PROJECT_ROOT)/rtl/mma_top.sv
SUB_SV := $(shell find $(SUB_MODULES_DIR) -maxdepth 5 -type f \( -name "*.sv" -o -name "*.v" \))

# 添加新的 interface 文件
SRCS := $(TB) icb_ext_if.sv mma_top_if.sv icb_ext_flat_adapter.sv \
        $(PROJECT_ROOT)/test/dep_modules/top_sram_icb_bridge.sv \
        $(MMA_TOP_SRC) $(SUB_SV)

# 输出目录与mem文件
OUT_DIR := out
MEM_INIT := $(OUT_DIR)/init.mem
MEM_GOLDEN := $(OUT_DIR)/golden.mem

all: run

$(OUT_DIR):
	mkdir -p $(OUT_DIR)

gen: $(OUT_DIR)
	python3 gen_mem.py --out_dir $(OUT_DIR)

build: $(TB) $(TEST_TASKS)
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE)

run: build gen
	./obj_dir/$(VEXE) +INIT_MEM=$(MEM_INIT) +GOLDEN_MEM=$(MEM_GOLDEN)

wave: run
	gtkwave wave.vcd

clean:
	rm -rf $(VEXE) *.vcd obj_dir $(OUT_DIR)

.PHONY: all build run clean wave gen
