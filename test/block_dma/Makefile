VEXE := sim_block_dma
PROJECT_ROOT := ../..
SUB_MODULES_DIR := $(PROJECT_ROOT)/sub_modules

VERILATOR_FLAGS := -sv -Wall --trace --timing \
	-Wno-GENUNNAMED -Wno-VARHIDDEN -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
	-Wno-UNUSED -Wno-UNUSEDGENVAR -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE \
	-Wno-UNOPTFLAT -Wno-BLKANDNBLK -Wno-INITIALDLY -Wno-MULTIDRIVEN \
	-Wno-IMPLICITSTATIC -Wno-WIDTHCONCAT -Wno-LATCH -Wno-TIMESCALEMOD \
	-Wno-EOFNEWLINE -Wno-PINCONNECTEMPTY -Wno-BLKSEQ -Wno-PROCASSINIT

SRCS := \
	tb_block_dma.sv \
	$(SUB_MODULES_DIR)/block_dma.sv \
	../ia_loader/tb_sram_model.sv

all: run

build:
	verilator $(VERILATOR_FLAGS) --binary $(SRCS) -o $(VEXE) --top-module tb_block_dma

run: build
	./obj_dir/$(VEXE)

clean:
	rm -rf obj_dir *.vcd

.PHONY: all build run clean
