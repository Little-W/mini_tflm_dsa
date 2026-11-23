// SPDX-License-Identifier: Apache-2.0
module requant_buffer_proof #(parameter int p_rows=512)(
    input logic clk,rst_n,i_clear,i_group_start,i_row_valid,i_row_ready,i_output_valid,
    input logic [31:0] i_group_rows,
    input logic i_data,i_tile_done
);
    localparam int p_count_width=(p_rows<=1)?1:$clog2(p_rows+1);
    logic [p_count_width-1:0] expected_rows, issued_rows;
    wire group_ready,row_valid,row_tile_done;
    wire signed [31:0] row_data[1], output_data[1];
    assign row_data[0]={31'd0,i_data};
    wire consume=row_valid && i_row_ready;
    requant_group_buffer #(.p_lanes(1),.p_rows(p_rows)) dut (
        .clk(clk),.rst_n(rst_n),.i_clear(i_clear),.i_group_start(i_group_start),
        .i_group_rows(i_group_rows),.o_group_ready(group_ready),
        .i_row_valid(i_row_valid),.i_row_tile_done(i_tile_done),.i_row_data(row_data),
        .o_row_valid(row_valid),.o_row_tile_done(row_tile_done),.o_row_data(output_data),
        .i_row_ready(i_row_ready),.i_output_valid(i_output_valid)
    );
    always_comb if(rst_n && !i_clear)begin
        assume(!i_group_start || (group_ready && i_group_rows>0 && i_group_rows<=p_rows));
        assume(!i_row_valid || i_group_start || expected_rows!=0);
        assume(!i_output_valid || issued_rows!=0);
    end
    always_ff @(posedge clk) begin
        if(!rst_n || i_clear)begin
            expected_rows<='0;
            issued_rows<='0;
        end
        else begin
            if(i_group_start)expected_rows<=p_count_width'(i_group_rows)-p_count_width'(i_row_valid);
            else if(i_row_valid)expected_rows<=expected_rows-1'b1;
            case({consume,i_output_valid})
                2'b10:issued_rows<=issued_rows+1'b1;
                2'b01:issued_rows<=issued_rows-1'b1;
                default:begin end
            endcase
        end
    end
    // 等式包含尚未抵达的阵列行、RAM行、读出行和算术流水行。
    always_comb if(rst_n)begin
        assert(dut.pending_rows_q<=p_rows);
        assert(expected_rows<=p_rows);
        assert(dut.stored_rows_q<=p_rows);
        assert(issued_rows<=p_rows);
        assert(32'(dut.pending_rows_q)==32'(expected_rows)+32'(dut.stored_rows_q)+32'(row_valid)+32'(issued_rows));
        if(group_ready)assert(expected_rows==0 && dut.stored_rows_q==0 && !row_valid && issued_rows==0);
        if(dut.read_row)assert(dut.stored_rows_q!=0);
        if(dut.push_row && !i_group_start)assert(dut.stored_rows_q<p_rows);
        assert(dut.write_addr_q<p_rows && dut.read_addr_q<p_rows);
    end
endmodule
