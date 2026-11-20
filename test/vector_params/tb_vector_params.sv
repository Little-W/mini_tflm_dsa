`timescale 1ns/1ps
module tb_vector_params #(
    parameter int TILE=16,
    parameter int BUS_WIDTH=64,
    parameter int PE_COUNT=8,
    localparam int INPUT_INDEX_W=$clog2(4*TILE),
    localparam int ACTIVE_COUNT_W=$clog2(TILE+1),
    localparam int TILE_INDEX_W=$clog2(TILE+PE_COUNT+1)
);
    logic clk=0;
    logic rst_n;
    logic [5:0] state_bits;
    logic [2:0] load_kind_bits;
    logic rd_raw_valid;
    logic [INPUT_INDEX_W-1:0] rd_col_base;
    logic [BUS_WIDTH-1:0] rd_raw_data;
    logic [ACTIVE_COUNT_W-1:0] active;
    logic [TILE_INDEX_W-1:0] q_issue;
    logic signed [31:0] reference_multiplier, candidate_multiplier;
    logic [5:0] reference_shift, candidate_shift;
    logic [37:0] expected [TILE];
    integer checks=0, writes=0, reset_cycles=0, repeated_writes=0;
    integer previous_address=-1;
    vector_params_reference #(.TILE(TILE), .BUS_WIDTH(BUS_WIDTH), .PE_COUNT(PE_COUNT)) u_reference (.*,
        .o_multiplier(reference_multiplier), .o_right_shift(reference_shift));
    vector_params_candidate #(.TILE(TILE), .BUS_WIDTH(BUS_WIDTH), .PE_COUNT(PE_COUNT)) u_candidate (.*,
        .o_multiplier(candidate_multiplier), .o_right_shift(candidate_shift));

    task automatic update_model;
        if (rst_n && state_bits==6'd5 && rd_raw_valid) begin
            for (int word_index=0;word_index<BUS_WIDTH/32;word_index++) begin
                int address;
                address=(int'(rd_col_base)>>2)+word_index;
                if (address<TILE && address<int'(active)) begin
                    if (load_kind_bits==3'd2) begin
                        expected[address][31:0]=rd_raw_data[32*word_index+:32];
                        writes++;
                    end
                    if (load_kind_bits==3'd3) begin
                        expected[address][37:32]=6'd31-rd_raw_data[32*word_index+:6];
                        writes++;
                    end
                end
            end
        end
    endtask

    task automatic check_reads;
        for (int index=0;index<(1<<TILE_INDEX_W);index++) begin
            logic [37:0] expected_read;
            q_issue=TILE_INDEX_W'(index);
            expected_read=index<TILE ? expected[index] : 38'd0;
            #1;
            if ({reference_shift,reference_multiplier} !== expected_read)
                $fatal(1,"reference read index=%0d actual=%h expected=%h",index,{reference_shift,reference_multiplier},expected_read);
            if ({candidate_shift,candidate_multiplier} !== expected_read)
                $fatal(1,"candidate read index=%0d actual=%h expected=%h",index,{candidate_shift,candidate_multiplier},expected_read);
            checks+=2;
        end
    endtask

    task automatic tick(input bit check_enabled);
        clk=0;
        if (check_enabled) check_reads();
        #1;
        clk=1;
        update_model();
        #1;
        if (check_enabled) check_reads();
        clk=0;
        #1;
    endtask

    initial begin
        int seed;
        seed=32'h4717a2c5;
        seed=$urandom(seed);
        rst_n=1;
        state_bits=6'd5;
        rd_raw_valid=1;
        active=ACTIVE_COUNT_W'(TILE);
        q_issue=0;
        // 先通过实际写端口填入全部参数，再检查复位期间保持和连续覆盖写入。
        for (int kind=2;kind<=3;kind++) begin
            load_kind_bits=3'(kind);
            for (int index=0;index<TILE;index+=BUS_WIDTH/32) begin
                rd_col_base=INPUT_INDEX_W'(4*index);
                for (int word_index=0;word_index<BUS_WIDTH/32;word_index++)
                    rd_raw_data[32*word_index+:32]=$urandom;
                tick(0);
            end
        end
        check_reads();
        for (int cycle=0;cycle<2000;cycle++) begin
            rst_n=(cycle%11!=0);
            state_bits=(cycle%5==0) ? 6'($urandom) : 6'd5;
            load_kind_bits=(cycle%7==0) ? 3'($urandom) : 3'(2+(cycle%2));
            rd_raw_valid=(cycle%9!=0);
            active=ACTIVE_COUNT_W'($urandom);
            if (cycle%3!=0) rd_col_base=INPUT_INDEX_W'($urandom);
            if (int'(rd_col_base)==previous_address) repeated_writes++;
            previous_address=int'(rd_col_base);
            for (int word_index=0;word_index<BUS_WIDTH/32;word_index++)
                rd_raw_data[32*word_index+:32]=$urandom;
            if (!rst_n) reset_cycles++;
            tick(1);
        end
        if (reset_cycles==0 || repeated_writes==0 || writes<TILE*2)
            $fatal(1,"insufficient event coverage");
        $display("VECTOR_PARAMS_PASS tile=%0d bus=%0d checks=%0d writes=%0d reset_cycles=%0d repeated_writes=%0d",
            TILE,BUS_WIDTH,checks,writes,reset_cycles,repeated_writes);
        $finish;
    end
endmodule
