# 原生 RTL 综合和布局布线共用的端点与资源报告。
source [file join [file dirname [file normalize [info script]]] .. .. fpga vivado tflm_ai_dsa_soc scripts timing_checks.tcl]

namespace eval soc_reports {
    variable dsp_check_dir [file normalize [file join [file dirname [info script]] .. .. test pe_dsp_boundary]]
}
source [file join $soc_reports::dsp_check_dir check_vivado.tcl]

proc soc_reports::dependency_sources {} {
    variable dsp_check_dir
    return [list [file join $dsp_check_dir check_vivado.tcl] [file join $dsp_check_dir check.py]]
}

proc soc_reports::check_array {directory {size 16}} {
    pe_dsp_boundary::check [file join $directory pe_dsp_boundary] \
        {*u_compute_core/u_systolic_array/*} $size 0 9
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
    report_timing -delay_type max -sort_by group -max_paths 200 -nworst 1 \
        -file [file join $directory ${prefix}_timing_paths.rpt]
    report_timing -delay_type min -sort_by group -max_paths 200 -nworst 1 \
        -file [file join $directory ${prefix}_hold_paths.rpt]
    report_high_fanout_nets -fanout_greater_than 100 -max_nets 200 \
        -file [file join $directory ${prefix}_high_fanout.rpt]
    # 每个捕获时钟分别枚举全部端点，不用前200条路径估算TNS。
    set stream [open [file join $directory ${prefix}_endpoints.tsv] w]
    puts $stream "delay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels"
    foreach clock [get_clocks -quiet] {
        set name [get_property NAME $clock]
        set period [get_property PERIOD $clock]
        foreach delay_type {max min} {
            foreach path [timing_checks::all_endpoint_paths $delay_type $clock] {
                set values [list $delay_type $name $period \
                    [get_property STARTPOINT_PIN $path] [get_property ENDPOINT_PIN $path] \
                    [get_property SLACK $path] [get_property LOGIC_LEVELS $path]]
                puts $stream [join $values \t]
            }
        }
    }
    close $stream
}
