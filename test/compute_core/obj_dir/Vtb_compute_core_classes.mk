# Verilated -*- Makefile -*-
# DESCRIPTION: Verilator output: Make include file with class lists
#
# This file lists generated Verilated files, for including in higher level makefiles.
# See Vtb_compute_core.mk for the caller.

### Switches...
# C11 constructs required?  0/1 (always on now)
VM_C11 = 1
# Timing enabled?  0/1
VM_TIMING = 1
# Coverage output mode?  0/1 (from --coverage)
VM_COVERAGE = 0
# Parallel builds?  0/1 (from --output-split)
VM_PARALLEL_BUILDS = 0
# Tracing output mode?  0/1 (from --trace-fst/--trace-saif/--trace-vcd)
VM_TRACE = 1
# Tracing output mode in FST format?  0/1 (from --trace-fst)
VM_TRACE_FST = 0
# Tracing output mode in SAIF format?  0/1 (from --trace-saif)
VM_TRACE_SAIF = 0
# Tracing output mode in VCD format?  0/1 (from --trace-vcd)
VM_TRACE_VCD = 1

### Object file lists...
# Generated module classes, fast-path, compile with highest optimization
VM_CLASSES_FAST += \
  Vtb_compute_core \
  Vtb_compute_core___024root__DepSet_h88611d68__0 \
  Vtb_compute_core___024root__DepSet_he697d28d__0 \
  Vtb_compute_core_tb_compute_core_if__DepSet_h25515e8b__0 \
  Vtb_compute_core_tb_compute_core_if__DepSet_h938810ac__0 \
  Vtb_compute_core__main \

# Generated module classes, non-fast-path, compile with low/medium optimization
VM_CLASSES_SLOW += \
  Vtb_compute_core__ConstPool_0 \
  Vtb_compute_core___024root__Slow \
  Vtb_compute_core___024root__DepSet_h88611d68__0__Slow \
  Vtb_compute_core___024root__DepSet_he697d28d__0__Slow \
  Vtb_compute_core_tb_compute_core_if__Slow \
  Vtb_compute_core_tb_compute_core_if__DepSet_h938810ac__0__Slow \

# Generated support classes, fast-path, compile with highest optimization
VM_SUPPORT_FAST += \
  Vtb_compute_core__Trace__0 \

# Generated support classes, non-fast-path, compile with low/medium optimization
VM_SUPPORT_SLOW += \
  Vtb_compute_core__Syms \
  Vtb_compute_core__Trace__0__Slow \
  Vtb_compute_core__TraceDecls__0__Slow \

# Global classes, need linked once per executable, fast-path, compile with highest optimization
VM_GLOBAL_FAST += \
  verilated \
  verilated_vcd_c \
  verilated_timing \
  verilated_threads \

# Global classes, need linked once per executable, non-fast-path, compile with low/medium optimization
VM_GLOBAL_SLOW += \

# Verilated -*- Makefile -*-
