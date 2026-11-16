`timescale 1ns/1ps
module tb_kernel_prefetch;
    localparam int SIZE=16;
    logic clk=0,rst_n=0,load_start=0,load_slot_id,row_valid=0,row_slot=0,load_done=0,done_slot=0;
    logic [3:0] row_idx=0;
    logic signed [15:0] row_data[SIZE],weight_out[SIZE];
    logic send_start,load_ready,weight_data_valid,weight_sending_done,store_weight_req;
    int rows[4]='{16,7,16,1};
    bit issued_slots[4];
    int issued=0,observed=0,send_done=0;
    bit early_reuse=0;
    assign send_start=weight_data_valid;
    always #5 clk=~clk;
    kernel_loader_buffer #(.DATA_WIDTH(16),.SIZE(SIZE)) dut(.*);
    initial begin
        for(int c=0;c<SIZE;c++)row_data[c]=0;
        repeat(4)@(negedge clk);rst_n=1;
        fork
            begin
                for(int job=0;job<4;job++)begin
                    do @(negedge clk);while(!load_ready);
                    issued_slots[job]=load_slot_id;
                    load_start=1;
                    if(job==2 && send_done==0)early_reuse=1;
                    @(negedge clk);load_start=0;issued=job+1;
                end
            end
            begin
                for(int job=0;job<4;job++)begin
                    wait(issued>job);
                    for(int r=0;r<rows[job];r++)begin
                        @(negedge clk);row_valid=1;row_slot=issued_slots[job];row_idx=4'(r);
                        load_done=(r==rows[job]-1);done_slot=issued_slots[job];
                        for(int c=0;c<SIZE;c++)row_data[c]=16'(1000*job+16*r+c);
                    end
                    @(negedge clk);row_valid=0;load_done=0;
                end
            end
        join
        wait(send_done==4);
        repeat(3)@(negedge clk);
        assert(observed==64 && early_reuse)else $fatal(1,"overlapping bank reuse was not exercised");
        $display("KERNEL_PREFETCH_PASS tiles=4 vectors=64 elements=1024 early_bank_reuse=1");$finish;
    end
    always @(negedge clk)if(rst_n)begin
        if(store_weight_req)begin
            int job,k;
            job=observed/SIZE;k=SIZE-1-observed%SIZE;
            for(int c=0;c<SIZE;c++)begin
                logic signed [15:0] expected;
                expected=c<rows[job] ? 16'(1000*job+16*c+k) : 16'd0;
                assert(weight_out[c]===expected)else $fatal(1,"kernel output mismatch tile=%0d k=%0d lane=%0d got=%0d expected=%0d",job,k,c,weight_out[c],expected);
            end
            observed++;
        end
        if(weight_sending_done)send_done++;
    end
    initial begin #100000;$fatal(1,"kernel prefetch timeout");end
endmodule
