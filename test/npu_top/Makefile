ROOT := ../..
UNIT := npu_top

.PHONY: all build build_only run run_only clean
all: run

build build_only:
	$(MAKE) -C $(ROOT) vcs-unit-build UNIT=$(UNIT)

run run_only:
	$(MAKE) -C $(ROOT) vcs-unit-$(UNIT)

clean:
	rm -rf $(ROOT)/build/vcs/unit/$(UNIT)

.PHONY: run_random run_all
run_random run_all:
	$(MAKE) -C $(ROOT) vcs-random-npu

.PHONY: run_param_random
run_param_random:
	$(MAKE) -C $(ROOT) vcs-param-npu

.PHONY: wave
wave:
	$(MAKE) -C $(ROOT) vcs-top DEBUG=1 SIM_ARGS='$(SIM_ARGS) +WAVE'
