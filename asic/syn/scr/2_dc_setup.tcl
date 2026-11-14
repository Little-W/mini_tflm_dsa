set std_db_path  "$STD_DB_PATH"
set mem_db_path  "$MEM_DB_PATH"
set sync_db_path "$SYNC_DB_PATH"
set io_db_path   "$IO_DB_PATH"
set lpk_db_path  "$LPK_DB_PATH"
set afe_db_path  "$AFE_DB_PATH"

set std_db_list  "$STD_DB_LIST"
set mem_db_list  "$MEM_DB_LIST"
set sync_db_list "$SYNC_DB_LIST"
set io_db_list   "$IO_DB_LIST"
set lpk_db_list  "$LPK_DB_LIST"
set afe_db_list  "$AFE_DB_LIST"

foreach path [list $std_db_path $mem_db_path $sync_db_path $io_db_path $lpk_db_path $afe_db_path] {
    if {$path ne "" && ![file isdirectory $path]} {
        puts "Warning: library path does not exist: $path"
    }
}

set search_path [concat $std_db_path $afe_db_path $mem_db_path $search_path $sync_db_path $io_db_path $lpk_db_path]
set target_library [concat $std_db_list $afe_db_list $mem_db_list $io_db_list $lpk_db_list]
set synthetic_library [list dw_foundation.sldb]
set link_library [concat * $target_library $synthetic_library]

puts "Library setup:"
puts "  search_path      = $search_path"
puts "  target_library   = $target_library"
puts "  synthetic_library= $synthetic_library"
puts "  link_library     = $link_library"
