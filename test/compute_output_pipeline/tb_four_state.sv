`timescale 1ns/1ps
module output_four_state_tb;
    localparam int SIZE=3;
    logic clk=0, rst_n=0;
    logic ia_row_valid=0, ia_calc_done=0, ia_is_init_data=0, ia_sending_done=0;
    logic final_output_overlap=0, direct_final_stream=0;
    logic signed [31:0] i_ps_data [SIZE];
    logic i_ps_valid=0, i_ps_tile_done=0;
    wire signed [31:0] output_data [SIZE];
    wire output_valid, output_tile_done;
    logic signed [31:0] expected_data [SIZE];
    logic expected_valid, expected_tile_done;
    int checked_values=0;

    current_stage #(.SIZE(SIZE)) u_current (
        .clk(clk), .rst_n(rst_n), .ia_row_valid(ia_row_valid), .ia_calc_done(ia_calc_done),
        .ia_is_init_data(ia_is_init_data), .ia_sending_done(ia_sending_done),
        .final_output_overlap(final_output_overlap), .direct_final_stream(direct_final_stream),
        .i_ps_data(i_ps_data), .i_ps_valid(i_ps_valid), .i_ps_tile_done(i_ps_tile_done),
        .acc_data_out(output_data), .acc_data_valid(output_valid), .tile_calc_over(output_tile_done),
        .partial_sum_calc_over(), .partial_sum_advance_ready(),
        .o_final_component(), .o_nonfinal_component()
    );
    function automatic logic state_value(input int index);
        case(index)
            0: state_value=1'b0;
            1: state_value=1'b1;
            2: state_value=1'bx;
            3: state_value=1'bz;
            default: state_value=1'bx;
        endcase
    endfunction
    initial begin
        for(int lane=0;lane<SIZE;lane++) i_ps_data[lane]='x;
        #1;
        for(int cycle=0;cycle<4096;cycle++) begin
            rst_n=(cycle % 97)!=0;
            i_ps_valid=state_value(cycle%4);
            i_ps_tile_done=state_value((cycle/4)%4);
            for(int lane=0;lane<SIZE;lane++) begin
                i_ps_data[lane]=$random;
                i_ps_data[lane][cycle%32]=state_value((cycle/(16*(lane+1)))%4);
                expected_data[lane]=i_ps_data[lane];
            end
            expected_valid=rst_n ? i_ps_valid : 1'b0;
            expected_tile_done=rst_n ? i_ps_tile_done : 1'b0;
            #1;clk=1;#1;
            if(output_valid !== expected_valid || output_tile_done !== expected_tile_done)
                $fatal(1,"Four-state qualifiers differ at cycle %0d",cycle);
            for(int lane=0;lane<SIZE;lane++) begin
                if(output_data[lane] !== expected_data[lane])
                    $fatal(1,"Four-state payload differs at cycle %0d lane %0d",cycle,lane);
                checked_values++;
            end
            clk=0;#1;
            if((cycle%97)==96) begin
                rst_n=0;#1;
                if(output_valid !== 1'b0 || output_tile_done !== 1'b0)
                    $fatal(1,"Asynchronous reset did not clear qualifiers");
            end
        end
        $display("{\"passed\":true,\"cycles\":4096,\"checked_values\":%0d}",checked_values);
        $finish;
    end
endmodule
