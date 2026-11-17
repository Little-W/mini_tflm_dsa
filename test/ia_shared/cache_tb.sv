module ia_shared_cache_tb #(
    parameter int BANK_BYTES=2048,
    parameter int BANK_COUNT=7,
    localparam int CACHE_BLOCKS=4*BANK_BYTES/512,
    localparam int SLOT_BLOCKS=2*CACHE_BLOCKS,
    localparam int SLOT_BITS=$clog2(SLOT_BLOCKS),
    localparam int WORD_BITS=$clog2(BANK_COUNT*BANK_BYTES/16),
    localparam int BANK_COUNT_BITS=$clog2(BANK_COUNT+1)
) (
    input logic clk, rst_n,
    input logic compact_mode,
    input logic signed [15:0] compact_offset,
    input logic [31:0] cfg_cache_blocks,
    input logic cfg_valid,
    input logic [BANK_COUNT_BITS-1:0] cfg_ia_banks,
    input logic [SLOT_BITS-1:0] wr_slot,
    input logic [3:0] wr_row, wr_col_base,
    input logic signed [15:0] wr_data [0:3],
    input logic wr_valid [0:3],
    input logic wr_use_16bits,
    input logic l1_start,
    input logic [SLOT_BITS-1:0] l1_slot_start, l1_slot_end,
    input logic l1_is_init, l1_calc_done,
    input logic [4:0] slot_rows [0:SLOT_BLOCKS-1],
    output logic signed [15:0] shared_out [0:15], local_out [0:15],
    output logic shared_valid, shared_init, shared_final,
    output logic shared_tile_done, shared_l1_done, shared_tile_start,
    output logic local_valid, local_init, local_final,
    output logic local_tile_done, local_l1_done, local_tile_start,
    output logic capacity_fault,
    output logic [1:0] ia_write_en, ia_read_en,
    output logic [WORD_BITS-1:0] ia_write_addr [0:1], ia_read_addr [0:1],
    output logic [127:0] ia_write_data [0:1],
    output logic [15:0] ia_write_mask [0:1],
    input logic [3:0] ps_read_en, ps_write_en,
    input logic [WORD_BITS-1:0] ps_read_addr [0:3], ps_write_addr [0:3],
    input logic [127:0] ps_write_data [0:3],
    output logic [127:0] ps_read_data [0:3],
    output logic [3:0] physical_read_count, physical_write_count,
    output logic physical_address_collision
);
    logic [127:0] ia_read_data [0:1];

    ia_loader_cache_mgr #(
        .DATA_WIDTH(16), .SIZE(16), .BUS_WIDTH(32), .CACHE_BLOCKS(CACHE_BLOCKS),
        .COMPACT_S8(1), .EXTERNAL_RAM(1), .RAM_WORD_ADDR_WIDTH(WORD_BITS)
    ) u_shared_manager (
        .clk, .rst_n, .compact_mode, .compact_offset, .cfg_cache_blocks,
        .ram_port_wr_en(ia_write_en), .ram_port_wr_addr(ia_write_addr),
        .ram_port_wr_data(ia_write_data), .ram_port_wr_mask(ia_write_mask),
        .ram_port_rd_en(ia_read_en), .ram_port_rd_addr(ia_read_addr),
        .ram_port_rd_data(ia_read_data),
        .wr_slot, .wr_row, .wr_col_base, .wr_data, .wr_valid, .wr_use_16bits,
        .l1_start, .l1_slot_start, .l1_slot_end, .l1_is_init, .l1_calc_done,
        .slot_rows, .tile_done(shared_tile_done), .l1_done(shared_l1_done),
        .ia_tile_start(shared_tile_start), .ia_out(shared_out),
        .ia_row_valid(shared_valid), .ia_is_init_data(shared_init),
        .ia_calc_done(shared_final)
    );

    ia_loader_cache_mgr #(
        .DATA_WIDTH(16), .SIZE(16), .BUS_WIDTH(32), .CACHE_BLOCKS(CACHE_BLOCKS),
        .COMPACT_S8(1), .EXTERNAL_RAM(0), .RAM_WORD_ADDR_WIDTH(WORD_BITS)
    ) u_local_manager (
        .clk, .rst_n, .compact_mode, .compact_offset, .cfg_cache_blocks,
        .ram_port_wr_en(), .ram_port_wr_addr(), .ram_port_wr_data(),
        .ram_port_wr_mask(), .ram_port_rd_en(), .ram_port_rd_addr(),
        .ram_port_rd_data('{default:'0}),
        .wr_slot, .wr_row, .wr_col_base, .wr_data, .wr_valid, .wr_use_16bits,
        .l1_start, .l1_slot_start, .l1_slot_end, .l1_is_init, .l1_calc_done,
        .slot_rows, .tile_done(local_tile_done), .l1_done(local_l1_done),
        .ia_tile_start(local_tile_start), .ia_out(local_out),
        .ia_row_valid(local_valid), .ia_is_init_data(local_init),
        .ia_calc_done(local_final)
    );

    ia_ps_shared_ram #(.TOTAL_BYTES(BANK_BYTES*BANK_COUNT), .BANK_BYTES(BANK_BYTES)) u_shared_ram (
        .clk, .rst_n, .cfg_valid, .cfg_ia_banks, .capacity_fault,
        .ia_read_en, .ia_read_addr, .ia_read_data,
        .ia_write_en, .ia_write_addr, .ia_write_data, .ia_write_mask,
        .ps_read_en, .ps_read_addr, .ps_read_data,
        .ps_write_en, .ps_write_addr, .ps_write_data
    );

    always_comb begin
        physical_read_count = 0;
        physical_write_count = 0;
        physical_address_collision = 0;
        for (int bank = 0; bank < BANK_COUNT; bank++) begin
            physical_read_count += 4'(u_shared_ram.read_en[bank]);
            physical_write_count += 4'(u_shared_ram.write_en[bank]);
            physical_address_collision |= u_shared_ram.read_en[bank] &&
                u_shared_ram.write_en[bank] &&
                u_shared_ram.read_addr[bank] == u_shared_ram.write_addr[bank];
        end
    end
endmodule
