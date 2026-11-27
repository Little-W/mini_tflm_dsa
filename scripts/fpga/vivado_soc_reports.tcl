# 原生 RTL 综合和布局布线共用的端点与资源报告。
source [file join [file dirname [file normalize [info script]]] .. .. fpga vivado tflm_ai_dsa_soc scripts timing_checks.tcl]
source [file join [file dirname [file normalize [info script]]] .. .. fpga vivado tflm_ai_dsa_soc scripts vivado_unique_timing_paths.tcl]

namespace eval soc_reports {
    variable dsp_check_dir [file normalize [file join [file dirname [info script]] .. .. test pe_dsp_boundary]]
    variable unique_timing_helper [file normalize [file join [file dirname [info script]] .. .. fpga vivado tflm_ai_dsa_soc scripts vivado_unique_timing_paths.tcl]]
    variable metrics_dir [file dirname [file normalize [info script]]]
    variable native_clock_definition [dict create]
}
source [file join $soc_reports::dsp_check_dir check_vivado.tcl]

proc soc_reports::dependency_sources {} {
    variable dsp_check_dir
    variable unique_timing_helper
    variable metrics_dir
    return [list [file join $dsp_check_dir check_vivado.tcl] [file join $dsp_check_dir check.py] \
        $unique_timing_helper [file join $metrics_dir netlist_metrics.py] [file join $metrics_dir lut_dependencies.py]]
}

proc soc_reports::graph_record {stream args} {
    foreach value $args {
        if {[regexp {[\t\r\n]} $value]} { error "Connectivity fields must not contain tabs or newlines" }
    }
    puts $stream [join $args \t]
}

proc soc_reports::pin_net {pin} {
    # 统一跨层次的导线名称，使父子层次的连接进入同一个位级图节点。
    set nets [get_nets -segments -top_net_of_hierarchical_group -of_objects $pin]
    if {[llength $nets] > 1} { error "A scalar pin has more than one canonical net: $pin" }
    if {[llength $nets] == 0} { return "" }
    return [get_property NAME [lindex $nets 0]]
}

proc soc_reports::soc_instance {} {
    set cells [get_cells -hierarchical -filter {REF_NAME == soc_top || ORIG_REF_NAME == soc_top}]
    if {[llength $cells] != 1} { error "Expected one complete soc_top instance" }
    return $cells
}

proc soc_reports::primitive_leaves {cells} {
    # 复合存储原语由其内部叶级单元表示，每条导线只保留一个输出驱动。
    set names [dict create]
    set containers [dict create]
    foreach cell $cells {
        set name [get_property NAME $cell]
        if {[dict exists $names $name]} { error "Duplicate primitive cell: $name" }
        dict set names $name $cell
    }
    dict for {name cell} $names {
        set parent $name
        while {[set separator [string last / $parent]] >= 0} {
            set parent [string range $parent 0 [expr {$separator - 1}]]
            if {[dict exists $names $parent]} { dict set containers $parent 1 }
        }
    }
    set leaves [list]
    dict for {name cell} $names {
        if {![dict exists $containers $name]} { lappend leaves $cell }
    }
    return $leaves
}

proc soc_reports::write_connectivity {directory prefix} {
    set destination [file join $directory ${prefix}_connectivity.tsv]
    set temporary ${destination}.tmp
    # 当前测量开始时移除已有结果；完整记录写入并关闭后再发布本次文件。
    file delete -force $destination $temporary
    set stream [open $temporary w]
    try {
        graph_record $stream format vivado_connectivity_v1
        # 原生设计覆盖全部 SoC；板级设计覆盖完整 SoC 实例及其全部边界引脚。
        set all_cells [primitive_leaves [get_cells -hierarchical -filter {IS_PRIMITIVE == 1 || IS_BLACKBOX == 1}]]
        if {$prefix eq "soc_top"} {
            set design_name [get_property NAME [current_design]]
            if {$design_name ne "soc_top"} { error "Native connectivity requires soc_top as the current design" }
            set cells $all_cells
            set ports [get_ports]
            set port_name_property NAME
            graph_record $stream scope soc_top top $design_name 0
        } else {
            set scope [soc_instance]
            set scope_name [get_property NAME $scope]
            set cells [list]
            foreach cell $all_cells {
                # 综合工具可将供电常量移到板级，保留这些固定驱动的定义。
                if {[string first ${scope_name}/ [get_property NAME $cell]] == 0 ||
                    [get_property REF_NAME $cell] in {VCC GND}} { lappend cells $cell }
            }
            set ports [get_pins -of_objects $scope]
            set port_name_property REF_PIN_NAME
            graph_record $stream scope soc_top instance $scope_name [expr {[llength $all_cells] - [llength $cells]}]
        }
        # 不限制单元或端点数量；黑盒与无法解释的 SoC 单元由后续检查明确拒绝。
        if {[llength $cells] == 0} { error "No primitive cells were found for complete connectivity export" }
        set pin_count 0
        set seen_cells [dict create]
        foreach cell $cells {
            set name [get_property NAME $cell]
            if {[dict exists $seen_cells $name]} { error "Duplicate primitive cell: $name" }
            dict set seen_cells $name 1
            set kind [get_property REF_NAME $cell]
            set blackbox [get_property IS_BLACKBOX $cell]
            if {$blackbox ni {0 1}} { error "Missing primitive black-box status: $name" }
            set pins [get_pins -of_objects $cell]
            if {[llength $pins] == 0} { error "Primitive cell has no enumerated pins: $name" }
            graph_record $stream cell $name $kind $blackbox [llength $pins]
            set parameters {}
            if {[regexp {^LUT([1-6]|6_2)$} $kind]} { set parameters {INIT} }
            if {$kind eq "DSP48E1"} {
                set parameters {AREG ACASCREG BREG BCASCREG CREG DREG ADREG MREG PREG \
                    INMODEREG OPMODEREG ALUMODEREG CARRYINREG CARRYINSELREG \
                    A_INPUT B_INPUT USE_MULT USE_DPORT USE_SIMD}
            }
            foreach parameter $parameters {
                set value [get_property $parameter $cell]
                if {$value eq ""} { error "Missing primitive parameter $name/$parameter" }
                if {$parameter eq "USE_DPORT"} {
                    if {![string is boolean -strict $value]} { error "Invalid boolean parameter $name/$parameter" }
                    set value [expr {$value ? "TRUE" : "FALSE"}]
                }
                graph_record $stream parameter $name $parameter $value
            }
            # 记录可选输入反相属性，防止将具有反相控制的 DSP 解释为固定 ALU 模式。
            if {$kind eq "DSP48E1"} {
                set properties [list_property $cell]
                foreach parameter {IS_OPMODE_INVERTED IS_INMODE_INVERTED} {
                    if {$parameter in $properties} {
                        graph_record $stream parameter $name $parameter [get_property $parameter $cell]
                    }
                }
            }
            foreach pin $pins {
                graph_record $stream pin $name [get_property REF_PIN_NAME $pin] \
                    [get_property DIRECTION $pin] [pin_net $pin]
                incr pin_count
            }
        }
        foreach port $ports {
            graph_record $stream port [get_property $port_name_property $port] [get_property DIRECTION $port] [pin_net $port]
        }
        # 完成记录独立列出原语、引脚和端口数量；部分输出不会被当作完整图。
        graph_record $stream complete [llength $cells] $pin_count [llength $ports]
        close $stream
        set stream ""
        file rename -force $temporary $destination
    } finally {
        if {$stream ne ""} { close $stream }
        file delete -force $temporary
    }
}

proc soc_reports::define_core_clock {frequency_mhz} {
    variable native_clock_definition
    set frequency [timing_checks::finite_number $frequency_mhz "SoC clock frequency"]
    if {$frequency <= 0} { error "SoC clock frequency must be positive" }
    set ports [get_ports clk]
    if {[llength $ports] != 1} { error "Expected one native SoC clock port" }
    set period [expr {1000.0 / $frequency}]
    create_clock -name clk -period $period $ports
    set native_clock_definition [dict create object [get_property NAME $ports] \
        frequency_mhz $frequency period_ns $period]
}

proc soc_reports::clocks_at_object {object} {
    set clocks [get_clocks -of_objects $object]
    if {[llength $clocks] == 0} {
        set nets [get_nets -segments -of_objects $object]
        if {[llength $nets] != 0} { set clocks [get_clocks -of_objects $nets] }
    }
    return [lsort -unique $clocks]
}

proc soc_reports::write_core_clock {directory prefix} {
    variable native_clock_definition
    set fields {clock period_ns object clock_kind definition_frequency_mhz definition_period_ns \
        source_pin source_cell source_ref soc_clock_pin same_source master_clock master_period_ns \
        master_is_generated multiply_by divide_by mmcm_input_period_ns mmcm_feedback_multiplier \
        mmcm_input_divider mmcm_output_divider}
    set stream [open [file join $directory ${prefix}_core_clock.tsv] w]
    try {
        puts $stream [join $fields \t]
        set values [dict create]
        if {$prefix eq "soc_top"} {
            set objects [get_ports clk]
            if {[llength $objects] != 1} { error "Expected one SoC core clock object" }
            set clocks [clocks_at_object $objects]
            if {[llength $clocks] != 1} { error "Expected one native SoC clock" }
            if {[get_property IS_GENERATED $clocks] ne "0"} { error "Native SoC clock must be primary" }
            dict set values clock_kind primary
            dict set values same_source 1
            dict set values source_pin [get_property NAME $objects]
            dict set values soc_clock_pin [get_property NAME $objects]
            if {[dict exists $native_clock_definition object] &&
                [dict get $native_clock_definition object] eq [get_property NAME $objects]} {
                dict set values definition_frequency_mhz [dict get $native_clock_definition frequency_mhz]
                dict set values definition_period_ns [dict get $native_clock_definition period_ns]
            }
        } else {
            # 通过模块类型寻找 SoC，沿其时钟输入反向寻找实际 MMCM 输出。
            set soc_cells [soc_instance]
            set soc_pins [get_pins -of_objects $soc_cells -filter {REF_PIN_NAME == clk}]
            if {[llength $soc_pins] != 1} { error "Expected one SoC clock input pin" }
            set fanin_names [get_property NAME [all_fanin -flat $soc_pins]]
            set candidates [list]
            foreach cell [get_cells -hierarchical -filter {REF_NAME == MMCME2_ADV || REF_NAME == MMCME2_BASE}] {
                foreach pin [get_pins -of_objects $cell -filter {DIRECTION == OUT && REF_PIN_NAME =~ CLKOUT*}] {
                    if {[get_property NAME $pin] in $fanin_names} { lappend candidates [list $cell $pin] }
                }
            }
            if {[llength $candidates] != 1} { error "Expected one MMCM output driving the SoC clock" }
            lassign [lindex $candidates 0] cell objects
            set clocks [get_clocks -of_objects $objects]
            if {[llength $clocks] != 1} { error "Expected one clock at the MMCM output" }
            if {[get_property IS_GENERATED $clocks] ne "1"} { error "MMCM output clock must be generated" }
            set source_name [get_property NAME $objects]
            if {$source_name ni [get_property SOURCE_PINS $clocks]} {
                error "Generated clock source does not match the selected MMCM output"
            }
            set sink_clocks [clocks_at_object $soc_pins]
            if {[llength $sink_clocks] != 1 ||
                [get_property NAME $sink_clocks] ne [get_property NAME $clocks]} {
                error "SoC clock input and MMCM output do not share one timing clock"
            }
            set master [get_clocks [get_property MASTER_CLOCK $clocks]]
            if {[llength $master] != 1} { error "Expected one MMCM master clock" }
            set input_pins [list]
            foreach pin [get_pins -of_objects $cell -filter {REF_PIN_NAME == CLKIN1 || REF_PIN_NAME == CLKIN2}] {
                set input_clocks [clocks_at_object $pin]
                if {[llength $input_clocks] == 1 &&
                    [get_property NAME $input_clocks] eq [get_property NAME $master]} {
                    lappend input_pins $pin
                }
            }
            if {[llength $input_pins] != 1} { error "Expected one MMCM input associated with its master clock" }
            set input_period_property [get_property REF_PIN_NAME $input_pins]_PERIOD
            if {![regexp {^CLKOUT([0-6])B?$} [get_property REF_PIN_NAME $objects] -> output_index]} {
                error "Unsupported MMCM clock output pin"
            }
            set output_divider_property CLKOUT${output_index}_DIVIDE
            if {$output_index == 0} { append output_divider_property _F }
            dict set values clock_kind mmcm
            dict set values same_source 1
            dict set values source_pin $source_name
            dict set values source_cell [get_property NAME $cell]
            dict set values source_ref [get_property REF_NAME $cell]
            dict set values soc_clock_pin [get_property NAME $soc_pins]
            dict set values master_clock [get_property NAME $master]
            dict set values master_period_ns [get_property PERIOD $master]
            dict set values master_is_generated [get_property IS_GENERATED $master]
            dict set values multiply_by [get_property MULTIPLY_BY $clocks]
            dict set values divide_by [get_property DIVIDE_BY $clocks]
            dict set values mmcm_input_period_ns [get_property $input_period_property $cell]
            dict set values mmcm_feedback_multiplier [get_property CLKFBOUT_MULT_F $cell]
            dict set values mmcm_input_divider [get_property DIVCLK_DIVIDE $cell]
            dict set values mmcm_output_divider [get_property $output_divider_property $cell]
        }
        dict set values clock [get_property NAME $clocks]
        dict set values period_ns [get_property PERIOD $clocks]
        dict set values object [get_property NAME $objects]
        set row [list]
        foreach field $fields {
            lappend row [expr {[dict exists $values $field] ? [dict get $values $field] : ""}]
        }
        graph_record $stream {*}$row
    } finally {
        close $stream
    }
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

proc soc_reports::write_setup_endpoints {directory prefix {count 2000} {query_limit 2000}} {
    set paths [get_timing_paths -delay_type max -nworst 1 -max_paths $query_limit -no_report_unconstrained]
    set ranked {}
    foreach path $paths {
        set slack [timing_checks::finite_number [get_property SLACK $path] "path slack"]
        set endpoint [get_property NAME [get_property ENDPOINT_PIN $path]]
        if {$endpoint eq ""} { error "Timing path has no endpoint pin" }
        lappend ranked [list $slack $endpoint $path]
    }
    set seen [dict create]
    set selected {}
    foreach entry [lsort -real -index 0 $ranked] {
        set endpoint [lindex $entry 1]
        if {[dict exists $seen $endpoint]} { continue }
        dict set seen $endpoint 1
        lappend selected $entry
        if {[llength $selected] == $count} { break }
    }
    set report [open [file join $directory ${prefix}_timing_paths.rpt] w]
    set table [open [file join $directory ${prefix}_setup_unique_endpoints.tsv] w]
    set endpoints [open [file join $directory ${prefix}_endpoints.tsv] w]
    set module_table [open [file join $directory ${prefix}_module_endpoints.tsv] w]
    set module_report [open [file join $directory ${prefix}_module_paths.rpt] w]
    set level_report [open [file join $directory ${prefix}_logic_levels.rpt] w]
    try {
        puts $report "Vivado setup paths, $count worst paths deduplicated by endpoint pin"
        puts $report "requested=$count query_limit=$query_limit returned=[llength $paths] unique_reported=[llength $selected]"
        puts $report "Deduplication keeps one worst path per endpoint pin; paths are sorted by slack."
        if {[llength $selected] < $count && [llength $paths] >= $query_limit} {
            puts $report "QUERY LIMIT REACHED: endpoint sample may be incomplete."
        }
        puts $table "endpoint\tslack_ns"
        puts $endpoints "delay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels"
        puts $module_table "scope\tdelay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels"
        puts $module_report "Per-module setup samples are selected from the global worst-path sample."
        puts $module_report "Detailed path reports are indexed in ${prefix}_timing_paths.rpt."
        puts $level_report "Logic-level distribution for the global worst-path sample."
        set scopes [dict create \
            cpu [list {*u_picorv32/*}] \
            axi [list {*g_npu_axi_timing_buffer* *u_cpu_axi_read_pingpong/* *u_cpu_axi_write_pingpong/* *u_axi_sim_ram/*}] \
            control [list {*u_npu_axil_reg_if/* *u_npu_controller/* *u_frame_address/*}] \
            scheduler [list {*g_frame_schedule*u_scheduler/*}] \
            dma [list {*u_block_dma_arbiter/*}] \
            im2col [list {*g_im2col.u_frontend/*}] \
            vector [list {*g_vector_engine.u_engine/*}] \
            compute [list {*u_compute_core/*}] \
            requant [list {*u_vec_requant/*}] \
            ia_loader [list {*u_ia_loader/*}] \
            kernel_loader [list {*u_kernel_loader/*}] \
            ps_storage [list {*u_ps_buffer/*}] \
            shared_storage [list {*g_shared_ia_ps* *u_vector_shared_store/*}]]
        set scope_counts [dict create]
        set level_counts [dict create]
        set index 0
        foreach entry $selected {
            lassign $entry slack endpoint path
            if {[regexp {[\t\r\n]} $endpoint]} { error "Invalid endpoint name" }
            puts $table "$endpoint\t$slack"
            set clock [get_property ENDPOINT_CLOCK $path]
            set clock_name [get_property NAME $clock]
            set period [get_property PERIOD $clock]
            set startpoint [get_property NAME [get_property STARTPOINT_PIN $path]]
            set levels [get_property LOGIC_LEVELS $path]
            set values [list max $clock_name $period $startpoint $endpoint $slack $levels]
            puts $endpoints [join $values \t]
            dict incr level_counts $levels
            set path_index [incr index]
            puts $report "===== Endpoint $path_index: $endpoint ====="
            dict for {scope patterns} $scopes {
                set matches 0
                foreach pattern $patterns {
                    if {[string match $pattern $endpoint]} { set matches 1; break }
                }
                if {$matches} {
                    puts $module_table [join [linsert $values 0 $scope] \t]
                    puts $module_report "$scope\t$path_index\t$endpoint\t$slack\t$levels"
                    dict incr scope_counts $scope
                }
            }
        }
        dict for {scope patterns} $scopes {
            if {![dict exists $scope_counts $scope]} { dict set scope_counts $scope 0 }
        }
        puts $module_report "\nScope sample counts:"
        dict for {scope count} $scope_counts { puts $module_report "$scope\t$count" }
        puts $level_report "logic_levels\tpaths"
        foreach levels [lsort -integer [dict keys $level_counts]] {
            puts $level_report "$levels\t[dict get $level_counts $levels]"
        }
        puts $report "\n[report_timing -of_objects [lmap entry $selected {lindex $entry 2}] \
            -path_type full_clock_expanded -return_string]"
    } finally {
        close $report
        close $table
        close $endpoints
        close $module_table
        close $module_report
        close $level_report
    }
}

proc soc_reports::write {directory {prefix soc_top}} {
    file mkdir $directory
    report_utilization -file [file join $directory ${prefix}_utilization.rpt]
    report_utilization -hierarchical -file [file join $directory ${prefix}_utilization_hier.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
        -file [file join $directory ${prefix}_timing_summary.rpt]
    write_core_clock $directory $prefix
    write_setup_endpoints $directory $prefix 2000 2000
}
