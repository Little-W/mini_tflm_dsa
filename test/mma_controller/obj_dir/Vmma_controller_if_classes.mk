# Verilated -*- Makefile -*-
# DESCRIPTION: Verilator output: Make include file with class lists
#
# This file lists generated Verilated files, for including in higher level makefiles.
# See Vmma_controller_if.mk for the caller.

### Switches...
# C11 constructs required?  0/1 (always on now)
VM_C11 = 1
# Timing enabled?  0/1
VM_TIMING = 1
# Coverage output mode?  0/1 (from --coverage)
VM_COVERAGE = 0
# Parallel builds?  0/1 (from --output-split)
VM_PARALLEL_BUILDS = 0
# Tracing output mode?  0/1 (from --trace/--trace-fst)
VM_TRACE = 1
# Tracing output mode in VCD format?  0/1 (from --trace)
VM_TRACE_VCD = 1
# Tracing output mode in FST format?  0/1 (from --trace-fst)
VM_TRACE_FST = 0

### Object file lists...
# Generated module classes, fast-path, compile with highest optimization
VM_CLASSES_FAST += \
	Vmma_controller_if \
	Vmma_controller_if___024root__DepSet_h2075e9cf__0 \
	Vmma_controller_if___024root__DepSet_h1f8fd6ba__0 \
	Vmma_controller_if_ia_loader_if__DepSet_h4b276b6a__0 \
	Vmma_controller_if_ia_loader_if__DepSet_h385e585d__0 \
	Vmma_controller_if_weight_loader_if__DepSet_h0f2cd44c__0 \
	Vmma_controller_if_weight_loader_if__DepSet_hfc58d33b__0 \
	Vmma_controller_if_bias_loader_if__DepSet_h882fbce3__0 \
	Vmma_controller_if_bias_loader_if__DepSet_h77562be6__0 \
	Vmma_controller_if_requant_if__DepSet_h5e99ccc1__0 \
	Vmma_controller_if_requant_if__DepSet_h4cabbbc8__0 \
	Vmma_controller_if_oa_writer_if__DepSet_h38dbbab9__0 \
	Vmma_controller_if_oa_writer_if__DepSet_h26ea2a10__0 \
	Vmma_controller_if_compute_core_if__DepSet_h1551f5d7__0 \
	Vmma_controller_if_compute_core_if__DepSet_h1273f2b2__0 \
	Vmma_controller_if_control_if__R20__DepSet_h938b3b76__0 \
	Vmma_controller_if_control_if__R20__DepSet_h8fbaa851__0 \
	Vmma_controller_if__main \

# Generated module classes, non-fast-path, compile with low/medium optimization
VM_CLASSES_SLOW += \
	Vmma_controller_if___024root__Slow \
	Vmma_controller_if___024root__DepSet_h2075e9cf__0__Slow \
	Vmma_controller_if___024root__DepSet_h1f8fd6ba__0__Slow \
	Vmma_controller_if_ia_loader_if__Slow \
	Vmma_controller_if_ia_loader_if__DepSet_h385e585d__0__Slow \
	Vmma_controller_if_weight_loader_if__Slow \
	Vmma_controller_if_weight_loader_if__DepSet_hfc58d33b__0__Slow \
	Vmma_controller_if_bias_loader_if__Slow \
	Vmma_controller_if_bias_loader_if__DepSet_h77562be6__0__Slow \
	Vmma_controller_if_requant_if__Slow \
	Vmma_controller_if_requant_if__DepSet_h4cabbbc8__0__Slow \
	Vmma_controller_if_oa_writer_if__Slow \
	Vmma_controller_if_oa_writer_if__DepSet_h26ea2a10__0__Slow \
	Vmma_controller_if_compute_core_if__Slow \
	Vmma_controller_if_compute_core_if__DepSet_h1273f2b2__0__Slow \
	Vmma_controller_if___024unit__Slow \
	Vmma_controller_if___024unit__DepSet_hc91d27cf__0__Slow \
	Vmma_controller_if_control_if__R20__Slow \
	Vmma_controller_if_control_if__R20__DepSet_h8fbaa851__0__Slow \

# Generated support classes, fast-path, compile with highest optimization
VM_SUPPORT_FAST += \
	Vmma_controller_if__Trace__0 \

# Generated support classes, non-fast-path, compile with low/medium optimization
VM_SUPPORT_SLOW += \
	Vmma_controller_if__Syms \
	Vmma_controller_if__Trace__0__Slow \
	Vmma_controller_if__TraceDecls__0__Slow \

# Global classes, need linked once per executable, fast-path, compile with highest optimization
VM_GLOBAL_FAST += \
	verilated \
	verilated_vcd_c \
	verilated_timing \
	verilated_threads \

# Global classes, need linked once per executable, non-fast-path, compile with low/medium optimization
VM_GLOBAL_SLOW += \


# Verilated -*- Makefile -*-
