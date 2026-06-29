# ================================================================
# ia_loader 验证 Makefile
# ================================================================
# 用法：
#   make run                     — 默认 case (exact_2x2)
#   make run CASE=col_rem        — 运行指定 case
#   make run_all                 — 运行所有预定义 case
#   make run_random SEED=42 COUNT=5 — 运行随机 case
#   make list                    — 列出所有预定义 case
#   make clean
# ================================================================

PROJECT_ROOT := ../..
DEP_MODULES_DIR := $(PROJECT_ROOT)/test/dep_modules
BASIC_MODULES_DIR := $(PROJECT_ROOT)/basic
INC_DIR := $(PROJECT_ROOT)/inc
VEXE := sim_ia_loader

# 默认 case
CASE ?= exact_2x2
SEED ?= 42
COUNT ?= 5

VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	-Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE \
	-Wno-UNOPTFLAT -Wno-BLKANDNBLK -Wno-INITIALDLY -Wno-MULTIDRIVEN \
	-Wno-IMPLICITSTATIC -Wno-WIDTHCONCAT -Wno-LATCH -Wno-TIMESCALEMOD \
	-Wno-EOFNEWLINE -Wno-PINCONNECTEMPTY -Wno-BLKSEQ

INCLUDES := -I$(INC_DIR) -Iout

SRCS := \
	tb_ia_loader.sv \
	tb_sram_model.sv \
	ia_loader.sv \
	ia_loader_ctrl.sv \
	block_dma.sv \
	ia_loader_cache_mgr.sv \
	$(DEP_MODULES_DIR)/icb_unalign_bridge.sv \
	$(BASIC_MODULES_DIR)/pseudo_dual_port_ram.v

all: run

# ── 单 case 流程 ──
gen:
	python3 gen_test_data.py --case $(CASE) --out_dir out

build: gen
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_ia_loader

run: build
	@echo "======== Running case: $(CASE) ========"
	@mkdir -p out
	./obj_dir/$(VEXE) +WAVE_FILE=out/wave_$(CASE).vcd

# ── 所有预定义 case ──
run_all:
	@python3 gen_test_data.py --list
	@PASS=0; FAIL=0; TOTAL=0; \
	for c in $$(python3 gen_test_data.py --list | tail -n +2 | awk '{print $$1}'); do \
		TOTAL=$$((TOTAL+1)); \
		echo ""; \
		echo "════════════════════════════════════════"; \
		echo "  Case: $$c"; \
		echo "════════════════════════════════════════"; \
		python3 gen_test_data.py --case $$c --out_dir out && \
		verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_ia_loader 2>&1 | tail -1 && \
		mkdir -p out && ./obj_dir/$(VEXE) +WAVE_FILE=out/wave_$$c.vcd 2>&1 | tee /tmp/ia_loader_$$c.log && \
		if grep -q 'PASS' /tmp/ia_loader_$$c.log; then \
			PASS=$$((PASS+1)); \
		else \
			FAIL=$$((FAIL+1)); \
			echo "  !! FAILED: $$c"; \
		fi; \
	done; \
	echo ""; \
	echo "════════════════════════════════════════"; \
	echo "  Summary: $$PASS/$$TOTAL passed, $$FAIL failed"; \
	echo "════════════════════════════════════════"; \
	[ $$FAIL -eq 0 ]

# ── 随机 case ──
run_random:
	@PASS=0; FAIL=0; TOTAL=0; \
	python3 gen_test_data.py --random --seed $(SEED) --count $(COUNT) --out_dir out; \
	for c in $$(cat out/case_list.txt); do \
		TOTAL=$$((TOTAL+1)); \
		echo ""; \
		echo "════════════════════════════════════════"; \
		echo "  Random case: $$c"; \
		echo "════════════════════════════════════════"; \
		cp out/$$c/* out/ && \
		verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_ia_loader 2>&1 | tail -1 && \
		mkdir -p out && ./obj_dir/$(VEXE) +WAVE_FILE=out/wave_$$c.vcd 2>&1 | tee /tmp/ia_loader_$$c.log && \
		if grep -q 'PASS' /tmp/ia_loader_$$c.log; then \
			PASS=$$((PASS+1)); \
		else \
			FAIL=$$((FAIL+1)); \
			echo "  !! FAILED: $$c"; \
		fi; \
	done; \
	echo ""; \
	echo "════════════════════════════════════════"; \
	echo "  Random summary: $$PASS/$$TOTAL passed, $$FAIL failed (seed=$(SEED))"; \
	echo "════════════════════════════════════════"; \
	[ $$FAIL -eq 0 ]

list:
	python3 gen_test_data.py --list

wave:
	@echo "波形文件: out/wave_$(CASE).vcd"
	gtkwave out/wave_$(CASE).vcd &

clean:
	rm -rf obj_dir out *.vcd /tmp/ia_loader_*.log

.PHONY: all gen build run run_all run_random list wave clean
