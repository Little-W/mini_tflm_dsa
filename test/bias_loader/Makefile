# ================================================================
# bias_loader 验证 Makefile
# ================================================================

PROJECT_ROOT := ../..
DEP_MODULES_DIR := $(PROJECT_ROOT)/test/dep_modules
SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules
INC_DIR := $(PROJECT_ROOT)/inc
VEXE := sim_bias_loader

CASE ?= single
SEED ?= 42
COUNT ?= 100

VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	-Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE \
	-Wno-UNOPTFLAT -Wno-BLKANDNBLK -Wno-INITIALDLY -Wno-MULTIDRIVEN \
	-Wno-IMPLICITSTATIC -Wno-WIDTHCONCAT -Wno-LATCH -Wno-TIMESCALEMOD \
	-Wno-EOFNEWLINE -Wno-PINCONNECTEMPTY -Wno-BLKSEQ \
	-Wno-PROCASSINIT -Wno-SYNCASYNCNET

INCLUDES := -I$(INC_DIR) -Iout

SRCS := \
	tb_bias_loader.sv \
	tb_sram_model.sv \
	$(SUB_MODULES_DIR)/bias_loader.sv \
	$(SUB_MODULES_DIR)/bias_loader_ctrl.sv \
	$(SUB_MODULES_DIR)/bias_loader_buffer.sv \
	$(SUB_MODULES_DIR)/block_dma.sv \
	$(DEP_MODULES_DIR)/icb_unalign_bridge.sv

all: run

gen:
	python3 gen_test_data.py --case $(CASE) --out_dir out

build: gen
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_bias_loader

run: build
	@mkdir -p out
	./obj_dir/$(VEXE) +WAVE_FILE=out/wave_$(CASE).vcd

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
		verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_bias_loader 2>&1 | tail -1 && \
		mkdir -p out && ./obj_dir/$(VEXE) +WAVE_FILE=out/wave_$$c.vcd 2>&1 | tee /tmp/bias_loader_$$c.log && \
		if grep -q 'PASS' /tmp/bias_loader_$$c.log; then \
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
		verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_bias_loader 2>&1 | tail -1 && \
		mkdir -p out && ./obj_dir/$(VEXE) +WAVE_FILE=out/wave_$$c.vcd 2>&1 | tee /tmp/bias_loader_$$c.log && \
		if grep -q 'PASS' /tmp/bias_loader_$$c.log; then \
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

clean:
	rm -rf obj_dir out *.vcd /tmp/bias_loader_*.log

.PHONY: all gen build run run_all run_random list clean
