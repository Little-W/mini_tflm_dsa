ROOT := ../..
UNIT := compute_core

.PHONY: all build build_only run run_only clean
all: run

build build_only:
	$(MAKE) -C $(ROOT) vcs-unit-build UNIT=$(UNIT)

run run_only:
	$(MAKE) -C $(ROOT) vcs-unit-$(UNIT)

clean:
	rm -rf $(ROOT)/build/vcs/unit/$(UNIT) $(ROOT)/build/vcs/unit/$(UNIT)_debug $(ROOT)/build/vcs/unit/compute_case $(ROOT)/build/vcs/unit/compute_random

.PHONY: run_random run_all
run_random run_all:
	$(MAKE) -C $(ROOT) vcs-random-compute

.PHONY: wave
wave:
	$(MAKE) -C $(ROOT) vcs-unit-compute_core DEBUG=1
