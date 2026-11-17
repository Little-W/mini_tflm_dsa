`timescale 1ns/1ps
module raw_frame_store_tb (
    input wire clk,rst_n,
    input wire frame_request,frame_accept,
    input wire [3:0] frame_id,
    input wire [31:0] frame_rows,
    input wire frame_init,frame_final,
    output wire frame_ready,frame_pressure,capacity_fault,frame_complete,
    input wire write_valid,
    input wire [511:0] write_data,
    input wire write_frame_end,replay_trigger,
    output wire [511:0] replay_data,
    input wire [12:0] inspect_linear,
    output wire [12:0] inspect_quotient [3],
    output wire [2:0] inspect_remainder [3],
    output wire replay_valid
);
    for(genvar index=0;index<3;index++) begin:g_address
        ps_raw_address #(.WIDTH(13),.DIVISOR(index+5)) u_address
            (.linear(inspect_linear),.quotient(inspect_quotient[index]),.remainder(inspect_remainder[index]));
    end
    ps_frame_store #(.MAX_FRAME_ROWS(64),.FRAME_COUNT(16),.POOL_BYTES(16384)) dut (
        .clk,.rst_n,.frame_request,.frame_accept,.frame_id,.frame_rows,
        .frame_reserve_rows(frame_rows),.frame_word_cap(3'd4),.frame_init,.frame_final,
        .force_raw_i(1'b1),.frame_ready,.frame_pressure,.capacity_fault,.frame_complete,
        .write_valid,.write_data,.write_frame_end,.replay_trigger,.replay_data,.replay_valid
    );
endmodule
