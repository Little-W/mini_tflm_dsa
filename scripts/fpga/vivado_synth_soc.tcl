# 完整生产 SoC 的 Vivado 综合与时序报告。
#
# Usage:
#   vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl
#   vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl -tclargs build/my_synth
#   vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl -tclargs build/my_impl soc_pins.xdc

set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir ../..]]
source [file join $script_dir vivado_soc_reports.tcl]
set report_helper [file join $script_dir vivado_soc_results.py]

if {[llength $argv] > 2} { error "Expected an output directory and optional SoC pin XDC" }
set pin_xdc ""
if {[llength $argv] == 2} {
    set pin_xdc [file normalize [lindex $argv 1]]
    if {![file isfile $pin_xdc]} { error "SoC pin constraints do not exist: $pin_xdc" }
}

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
set synth_defines {
    SYNTHESIS=1 XILINX_FPGA=1 XILINX_CLK_WIZ_IP=1
    GEMPACT_PS_COMPRESS=1 GEMMORA_PS_POOL_BYTES=49152 GEMMORA_PS_FORCE_RAW=1
}
set_property verilog_define $synth_defines [current_fileset]

set measurement_sources [concat $rtl_files [soc_reports::dependency_sources] [list $xdc_file $report_helper \
    [file join $script_dir vivado_soc_reports.tcl] [file normalize [info script]] \
    [file join $out_dir hardware_config.mk]]]
foreach source_file [glob -directory [file join $repo_root fpga vivado tflm_ai_dsa_soc scripts] *.tcl] {
    lappend measurement_sources $source_file
}
if {$pin_xdc ne ""} { lappend measurement_sources $pin_xdc }
set source_manifest [soc_reports::snapshot $out_dir $report_helper \
    [dict create repository $repo_root vivado_version [version -short] part $part_name \
        top $top_name clock_period_ns $clock_period_ns generics [join $synth_generics " "] \
        defines [join $synth_defines " "] pin_xdc $pin_xdc] $measurement_sources $incdirs]

read_verilog -sv $rtl_files
read_xdc $xdc_file

synth_design -top $top_name -part $part_name -generic $synth_generics -flatten_hierarchy rebuilt

soc_reports::write $out_dir
write_checkpoint -force [file join $out_dir soc_top_synth.dcp]
puts [exec python3 $report_helper summarize --manifest $source_manifest \
    --directory $out_dir --stage synthesized]
soc_reports::check_array $out_dir 16

if {$pin_xdc ne ""} {
    read_xdc $pin_xdc
    set main_clock [get_clocks -quiet -of_objects [get_ports clk]]
    if {[llength $main_clock] != 1} { error "Expected one clock on soc_top.clk" }
    set actual_period [timing_checks::finite_number [get_property PERIOD $main_clock] "SoC clock period"]
    if {$actual_period <= 0 || $actual_period > 6.667001} {
        error "The SoC clock period exceeds the 6.667 ns requirement"
    }
    opt_design
    place_design
    phys_opt_design
    route_design
    set routed_dir [file join $out_dir routed]
    soc_reports::write $routed_dir
    write_checkpoint -force [file join $routed_dir soc_top_routed.dcp]
    report_route_status -file [file join $routed_dir soc_top_route_status.rpt]
    # 即使时序条件未满足，也保存实际测量结果及源码指纹。
    set check_status [catch {timing_checks::check_implementation $routed_dir} check_message check_options]
    if {[file isfile [file join $routed_dir implementation_checks.tsv]]} {
        puts [exec python3 $report_helper summarize --manifest $source_manifest \
            --directory $routed_dir --stage routed]
    }
    if {$check_status} { return -options $check_options $check_message }
    soc_reports::check_array $routed_dir 16
}
