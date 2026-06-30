PROJECT_ROOT := ../..
SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules

# 顶层tb与可执行名
TB := tb_mma_top.sv
VEXE := sim_mma_top
SIZE ?= 4
IA_CACHE_BLOCKS ?= 4
PS_FRAME_COUNT ?= 8
BUILD_ROOT ?= obj_dir
BUILD_DIR := $(BUILD_ROOT)/s$(SIZE)_c$(IA_CACHE_BLOCKS)_ps$(PS_FRAME_COUNT)
SIM_BIN := $(BUILD_DIR)/$(VEXE)
VERILATOR_OPT_FLAGS ?= -O3 -CFLAGS -O3 -LDFLAGS -O3

# Verilator参数
VERILATOR_FLAGS := -sv -Wall --trace --timing --top-module tb_mma_top \
	$(VERILATOR_OPT_FLAGS) \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	-Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-UNDRIVEN -Wno-PINMISSING \
	-Wno-STMTDLY -Wno-DECLFILENAME -Wno-CASEINCOMPLETE -Wno-EOFNEWLINE \
	-Wno-PROCASSINIT -Wno-SYNCASYNCNET -Wno-COMBDLY -Wno-PINCONNECTEMPTY \
	-Wno-WIDTHTRUNC -Wno-ASCRANGE -Wno-INITIALDLY -Wno-BLKSEQ -Wno-MULTIDRIVEN \
	-DTB_SIZE=$(SIZE) -DTB_IA_CACHE_BLOCKS=$(IA_CACHE_BLOCKS) -DTB_PS_FRAME_COUNT=$(PS_FRAME_COUNT)

# 测试任务头文件
TEST_TASKS :=

# 工程源：tb、bridge、mma_top 以及 sub_modules
MMA_TOP_SRC ?= $(PROJECT_ROOT)/top/mma_top.sv
SUB_SV := $(shell find $(SUB_MODULES_DIR) -maxdepth 5 -type f \( -name "*.sv" -o -name "*.v" \))
DEP_SV := $(shell find $(PROJECT_ROOT)/test/dep_modules -maxdepth 1 -type f \( -name "*.sv" -o -name "*.v" \))
BASIC_SV := \
        $(PROJECT_ROOT)/basic/pseudo_dual_port_ram.v \
        $(PROJECT_ROOT)/basic/ws_systolic_cell.sv \
        $(PROJECT_ROOT)/basic/shift_accumulator.sv

# 添加新的 interface 文件
SRCS := $(TB) tb_e203_sirv_stubs.v \
        $(DEP_SV) $(MMA_TOP_SRC) $(SUB_SV) $(BASIC_SV)

# 输出目录与mem文件
OUT_DIR := out
MEM_INIT := $(OUT_DIR)/init.mem
MEM_GOLDEN := $(OUT_DIR)/golden.mem
MEM_CASE := $(OUT_DIR)/config.mem
GEN_ARGS ?=
RANDOM_GEN_ARGS ?= --random --random_quant --lhs_dtype 0 --min_dim 1 --max_dim 32 --ps_frame_count 8
COUNT ?= 20
SEED ?= 1000
SIZES ?= 4 8 16
CACHE_BLOCKS_LIST ?= 2 4 8
SIM_ARGS ?= +DDR_RAND_LAT=1 +DDR_CMD_MAX_LAT=3 +DDR_W_MAX_LAT=2 +DDR_RSP_MAX_LAT=8

# 头文件路径
INCLUDES = -I$(PROJECT_ROOT)/inc -I. -I$(OUT_DIR)

all: run

$(OUT_DIR):
	mkdir -p $(OUT_DIR)

gen: $(OUT_DIR)
	python3 gen_mem.py --out_dir $(OUT_DIR) --size $(SIZE) --ia_cache_blocks $(IA_CACHE_BLOCKS) $(GEN_ARGS)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(SIM_BIN): $(SRCS) $(TEST_TASKS) Makefile | $(BUILD_DIR)
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --Mdir $(BUILD_DIR) --binary $(SRCS) -o $(VEXE)

build_only: $(SIM_BIN)

build: gen build_only

run_only:
	$(SIM_BIN) +INIT_MEM=$(MEM_INIT) +GOLDEN_MEM=$(MEM_GOLDEN) +CASE_MEM=$(MEM_CASE) $(SIM_ARGS)

run: build run_only

run_random: $(OUT_DIR) build_only
	@pass=0; fail=0; \
	for i in $$(seq 0 $$(( $(COUNT) - 1 ))); do \
		seed=$$(( $(SEED) + $$i )); \
		log="$(OUT_DIR)/random_$${seed}.log"; \
		echo "[run_random] size=$(SIZE) cache=$(IA_CACHE_BLOCKS) seed=$${seed}"; \
		python3 gen_mem.py --out_dir $(OUT_DIR) --size $(SIZE) --ia_cache_blocks $(IA_CACHE_BLOCKS) --seed $${seed} $(RANDOM_GEN_ARGS) || exit 1; \
		$(SIM_BIN) +INIT_MEM=$(MEM_INIT) +GOLDEN_MEM=$(MEM_GOLDEN) +CASE_MEM=$(MEM_CASE) $(SIM_ARGS) +DDR_SEED=$${seed} | tee "$${log}"; \
		if grep -q "\\[TB\\] PASS" "$${log}"; then pass=$$((pass + 1)); else fail=$$((fail + 1)); fi; \
	done; \
	echo "[run_random] PASS=$${pass} FAIL=$${fail}"; \
	test "$${fail}" -eq 0

run_param_random: $(OUT_DIR)
	@pass=0; fail=0; idx=0; \
	for size in $(SIZES); do \
		for cache in $(CACHE_BLOCKS_LIST); do \
			build_log="$(OUT_DIR)/build_s$${size}_c$${cache}.log"; \
			$(MAKE) --no-print-directory build_only SIZE=$${size} IA_CACHE_BLOCKS=$${cache} PS_FRAME_COUNT=$(PS_FRAME_COUNT) > "$${build_log}" 2>&1 || { \
				cat "$${build_log}"; fail=$$((fail + $(COUNT))); idx=$$((idx + $(COUNT))); continue; }; \
			bin="$(BUILD_ROOT)/s$${size}_c$${cache}_ps$(PS_FRAME_COUNT)/$(VEXE)"; \
			for i in $$(seq 0 $$(( $(COUNT) - 1 ))); do \
				seed=$$(( $(SEED) + $$idx )); idx=$$((idx + 1)); \
				log="$(OUT_DIR)/param_s$${size}_c$${cache}_$${seed}.log"; \
				echo "[run_param_random] size=$${size} cache=$${cache} seed=$${seed}"; \
				python3 gen_mem.py --out_dir $(OUT_DIR) --size $${size} --ia_cache_blocks $${cache} --seed $${seed} $(RANDOM_GEN_ARGS) || exit 1; \
				"$${bin}" +INIT_MEM=$(MEM_INIT) +GOLDEN_MEM=$(MEM_GOLDEN) +CASE_MEM=$(MEM_CASE) $(SIM_ARGS) +DDR_SEED=$${seed} | tee "$${log}"; \
				if grep -q "\\[TB\\] PASS" "$${log}"; then pass=$$((pass + 1)); else fail=$$((fail + 1)); fi; \
			done; \
		done; \
	done; \
	echo "[run_param_random] PASS=$${pass} FAIL=$${fail}"; \
	test "$${fail}" -eq 0

wave: run
	gtkwave wave.vcd

clean:
	rm -rf $(VEXE) *.vcd obj_dir $(OUT_DIR)

.PHONY: all build build_only run run_only run_random run_param_random clean wave gen
