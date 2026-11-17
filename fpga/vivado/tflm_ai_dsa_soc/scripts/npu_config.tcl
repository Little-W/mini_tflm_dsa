# Read literal Make configuration and provide Vivado hardware parameters.
namespace eval npu_config {
    variable defaults [dict create \
        NPU_AXI_DATA_WIDTH 64 SHARED_BANK_BYTES 2048 SHARED_BANK_COUNT 7 \
        PCR_ENGINE 1 PS_POOL_BYTES 12288 PS_FORCE_RAW 0]
}

proc npu_config::repository_root {script_directory} {
    set parent [file normalize [file join $script_directory ..]]
    if {[file isfile [file join $script_directory export_sources.tcl]]} {
        return $parent
    }
    return [file normalize [file join $parent .. .. ..]]
}

proc npu_config::integer_literal {name text} {
    set value [string trim $text]
    if {![regexp {^[+-]?(0[xX][0-9a-fA-F]+|[0-9]+)$} $value]} {
        error "$name must be an integer literal"
    }
    if {[regexp {^[+-]?0[xX]} $value]} {
        set result [expr {$value + 0}]
    } else {
        scan $value %d result
    }
    return $result
}

proc npu_config::validate {values} {
    foreach {name allowed} {
        NPU_AXI_DATA_WIDTH {32 64}
        SHARED_BANK_BYTES {1024 2048 4096}
        SHARED_BANK_COUNT {6 7 8 9}
        PCR_ENGINE {0 1}
        PS_FORCE_RAW {0 1}
    } {
        if {[dict get $values $name] ni $allowed} {
            error "$name must be one of [join $allowed {, }]"
        }
    }
    set pool [dict get $values PS_POOL_BYTES]
    if {$pool < 64 || $pool % 64 != 0} {
        error "PS_POOL_BYTES must be a positive multiple of 64"
    }
    return $values
}

proc npu_config::read {root {config_path ""}} {
    variable defaults
    if {$config_path eq ""} {
        if {[info exists ::env(NPU_CONFIG)] && $::env(NPU_CONFIG) ne ""} {
            set config_path $::env(NPU_CONFIG)
        } else {
            set config_path [file join $root config npu.mk]
        }
    }
    set config_path [file normalize $config_path]
    set input [open $config_path r]
    try {
        set contents [::read $input]
    } finally {
        close $input
    }
    set values $defaults
    set seen [dict create]
    set line_number 0
    foreach line [split $contents "\n"] {
        incr line_number
        set source [string trim [lindex [split $line #] 0]]
        if {$source eq ""} { continue }
        if {[regexp {^(?:(?:export|override)\s+)?([A-Z][A-Z0-9_]*)\s*(\?=|:=|=)\s*(.*?)\s*$} $source -> name operator value]} {
            if {![dict exists $defaults $name]} { continue }
            if {[dict exists $seen $name]} {
                error "$config_path:$line_number: duplicate assignment for $name"
            }
            dict set seen $name 1
            dict set values $name [integer_literal $name $value]
        } elseif {[regexp {^(?:(?:export|override)\s+)?([A-Z][A-Z0-9_]*)\s*} $source -> name] && [dict exists $defaults $name]} {
            error "$config_path:$line_number: unsupported assignment syntax for $name"
        }
    }
    foreach name {NPU_AXI_DATA_WIDTH SHARED_BANK_BYTES SHARED_BANK_COUNT} {
        if {[info exists ::env($name)]} {
            dict set values $name [integer_literal $name $::env($name)]
        }
    }
    dict set values config_path $config_path
    return [validate $values]
}

proc npu_config::generics {values} {
    validate $values
    return [list \
        BUS_WIDTH=[dict get $values NPU_AXI_DATA_WIDTH] \
        SHARED_BANK_BYTES=[dict get $values SHARED_BANK_BYTES] \
        SHARED_BANK_COUNT=[dict get $values SHARED_BANK_COUNT]]
}

proc npu_config::write_snapshot {path values} {
    variable defaults
    validate $values
    file mkdir [file dirname $path]
    set output [open $path w]
    try {
        puts $output {# Hardware settings for the exported Vivado project.}
        foreach name [dict keys $defaults] {
            puts $output "$name := [dict get $values $name]"
        }
    } finally {
        close $output
    }
}
