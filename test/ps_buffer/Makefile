PROJECT_ROOT := ../..
RTL_ROOT := $(PROJECT_ROOT)/rtl
COMMON_RTL_DIR := $(RTL_ROOT)/common
NPU_COMPUTE_DIR := $(RTL_ROOT)/npu/compute
NPU_BUFFERS_DIR := $(RTL_ROOT)/npu/buffers
TB := tb_ps_buffer.sv
VEXE := sim_ps_buffer

VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL -Wno-UNUSED -Wno-UNUSEDGENVAR \
	-Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE -Wno-UNOPTFLAT -Wno-BLKANDNBLK -Wno-INITIALDLY -Wno-MULTIDRIVEN \
	-Wno-IMPLICITSTATIC -Wno-WIDTHCONCAT -Wno-LATCH -Wno-TIMESCALEMOD -Wno-EOFNEWLINE -Wno-PINCONNECTEMPTY -Wno-BLKSEQ \
	-Wno-PROCASSINIT -Wno-SYNCASYNCNET -Wno-DECLFILENAME

SRCS := \
	$(TB) \
	$(NPU_BUFFERS_DIR)/ps_buffer.sv \
	$(NPU_COMPUTE_DIR)/de_diagonalizer.sv \
	$(COMMON_RTL_DIR)/pseudo_dual_port_ram.v \
	$(NPU_BUFFERS_DIR)/ps_buffer_fifo.sv

all: run

build:
	verilator $(VERILATOR_FLAGS) --binary $(SRCS) -o $(VEXE) --top-module tb_ps_buffer

run: build
	./obj_dir/$(VEXE)

clean:
	rm -rf obj_dir $(VEXE) *.vcd

.PHONY: all build run clean
