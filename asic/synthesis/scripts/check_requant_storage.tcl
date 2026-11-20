# 量化输出缓冲使用已链接的 SRAM 宏，数据阵列不进入标准单元映射。
proc check_requant_storage {report_path} {
    set buffers [get_cells -quiet -hierarchical -filter {
        is_hierarchical == true && ref_name =~ *requant_group_buffer*
    }]
    set cells [get_cells -quiet -hierarchical *]
    set report [open $report_path w]
    puts $report "buffer\tmacro_instances\tphysical_storage_bits\tregfile_instances"
    set errors {}
    foreach_in_collection buffer $buffers {
        set buffer_name [get_object_name $buffer]
        set prefix "${buffer_name}/"
        set macro_count 0
        set physical_bits 0
        set regfile_count 0
        foreach_in_collection cell $cells {
            set cell_name [get_object_name $cell]
            if {[string first $prefix $cell_name] != 0} {continue}
            set reference [get_attribute $cell ref_name]
            switch -- $reference {
                RAMTP128X16 {
                    incr macro_count
                    incr physical_bits 2048
                }
                RAMTP1024X16 {
                    incr macro_count
                    incr physical_bits 16384
                }
            }
            if {[string match -nocase *regfile* $reference]} {
                incr regfile_count
            }
        }
        puts $report "$buffer_name\t$macro_count\t$physical_bits\t$regfile_count"
        if {$macro_count == 0 || $regfile_count != 0} {
            lappend errors "$buffer_name: SRAM macros=$macro_count, regfile instances=$regfile_count"
        }
    }
    close $report
    if {[llength $errors] != 0} {
        error "Requantization storage requires ASIC SRAM mapping: [join $errors {; }]. Elaborate current RTL with ASIC_SRAM enabled."
    }
    return [sizeof_collection $buffers]
}
