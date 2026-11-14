// Lossless, ordered 16-lane INT32 partial-sum storage.
// A short record contains 3 x 128-bit sectors (16 signed low-24 values).
// A long record adds one 128-bit sector holding ALL sixteen high bytes.
// One mode bit per logical row is charged separately. No arithmetic truncation.
// Four 1R1W banks accept one vector and replay one vector per cycle.
// Capacity overflow is an explicit sticky error; this prototype has no spill DMA.
module ps_sector_store #(
    parameter integer LOGICAL_ROWS = 4607,
    parameter integer POOL_BYTES = 294848,
    parameter integer ADDR_WIDTH = $clog2(LOGICAL_ROWS),
    parameter bit FAIL_STOP = 1'b1
)(
    input logic clk, rst_n, write_en, read_en,
    input logic [ADDR_WIDTH-1:0] write_addr, read_addr,
    input logic [511:0] write_data,
    output logic [511:0] read_data,
    output logic capacity_fault
);
    localparam integer BANK_DEPTH = POOL_BYTES / 64;
    localparam integer SECTORS = BANK_DEPTH * 4;
    localparam integer PTR_W = $clog2(SECTORS);
    localparam integer BANK_AW = $clog2(BANK_DEPTH);
    localparam integer ROW_W = $clog2(LOGICAL_ROWS);
    localparam integer COUNT_W = $clog2(SECTORS+1);
    (* ram_style="distributed" *) logic long_record [0:LOGICAL_ROWS-1];
    logic [PTR_W-1:0] write_sector, read_sector;
    logic [ROW_W-1:0] write_row, read_row;
    logic [COUNT_W-1:0] used_sectors;
    logic [$clog2(LOGICAL_ROWS+1)-1:0] used_rows;
    logic [383:0] low_bits;
    logic [127:0] high_bits;
    logic [15:0] exception_mask;
    logic encode_long, decode_long, decode_long_q;
    logic [2:0] write_length, read_length;
    logic [1:0] read_phase_q;
    logic write_accept;
    logic [BANK_AW-1:0] bank_wa[4], bank_ra[4];
    logic [127:0] bank_wd[4], bank_rd[4];
    logic bank_we[4], bank_re[4];
    logic [511:0] packet_q;

    always_comb begin
        for (int lane=0; lane<16; lane++) begin
            low_bits[lane*24+:24] = write_data[lane*32+:24];
            high_bits[lane*8+:8] = write_data[lane*32+24+:8];
            exception_mask[lane] = write_data[lane*32+24+:8] != {8{write_data[lane*32+23]}};
        end
    end
    `ifdef GEMMORA_PS_FORCE_RAW
    assign encode_long = 1'b1;
`else
    assign encode_long = |exception_mask;
`endif
    assign decode_long = long_record[read_row];
    assign write_length = encode_long ? 3'd4 : 3'd3;
    assign read_length = decode_long ? 3'd4 : 3'd3;
    // Do not rely on device-specific read-during-write collision semantics.
    assign write_accept = write_en && !capacity_fault &&
                          (used_rows < $bits(used_rows)'(LOGICAL_ROWS)) &&
                          (encode_long ? (used_sectors <= COUNT_W'(SECTORS-4)) :
                                         (used_sectors <= COUNT_W'(SECTORS-3)));

    // Each bank receives exactly one of the four consecutive sectors.
    // A two-bit phase selects its payload; only the bank-local address may
    // advance by one. Typed narrow arithmetic avoids signed 32-bit modulo,
    // quotient correction and a variable-index write crossbar.
    for (genvar bank=0; bank<4; bank++) begin:g_bank_address
        wire [1:0] write_offset = 2'(bank) - write_sector[1:0];
        wire [1:0] read_offset = 2'(bank) - read_sector[1:0];
        wire [BANK_AW-1:0] write_base = BANK_AW'(write_sector >> 2);
        wire [BANK_AW-1:0] read_base = BANK_AW'(read_sector >> 2);
        wire [BANK_AW-1:0] write_base_inc = write_base == BANK_AW'(BANK_DEPTH-1) ?
                                                '0 : write_base + 1'b1;
        wire [BANK_AW-1:0] read_base_inc = read_base == BANK_AW'(BANK_DEPTH-1) ?
                                                '0 : read_base + 1'b1;
        assign bank_wa[bank] = write_sector[1:0] > 2'(bank) ? write_base_inc : write_base;
        assign bank_ra[bank] = read_sector[1:0] > 2'(bank) ? read_base_inc : read_base;
        assign bank_we[bank] = write_accept && (write_length == 3'd4 || write_offset != 2'd3);
        assign bank_re[bank] = read_en && !capacity_fault && (read_length == 3'd4 || read_offset != 2'd3);
        always_comb begin
            case(write_offset)
                2'd0:bank_wd[bank] = low_bits[0+:128];
                2'd1:bank_wd[bank] = low_bits[128+:128];
                2'd2:bank_wd[bank] = low_bits[256+:128];
                2'd3:bank_wd[bank] = high_bits;
            endcase
        end
    end
    for(genvar bank=0;bank<4;bank++) begin:g_bank
        (* ram_style="block" *) logic [127:0] ram[0:BANK_DEPTH-1];
        always_ff @(posedge clk) begin
            if(bank_we[bank]) ram[bank_wa[bank]]<=bank_wd[bank];
            if(bank_re[bank]) bank_rd[bank]<=ram[bank_ra[bank]];
        end
    end
    always_comb begin
        for(int sector=0;sector<4;sector++)
            packet_q[sector*128+:128]=bank_rd[2'(read_phase_q+2'(sector))];
        for(int lane=0;lane<16;lane++) begin
            read_data[lane*32+:24]=packet_q[lane*24+:24];
            read_data[lane*32+24+:8]=decode_long_q ? packet_q[384+lane*8+:8] :
                                                  {8{packet_q[lane*24+23]}};
        end
    end
    // Advance the two-bit phase independently. Three-sector records add
    // one bank row unless phase==0; four-sector records always add a row.
    // The directory bit selects precomputed base addresses, avoiding a
    // late variable add, full-pointer comparison and wrap subtraction.
    wire [BANK_AW-1:0] write_pointer_base = BANK_AW'(write_sector >> 2);
    wire [BANK_AW-1:0] read_pointer_base = BANK_AW'(read_sector >> 2);
    wire [BANK_AW-1:0] write_pointer_inc = write_pointer_base == BANK_AW'(BANK_DEPTH-1) ?
        '0 : write_pointer_base + 1'b1;
    wire [BANK_AW-1:0] read_pointer_inc = read_pointer_base == BANK_AW'(BANK_DEPTH-1) ?
        '0 : read_pointer_base + 1'b1;
    wire [1:0] write_next_phase = encode_long ? write_sector[1:0] : write_sector[1:0] - 2'd1;
    wire [1:0] read_next_phase = decode_long ? read_sector[1:0] : read_sector[1:0] - 2'd1;
    wire [PTR_W-1:0] write_next = {
        ((encode_long || write_sector[1:0]!=0) ? write_pointer_inc : write_pointer_base),write_next_phase};
    wire [PTR_W-1:0] read_next = {
        ((decode_long || read_sector[1:0]!=0) ? read_pointer_inc : read_pointer_base),read_next_phase};
    always_ff @(posedge clk) begin
        if(!rst_n) begin
            write_sector<='0;read_sector<='0;write_row<='0;read_row<='0;
            used_sectors<='0;used_rows<='0;capacity_fault<=1'b0;decode_long_q<=1'b0;read_phase_q<='0;
        end else begin
            if(write_en && !write_accept) capacity_fault<=1'b1;
            if(write_accept) begin
                long_record[write_row]<=encode_long;
                write_row<=write_row==ROW_W'(LOGICAL_ROWS-1) ? '0 : write_row+1'b1;
                write_sector<=write_next;
            end
            if(read_en && !capacity_fault) begin
                decode_long_q<=decode_long;read_phase_q<=read_sector[1:0];
                read_row<=read_row==ROW_W'(LOGICAL_ROWS-1) ? '0 : read_row+1'b1;
                read_sector<=read_next;
            end
            case({write_accept,read_en && !capacity_fault})
                2'b10:begin used_sectors<=used_sectors+COUNT_W'(write_length);used_rows<=used_rows+1'b1;end
                2'b01:begin used_sectors<=used_sectors-COUNT_W'(read_length);used_rows<=used_rows-1'b1;end
                2'b11:begin
                    if (encode_long && !decode_long) used_sectors <= used_sectors + 1'b1;
                    else if (!encode_long && decode_long) used_sectors <= used_sectors - 1'b1;
                end
                default:;
            endcase
        end
    end
`ifndef SYNTHESIS
    longint unsigned rows_written,rows_read,long_rows,exception_values,peak_sectors;
    bit codec_trace;
    initial begin
        codec_trace=$test$plusargs("PS_CODEC_TRACE");
        assert(POOL_BYTES%64==0 && LOGICAL_ROWS>1 && SECTORS>4);
    end
    always @(posedge clk) begin
        if(!rst_n) begin
            rows_written=0;rows_read=0;long_rows=0;exception_values=0;peak_sectors=0;
        end else begin
            if(write_accept) begin
                assert(write_addr==write_row) else $fatal(1,"PS nonsequential write addr=%0d expected=%0d",write_addr,write_row);
                rows_written++;long_rows+=int'(encode_long);exception_values+=$countones(exception_mask);
            end
            if(read_en && !capacity_fault) begin
                assert(read_addr==read_row) else $fatal(1,"PS nonsequential read addr=%0d expected=%0d",read_addr,read_row);
                assert(used_sectors>=COUNT_W'(read_length)) else $fatal(1,"PS sector underflow");
                rows_read++;
            end
            if(int'(used_sectors)>peak_sectors) peak_sectors=int'(used_sectors);
            for(int b=0;b<4;b++)
                assert(!(bank_we[b]&&bank_re[b]&&bank_wa[b]==bank_ra[b])) else $fatal(1,"PS bank read/write collision");
            if(write_en && !write_accept && FAIL_STOP)
                $fatal(1,"PS_CAPACITY_FAULT pool_bytes=%0d used_sectors=%0d required=%0d rows_written=%0d rows_read=%0d",POOL_BYTES,used_sectors,write_length,rows_written,rows_read);
        end
    end
    final if(codec_trace)
        $display("[PS_CODEC] rows_written=%0d rows_read=%0d long_rows=%0d exception_values=%0d payload_write_bytes=%0d peak_payload_bytes=%0d mode_directory_bytes=%0d",rows_written,rows_read,long_rows,exception_values,48*rows_written+16*long_rows,16*peak_sectors,(LOGICAL_ROWS+7)/8);
`endif
endmodule
