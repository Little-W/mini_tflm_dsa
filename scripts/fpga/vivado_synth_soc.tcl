# 完整生产 SoC 的 Vivado 综合与时序报告。
#
# Usage:
#   vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl
#   vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl -tclargs build/my_synth

set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir ../..]]

if {[llength $argv] >= 1} {
    set out_dir [file normalize [lindex $argv 0]]
} else {
    set out_dir [file join $repo_root build vivado_soc_synth_150mhz]
}
file mkdir $out_dir

set part_name xc7a200tfbg484-3
set top_name  soc_top
set clock_period_ns 6.667
set_param general.maxThreads 2
set synth_generics {
    SIZE=16 BUS_WIDTH=64 IA_CACHE_BLOCKS=4 IM2COL_CACHE_BYTES=4096
    SHARED_BANK_BYTES=8192 SHARED_BANK_COUNT=7 PS_FRAME_COUNT=16
    AXI_READ_OUTSTANDING=4 AXI_WRITE_OUTSTANDING=4
    ENABLE_VECTOR_ENGINE=1 VECTOR_PE_COUNT=8
    CPU_MEM_DP=65536 CPU_MEM_WORD_WIDTH=64 CPU_MEM_INIT_EN=0
    CPU_ENABLE_ICACHE=0 CPU_ENABLE_MUL=1 CPU_ENABLE_DIV=1
    NPU_ENABLE_IS_MODE=1 NPU_ENABLE_PER_CHANNEL=1 NPU_ENABLE_CLOCK_GATING=1
    NPU_AXI_TIMING_BUFFER=1 CPU_AXI_WRITE_TIMING_BUFFER=1
    BYPASS_RAM_PINGPONG=0 RAM_WRITE_TIMING_BUFFER=1
}

source [file join $repo_root fpga vivado tflm_ai_dsa_soc scripts sources.tcl]
set incdirs $include_dirs
set hardware_config [npu_config::read $repo_root]
foreach {name expected} {
    NPU_AXI_DATA_WIDTH 64 SHARED_BANK_BYTES 8192 SHARED_BANK_COUNT 7
    IM2COL_CACHE_BYTES 4096 PCR_ENGINE 1 PS_POOL_BYTES 49152 PS_FORCE_RAW 1
} {
    if {[dict get $hardware_config $name] != $expected} {
        error "Production synthesis requires $name=$expected"
    }
}
npu_config::write_snapshot [file join $out_dir hardware_config.mk] $hardware_config
set rtl_files {}
foreach source_file $design_sources {
    if {[file tail $source_file] ni {fpga_top.sv clk_wiz_0_sim_stub.sv}} {
        lappend rtl_files $source_file
    }
}
foreach source_file [lsort [glob -nocomplain -directory [file join $repo_root rtl common] *.v *.sv]] {
    if {$source_file ni $rtl_files} { lappend rtl_files $source_file }
}

set xdc_file [file join $out_dir soc_top_150mhz.xdc]
set xdc_fh [open $xdc_file w]
puts $xdc_fh "create_clock -name clk -period $clock_period_ns \[get_ports clk\]"
close $xdc_fh

create_project -in_memory -part $part_name
set_property include_dirs $incdirs [current_fileset]
set_property verilog_define {
    SYNTHESIS=1 XILINX_FPGA=1 XILINX_CLK_WIZ_IP=1
    GEMPACT_PS_COMPRESS=1 GEMMORA_PS_POOL_BYTES=49152 GEMMORA_PS_FORCE_RAW=1
} [current_fileset]

read_verilog -sv $rtl_files
read_xdc $xdc_file

synth_design -top $top_name -part $part_name -generic $synth_generics -flatten_hierarchy rebuilt

report_utilization -file [file join $out_dir soc_top_utilization.rpt]
report_utilization -hierarchical -file [file join $out_dir soc_top_utilization_hier.rpt]
report_timing_summary -delay_type max -report_unconstrained -check_timing_verbose \
    -file [file join $out_dir soc_top_timing_summary.rpt]
report_timing -delay_type max -sort_by group -max_paths 200 -nworst 1 \
    -file [file join $out_dir soc_top_timing_paths.rpt]
report_high_fanout_nets -fanout_greater_than 100 -max_nets 200 \
    -file [file join $out_dir soc_top_high_fanout.rpt]
write_checkpoint -force [file join $out_dir soc_top_synth.dcp]
