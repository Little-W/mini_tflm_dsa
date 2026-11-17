# Convert CPU word images into the physical RAM word format used by fpga_top.
namespace eval cpu_memory {}

proc cpu_memory::read_cpu_words {path depth} {
    if {![string is integer -strict $depth] || $depth <= 0} {
        error "CPU_MEM_DP must be a positive count of 32-bit CPU words"
    }
    set input [open $path r]
    try {
        set text [::read $input]
    } finally {
        close $input
    }
    regsub -all {(?s)/\*.*?\*/} $text { } text
    regsub -all {//[^\n\r]*} $text { } text
    set words [lrepeat $depth 00000000]
    set address 0
    foreach token [regexp -all -inline {\S+} $text] {
        set token [string map {_ ""} $token]
        if {[regexp {^@([0-9a-fA-F]+)$} $token -> hex]} {
            set address [expr "0x$hex"]
        } elseif {[regexp {^[0-9a-fA-F]{1,8}$} $token]} {
            if {$address >= $depth} {
                error "CPU image address $address exceeds CPU_MEM_DP=$depth: $path"
            }
            lset words $address [format %08x [expr "0x$token"]]
            incr address
        } else {
            error "CPU image requires 32-bit hexadecimal words and @word addresses: $path"
        }
        if {$address > $depth} {
            error "CPU image address $address exceeds CPU_MEM_DP=$depth: $path"
        }
    }
    return $words
}

proc cpu_memory::write_words {path words} {
    file mkdir [file dirname $path]
    set output [open $path w]
    try {
        puts $output [join $words "\n"]
    } finally {
        close $output
    }
}

proc cpu_memory::write_images {source cpu32_path native_path depth bus_width} {
    if {$bus_width ni {32 64}} { error "CPU RAM data width must be 32 or 64" }
    set words_per_row [expr {$bus_width / 32}]
    if {![string is integer -strict $depth] || $depth <= 0 || $depth % $words_per_row != 0} {
        error "CPU_MEM_DP must contain an integral number of $bus_width-bit RAM rows"
    }
    set words [read_cpu_words $source $depth]
    if {$bus_width == 64} {
        set native [list]
        foreach {low high} $words { lappend native "$high$low" }
    } else {
        set native $words
    }
    write_words $cpu32_path $words
    write_words $native_path $native
    return [dict create cpu32_path [file normalize $cpu32_path] \
        native_path [file normalize $native_path] cpu_words $depth \
        physical_rows [llength $native] word_bits $bus_width]
}
