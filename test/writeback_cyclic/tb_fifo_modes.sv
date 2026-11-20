`timescale 1ns/1ps
module tb_fifo_modes;
    localparam BUS_WIDTH=`TB_BUS_WIDTH, NB=BUS_WIDTH/8, BANKS=4;
    logic clk=0;
    always #5 clk=!clk;
    logic rst_n=0, start_permitted=0, in_valid=0, in_tile_done=0;
    logic [127:0] in_vec_s8=0;
    logic transpose_mode=0,coalesce_enable=0,coalesce_group_start=0,output_ready=0;
    logic [31:0] coalesce_rows=1,coalesce_cols=1,reserve_banks=1;
    logic [3:0] vec_valid_num_col=0,vec_valid_num_row=0;
    wire [2*(BUS_WIDTH+NB+4)-1:0] observed;
    for(genvar implementation=0;implementation<2;implementation++) begin : g_check
        wire dut_req,dut_valid,dut_switch,dut_full,ref_req,ref_valid,ref_switch,ref_full;
        wire [BUS_WIDTH-1:0] dut_data,ref_data;
        wire [NB-1:0] dut_mask,ref_mask;
        wire active_coalesce=(implementation==0)&&coalesce_enable;
        vec_s8_to_fifo_full #(.VLEN(16),.BANKS(BANKS),.BUS_WIDTH(BUS_WIDTH),
            .p_cyclic_storage(implementation)) u_dut (
            .*,.coalesce_enable(active_coalesce),.oa_fifo_req(dut_req),.output_valid(dut_valid),
            .output_row_switch(dut_switch),.output_mask(dut_mask),.output_data(dut_data),.fifo_full_flag(dut_full));
        vec_s8_to_fifo_ref_full #(.VLEN(16),.BANKS(BANKS),.BUS_WIDTH(BUS_WIDTH)) u_ref (
            .*,.coalesce_enable(active_coalesce),.oa_fifo_req(ref_req),.output_valid(ref_valid),
            .output_row_switch(ref_switch),.output_mask(ref_mask),.output_data(ref_data),.fifo_full_flag(ref_full));
        always @(posedge clk) if(rst_n) begin
            assert({dut_req,dut_valid,dut_switch,dut_mask,dut_data,dut_full}===
                {ref_req,ref_valid,ref_switch,ref_mask,ref_data,ref_full})
                else $fatal(1,"FIFO live mode mismatch implementation=%0d",implementation);
        end
    end
    int cycles=0, mode_changes=0, first_wait_changes=0;
    logic last_mode;
    initial begin
        repeat(200000) begin
            @(negedge clk);
            rst_n=$urandom_range(0,127)!=0;
            start_permitted=$urandom_range(0,3)!=0;
            in_valid=$urandom_range(0,1);
            in_tile_done=$urandom_range(0,15)==0;
            for(int word_index=0;word_index<4;word_index++) in_vec_s8[word_index*32+:32]=$urandom();
            last_mode=transpose_mode;
            transpose_mode=$urandom_range(0,1);
            coalesce_enable=$urandom_range(0,1);
            coalesce_group_start=$urandom_range(0,1);
            coalesce_rows=$urandom_range(0,3);coalesce_cols=$urandom_range(0,3);
            reserve_banks=$urandom_range(0,7);
            vec_valid_num_col=4'($urandom());vec_valid_num_row=4'($urandom());
            output_ready=$urandom_range(0,1);
            if(rst_n&&transpose_mode!=last_mode) mode_changes++;
            if(rst_n&&transpose_mode!=last_mode&&g_check[1].u_dut.stream_active&&
                g_check[1].u_dut.read_ptr==0&&g_check[1].u_dut.beat_idx==0&&!output_ready)
                first_wait_changes++;
            cycles++;
        end
        @(negedge clk);
        assert(first_wait_changes>0);
        $display("FIFO_MODES_PASS bus_width=%0d cycles=%0d mode_changes=%0d first_wait_changes=%0d",
            BUS_WIDTH,cycles,mode_changes,first_wait_changes);
        $finish;
    end
endmodule
