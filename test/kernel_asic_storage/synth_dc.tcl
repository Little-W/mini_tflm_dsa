set root /media/proj_tmp/tflm_ai_dsa
set search_path [concat $search_path [list $root/build/dc_current_fpga_raw_50/libs /media/6/IC/lib/SMIC40_2025/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v]]
set target_library {scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db}
set link_library [concat * $target_library {RAMTP128X16_tt_1p10v_1p10v_25c.db RAMTP1024X16_tt_1p10v_1p10v_25c.db} dw_foundation.sldb]
set_host_options -max_cores 1
analyze -format sverilog -define {ASIC_SRAM ASIC_SYNTHESIS SYNTHESIS} [list $root/asic/rtl/smic40_sram_1r1w.sv $root/rtl/common/regfile.v $root/rtl/npu/loaders/kernel_loader_buffer.sv $root/test/kernel_asic_storage/synth_top.sv]
elaborate kernel_asic_storage_synth_top
link
create_clock -name clk -period 10 [get_ports clk]
set_input_delay 1 -clock clk [remove_from_collection [all_inputs] [get_ports clk]]
set_output_delay 1 -clock clk [all_outputs]
set_fix_multiple_port_nets -all -exclude_clock_network
compile -map_effort medium -area_effort low -power_effort none
report_area -hierarchy > area.rpt
report_timing -delay_type max -max_paths 5 > timing.rpt
check_design > check_design.rpt
set fd [open macro_count.txt w]
puts $fd [sizeof_collection [get_cells -hierarchical -filter {ref_name =~ RAMTP*}]]
close $fd
write -format verilog -hierarchy -output mapped.v
exit
