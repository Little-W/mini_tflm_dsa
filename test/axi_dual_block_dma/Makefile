VEXE := sim_axi_dual_block_dma
PROJECT_ROOT := ../..
NPU_DMA_DIR := $(PROJECT_ROOT)/rtl/npu/dma

VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
	-Wno-UNUSEDSIGNAL -Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-TIMESCALEMOD \
	-Wno-DECLFILENAME -Wno-EOFNEWLINE -Wno-PROCASSINIT -Wno-BLKSEQ \
	-Wno-INITIALDLY -Wno-SYNCASYNCNET

SRCS := \
	tb_axi_dual_block_dma.sv \
	$(NPU_DMA_DIR)/axi_dual_block_dma.sv

all: run

build:
	verilator $(VERILATOR_FLAGS) --binary $(SRCS) -o $(VEXE) --top-module tb_axi_dual_block_dma

run: build
	./obj_dir/$(VEXE)

clean:
	rm -rf obj_dir *.vcd

.PHONY: all build run clean
