ROOT := ../..
UNIT := axi_block_dma_arbiter

.PHONY: all build build_only run run_only clean
all: run

build build_only:
	$(MAKE) -C $(ROOT) vcs-unit-build UNIT=$(UNIT)

run run_only:
	$(MAKE) -C $(ROOT) vcs-unit-$(UNIT)

clean:
	rm -rf $(ROOT)/build/vcs/unit/$(UNIT)
