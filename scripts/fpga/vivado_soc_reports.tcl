# 原生 RTL 综合和布局布线共用的端点与资源报告。
source [file join [file dirname [file normalize [info script]]] .. .. fpga vivado tflm_ai_dsa_soc scripts timing_checks.tcl]
source [file join [file dirname [file normalize [info script]]] .. .. fpga vivado tflm_ai_dsa_soc scripts vivado_unique_timing_paths.tcl]

namespace eval soc_reports {
    variable dsp_check_dir [file normalize [file join [file dirname [info script]] .. .. test pe_dsp_boundary]]
    variable unique_timing_helper [file normalize [file join [file dirname [info script]] .. .. fpga vivado tflm_ai_dsa_soc scripts vivado_unique_timing_paths.tcl]]
}
source [file join $soc_reports::dsp_check_dir check_vivado.tcl]

proc soc_reports::dependency_sources {} {
    variable dsp_check_dir
    variable unique_timing_helper
    return [list [file join $dsp_check_dir check_vivado.tcl] [file join $dsp_check_dir check.py] $unique_timing_helper]
}

proc soc_reports::check_array {directory {size 16}} {
    # 记录综合推断的 DSP 级联，使用布线后 150 MHz 建立与保持时间检查频率。
    pe_dsp_boundary::check [file join $directory pe_dsp_boundary] \
        {*u_compute_core/u_systolic_array/*} $size 100000 100000
}

proc soc_reports::record {stream key value} {
    if {[regexp {[\t\r\n]} $key] || [regexp {[\t\r\n]} $value]} {
        error "Input metadata must not contain tabs or newlines"
    }
    puts $stream "$key\t$value"
}

proc soc_reports::snapshot {directory helper metadata sources include_dirs} {
    set inputs [file join $directory inputs.tsv]
    set stream [open $inputs w]
    dict for {key value} $metadata { record $stream $key $value }
    foreach path [lsort -unique $sources] { record $stream source [file normalize $path] }
    foreach path $include_dirs { record $stream include_dir [file normalize $path] }
    close $stream
    set manifest [file join $directory source_manifest.json]
    puts [exec python3 $helper snapshot --inputs $inputs --out $manifest]
    return $manifest
}

proc soc_reports::write_module_paths {directory prefix {count 20}} {
    # 每组保存不同终点的最差路径，使各模块都能参与下一轮时序分析。
    set scopes [dict create \
        cpu {*u_picorv32/*} \
        axi {*g_npu_axi_timing_buffer* *u_cpu_axi_read_pingpong/* *u_cpu_axi_write_pingpong/* *u_axi_sim_ram/*} \
        control {*u_npu_axil_reg_if/* *u_npu_controller/* *u_frame_address/*} \
        scheduler {*g_frame_schedule*u_scheduler/*} \
        dma {*u_block_dma_arbiter/*} \
        im2col {*g_im2col.u_frontend/*} \
        vector {*g_vector_engine.u_engine/*} \
        compute {*u_compute_core/*} \
        requant {*u_vec_requant/*} \
        ia_loader {*u_ia_loader/*} \
        kernel_loader {*u_kernel_loader/*} \
        ps_storage {*u_ps_buffer/*} \
        shared_storage {*g_shared_ia_ps* *u_vector_shared_store/*}]
    set table [open [file join $directory ${prefix}_module_endpoints.tsv] w]
    set report [open [file join $directory ${prefix}_module_paths.rpt] w]
    try {
        puts $table "scope\tdelay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels"
        puts $report "Vivado per-module timing samples; at most $count distinct endpoints per delay type."
        puts $report "Scopes can overlap. Global setup and hold results remain in the timing summary."
        dict for {scope patterns} $scopes {
            set sinks {}
            foreach pattern $patterns {
                foreach cell [get_cells -hierarchical -quiet -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"] {
                    lappend sinks $cell
                }
            }
            set sinks [lsort -unique $sinks]
            puts $report "\nScope: $scope; sequential cells: [llength $sinks]"
            if {[llength $sinks] == 0} { continue }
            foreach delay_type {max min} {
                set paths [get_timing_paths -delay_type $delay_type -to $sinks \
                    -nworst 1 -max_paths $count -no_report_unconstrained]
                foreach path $paths {
                    set clock [get_property ENDPOINT_CLOCK $path]
                    set values [list $scope $delay_type [get_property NAME $clock] \
                        [get_property PERIOD $clock] [get_property STARTPOINT_PIN $path] \
                        [get_property ENDPOINT_PIN $path] [get_property SLACK $path] \
                        [get_property LOGIC_LEVELS $path]]
                    puts $table [join $values \t]
                    puts $report "\n[unique_timing_paths::detail [report_timing -of_objects $path -return_string]]"
                }
            }
        }
    } finally {
        close $table
        close $report
    }
}

proc soc_reports::write {directory {prefix soc_top}} {
    file mkdir $directory
    report_utilization -file [file join $directory ${prefix}_utilization.rpt]
    report_utilization -hierarchical -file [file join $directory ${prefix}_utilization_hier.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
        -file [file join $directory ${prefix}_timing_summary.rpt]
    unique_timing_paths::write [file join $directory ${prefix}_timing_paths.rpt] max
    unique_timing_paths::write [file join $directory ${prefix}_hold_paths.rpt] min
    write_module_paths $directory $prefix
    # 统计最差一万条建立时间路径的组合级数分布；该表保留明确的采样范围。
    report_design_analysis -logic_level_distribution -logic_level_dist_paths 10000 \
        -file [file join $directory ${prefix}_logic_levels.rpt]
    report_high_fanout_nets -fanout_greater_than 100 -max_nets 200 \
        -file [file join $directory ${prefix}_high_fanout.rpt]
    # 限量样本只用于诊断；完整的 WNS/TNS 和端点数量以原生汇总报告为准。
    set stream [open [file join $directory ${prefix}_endpoints.tsv] w]
    puts $stream "delay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels"
    foreach clock [get_clocks -quiet] {
        set name [get_property NAME $clock]
        set period [get_property PERIOD $clock]
        foreach delay_type {max min} {
            foreach path [get_timing_paths -delay_type $delay_type -to $clock -nworst 1 -max_paths 100 -no_report_unconstrained] {
                set values [list $delay_type $name $period \
                    [get_property STARTPOINT_PIN $path] [get_property ENDPOINT_PIN $path] \
                    [get_property SLACK $path] [get_property LOGIC_LEVELS $path]]
                puts $stream [join $values \t]
            }
        }
    }
    close $stream
}
