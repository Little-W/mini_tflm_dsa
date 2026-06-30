PROJECT_ROOT := ../..
OUT_DIR := out
SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules
VEXE := sim_kernel_loader

CASE ?= exact_4x4_r2_w2
SEED ?= 42
COUNT ?= 100

VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-UNUSEDSIGNAL -Wno-UNOPTFLAT -Wno-INITIALDLY -Wno-WIDTHCONCAT \
	-Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
	-Wno-LATCH -Wno-BLKSEQ -Wno-PINCONNECTEMPTY -Wno-CASEINCOMPLETE \
	-Wno-BLKANDNBLK -Wno-UNUSED -Wno-EOFNEWLINE \
	-Wno-PROCASSINIT -Wno-SYNCASYNCNET

INCLUDES := -I. -I$(OUT_DIR)

SRCS := \
	kernel_loader_tb_if.sv \
	icb_bus_if.sv \
	tb_kernel_loader.sv \
	tb_sram_model.sv \
	../dep_modules/icb_unalign_bridge.sv \
	$(SUB_MODULES_DIR)/kernel_loader.sv \
	$(SUB_MODULES_DIR)/kernel_loader_ctrl.sv \
	$(SUB_MODULES_DIR)/kernel_loader_buffer.sv \
	$(SUB_MODULES_DIR)/kernel_block_dma.sv

all: run

gen:
	python3 gen_test_data.py --case $(CASE) --out_dir $(OUT_DIR)

build: gen
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_kernel_loader

run: build
	@mkdir -p $(OUT_DIR)
	./obj_dir/$(VEXE) +WAVE_FILE=$(OUT_DIR)/wave_$(CASE).vcd

list:
	python3 gen_test_data.py --list

run_all:
	@PASS=0; FAIL=0; TOTAL=0; SUMMARY=""; \
	for c in $$(python3 gen_test_data.py --list | tail -n +2 | awk '{print $$1}'); do \
		TOTAL=$$((TOTAL+1)); \
		echo ""; \
		echo "════════════════════════════════════════"; \
		echo "  Case: $$c"; \
		echo "════════════════════════════════════════"; \
		python3 gen_test_data.py --case $$c --out_dir $(OUT_DIR) || { FAIL=$$((FAIL+1)); SUMMARY="$$SUMMARY\n  $$c: GEN_FAIL"; continue; }; \
		build_log=/tmp/kernel_loader_$$c.build.log; \
		if ! verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_kernel_loader > "$$build_log" 2>&1; then \
			cat "$$build_log"; \
			FAIL=$$((FAIL+1)); \
			echo "  !! BUILD FAILED: $$c"; \
			SUMMARY="$$SUMMARY\n  $$c: BUILD_FAIL"; \
			continue; \
		fi; \
		tail -1 "$$build_log"; \
		./obj_dir/$(VEXE) +WAVE_FILE=$(OUT_DIR)/wave_$$c.vcd 2>&1 | tee /tmp/kernel_loader_$$c.log; \
		if grep -q 'PASS' /tmp/kernel_loader_$$c.log; then \
			PASS=$$((PASS+1)); \
			SUMMARY="$$SUMMARY\n  $$c: PASS"; \
		else \
			FAIL=$$((FAIL+1)); \
			echo "  !! FAILED: $$c"; \
			SUMMARY="$$SUMMARY\n  $$c: FAIL"; \
		fi; \
	done; \
	echo ""; \
	echo "════════════════════════════════════════"; \
	echo "  Summary: $$PASS/$$TOTAL passed, $$FAIL failed"; \
	printf '%b\n' "$$SUMMARY"; \
	echo "════════════════════════════════════════"; \
	[ $$FAIL -eq 0 ]

run_random:
	@PASS=0; FAIL=0; TOTAL=0; \
	python3 gen_test_data.py --random --seed $(SEED) --count $(COUNT) --out_dir $(OUT_DIR); \
	for c in $$(cat $(OUT_DIR)/case_list.txt); do \
		TOTAL=$$((TOTAL+1)); \
		echo ""; \
		echo "════════════════════════════════════════"; \
		echo "  Random case: $$c"; \
		echo "════════════════════════════════════════"; \
		cp $(OUT_DIR)/$$c/* $(OUT_DIR)/ || { FAIL=$$((FAIL+1)); continue; }; \
		build_log=/tmp/kernel_loader_$$c.build.log; \
		if ! verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE) --top-module tb_kernel_loader > "$$build_log" 2>&1; then \
			cat "$$build_log"; \
			FAIL=$$((FAIL+1)); \
			echo "  !! BUILD FAILED: $$c"; \
			continue; \
		fi; \
		tail -1 "$$build_log"; \
		./obj_dir/$(VEXE) +WAVE_FILE=$(OUT_DIR)/wave_$$c.vcd 2>&1 | tee /tmp/kernel_loader_$$c.log; \
		if grep -q 'PASS' /tmp/kernel_loader_$$c.log; then \
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

wave:
	@echo "Wave file: $(OUT_DIR)/wave_$(CASE).vcd"
	gtkwave $(OUT_DIR)/wave_$(CASE).vcd &

clean:
	rm -rf obj_dir $(OUT_DIR) *.vcd /tmp/kernel_loader_*.log

.PHONY: all gen build run list run_all run_random wave clean
