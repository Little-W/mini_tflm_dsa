VEXE := sim_axi_block_dma_arbiter
PROJECT_ROOT := ../..
SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules

VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
	-Wno-UNUSEDSIGNAL -Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-TIMESCALEMOD \
	-Wno-DECLFILENAME -Wno-EOFNEWLINE -Wno-PROCASSINIT -Wno-BLKSEQ \
	-Wno-INITIALDLY -Wno-SYNCASYNCNET

SRCS := \
	tb_axi_block_dma_arbiter.sv \
	$(SUB_MODULES_DIR)/axi_block_dma_arbiter.sv \
	$(SUB_MODULES_DIR)/axi_dual_block_dma.sv

all: run

build:
	verilator $(VERILATOR_FLAGS) --binary $(SRCS) -o $(VEXE) --top-module tb_axi_block_dma_arbiter

run: build
	./obj_dir/$(VEXE)

clean:
	rm -rf obj_dir *.vcd

.PHONY: all build run clean
