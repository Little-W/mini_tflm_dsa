`default_nettype none

module tb_storage;
    parameter integer p_depth = 256;
    localparam integer p_addr_width = (p_depth <= 1) ? 1 : $clog2(p_depth);
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic init_cfg = 1'b1;
    logic shift_i_wr_en = 1'b0;
    logic write_last = 1'b0;
    logic [p_addr_width-1:0] write_addr = '0;
    logic [6:0] write_product_amount = '0;
    logic [p_addr_width-1:0] product_multiplier_i_rd_addr = '0;
    logic [6:0] actual;
    logic [6:0] expected;
    logic [6:0] reference [p_depth];
    logic [127:0] values_seen = '0;
    logic [31:0] random_state = 32'h48d219ab;
    integer cycles = 0;
    integer checks = 0;
    integer completed_pairs = 0;
    integer tail_writes = 0;
    integer interruptions = 0;
    integer unknown_values = 0;
    integer read_hold_checks = 0;
    integer loaded;
    integer selected;
    integer length;
    integer sample_count = 0;
    logic [6:0] saved_output;

    amount_storage #(.BANK_DEPTH(p_depth)) u_dut (.*,.o_amount(actual));

    function automatic [31:0] next_random(input [31:0] value);
        next_random = {value[30:0],value[31]^value[21]^value[1]^value[0]};
    endfunction

    task automatic tick(input bit compare_data);
        begin
            clk = 1'b0;
            #2;
            if (!init_cfg) expected = reference[product_multiplier_i_rd_addr];
            saved_output = actual;
            clk = 1'b1;
            if (shift_i_wr_en) reference[write_addr] = write_product_amount;
            #2;
            cycles = cycles + 1;
            if (init_cfg) begin
                if (actual !== saved_output)
                    $fatal(1,"Read output changed while disabled");
                read_hold_checks = read_hold_checks + 1;
            end else if (compare_data) begin
                if (actual !== expected)
                    $fatal(1,"Data mismatch depth=%0d cycle=%0d address=%0d expected=%h actual=%h",
                        p_depth,cycles,product_multiplier_i_rd_addr,expected,actual);
                checks = checks + 1;
            end
            clk = 1'b0;
            #1;
        end
    endtask

    initial begin
        tick(0);
        rst_n = 1'b1;
        for (integer iteration=0;iteration<384;iteration=iteration+1) begin
            init_cfg = 1'b1;
            shift_i_wr_en = 1'b0;
            tick(0);
            init_cfg = 1'b0;
            random_state = next_random(random_state);
            length = (iteration%4==0) ? p_depth : 1+(random_state%p_depth);
            loaded = 0;
            for (integer index=0;index<length;index=index+1) begin
                random_state = next_random(random_state);
                repeat (random_state[1:0]) begin
                    shift_i_wr_en = 1'b0;
                    product_multiplier_i_rd_addr = '0;
                    tick(loaded>=2);
                end
                write_addr = p_addr_width'(index);
                write_product_amount = 7'(sample_count);
                sample_count = sample_count + 1;
                if (iteration%13==7) begin
                    write_product_amount[iteration%7] = 1'bx;
                    unknown_values = unknown_values + 1;
                end else if (iteration%17==9) begin
                    write_product_amount[iteration%7] = 1'bz;
                    unknown_values = unknown_values + 1;
                end
                if ((^write_product_amount) !== 1'bx)
                    values_seen[write_product_amount] = 1'b1;
                shift_i_wr_en = 1'b1;
                write_last = index+1==length;
                product_multiplier_i_rd_addr = '0;
                tick(loaded>=2 && index>=2);
                loaded = index+1;
                if (index[0]) completed_pairs = completed_pairs + 1;
                else if (write_last) tail_writes = tail_writes + 1;
                if (iteration%11==3 && index==0 && length>1) begin
                    interruptions = interruptions + 1;
                    loaded = 0;
                    index = length;
                end
            end
            shift_i_wr_en = 1'b0;
            write_last = 1'b0;
            for (integer index=0;index<loaded;index=index+1) begin
                product_multiplier_i_rd_addr = p_addr_width'(index);
                tick(1);
            end
            for (integer index=0;index<loaded;index=index+1) begin
                random_state = next_random(random_state);
                selected = random_state%loaded;
                product_multiplier_i_rd_addr = p_addr_width'(selected);
                tick(1);
            end
        end
        if (values_seen !== {128{1'b1}} || checks==0 || tail_writes==0 || unknown_values==0)
            $fatal(1,"Incomplete storage coverage");
        if (p_depth>1 && (completed_pairs==0 || interruptions==0))
            $fatal(1,"Incomplete pair or interruption coverage");
        $display("PACKING_PASS depth=%0d cycles=%0d checks=%0d pairs=%0d tails=%0d interruptions=%0d unknown_values=%0d read_hold_checks=%0d values=128",
            p_depth,cycles,checks,completed_pairs,tail_writes,interruptions,unknown_values,read_hold_checks);
        $finish;
    end
endmodule

`default_nettype wire
