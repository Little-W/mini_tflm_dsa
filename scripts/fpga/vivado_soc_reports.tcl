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
    # Record the inferred DSP cascade without enforcing a logic-depth target;
    # routed 150 MHz setup and hold timing are the acceptance criteria.
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

proc soc_reports::write {directory {prefix soc_top}} {
    file mkdir $directory
    report_utilization -file [file join $directory ${prefix}_utilization.rpt]
    report_utilization -hierarchical -file [file join $directory ${prefix}_utilization_hier.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
        -file [file join $directory ${prefix}_timing_summary.rpt]
    unique_timing_paths::write [file join $directory ${prefix}_timing_paths.rpt] max
    unique_timing_paths::write [file join $directory ${prefix}_hold_paths.rpt] min
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
