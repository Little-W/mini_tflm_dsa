PROJECT_ROOT := ../..
RTL_ROOT := $(PROJECT_ROOT)/rtl
COMMON_RTL_DIR := $(RTL_ROOT)/common
NPU_COMPUTE_DIR := $(RTL_ROOT)/npu/compute
NPU_BUFFERS_DIR := $(RTL_ROOT)/npu/buffers
TB := tb_compute_core.sv
TEST_PARAMS := test_params_pkg.sv
VEXE := sim_compute_core
SEED ?= 42
COUNT ?= 32
# INCLUDES := -I $(PROJECT_ROOT)/inc

# Suppress non-critical Verilator warnings to allow build
VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL -Wno-UNUSED -Wno-UNUSEDGENVAR \
	-Wno-EOFNEWLINE -Wno-MULTITOP -Wno-BLKSEQ -Wno-WIDTHTRUNC -Wno-UNDRIVEN \
	-Wno-SYNCASYNCNET -Wno-DECLFILENAME

SRCS := \
	$(TEST_PARAMS) \
	$(TB) \
	tb_compute_core_if.sv \
	compute_core_test.sv \
	$(NPU_COMPUTE_DIR)/bias_mux.sv \
	$(NPU_BUFFERS_DIR)/ps_buffer.sv \
	$(NPU_BUFFERS_DIR)/ps_buffer_fifo.sv \
	$(NPU_COMPUTE_DIR)/de_diagonalizer.sv \
	$(COMMON_RTL_DIR)/pseudo_dual_port_ram.v \
	$(NPU_COMPUTE_DIR)/ws_systolic_array.sv \
	$(NPU_COMPUTE_DIR)/ws_systolic_cell.sv

all: run

gen: gen_mats.py
	python3 gen_mats.py

build: gen $(TB)
	$(MAKE) build_only

build_only:
	rm -rf obj_dir
	verilator $(VERILATOR_FLAGS) $(INCLUDES) --binary $(SRCS) -o $(VEXE)

run: build
	./obj_dir/$(VEXE)

run_random: build
	@PASS=0; FAIL=0; TOTAL=0; \
	for seed in $$(seq $(SEED) $$(( $(SEED) + $(COUNT) - 1 ))); do \
		TOTAL=$$((TOTAL+1)); \
		echo ""; \
		echo "════════════════════════════════════════"; \
		echo "  Random seed: $$seed"; \
		echo "════════════════════════════════════════"; \
		python3 gen_mats.py --seed $$seed --random-shape; \
		$(MAKE) build_only; \
		./obj_dir/$(VEXE) +SKIP_COMPARE=1 2>&1 | tee /tmp/compute_core_$$seed.log; \
		if grep -q 'PASS: compute_core 4x16 \* 16x4 matched expected' /tmp/compute_core_$$seed.log; then \
			PASS=$$((PASS+1)); \
		else \
			FAIL=$$((FAIL+1)); \
			echo "  !! FAILED seed: $$seed"; \
		fi; \
	done; \
	echo ""; \
	echo "════════════════════════════════════════"; \
	echo "  Random summary: $$PASS/$$TOTAL passed, $$FAIL failed"; \
	echo "════════════════════════════════════════"; \
	[ $$FAIL -eq 0 ]

run_all: run_random

wave: run
	# 波形文件为wave.vcd（在当前目录下），可用gtkwave等工具查看

clean:
	rm -rf $(VEXE) *.vcd *.hex *.txt obj_dir tiles test_params_pkg.sv test_params.svh
.PHONY: all gen build run clean
