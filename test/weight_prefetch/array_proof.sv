// SPDX-License-Identifier: Apache-2.0
module array_proof #(parameter int p_size=16)(
    input logic clk, rst_n, i_store, i_commit,
    input logic i_weight
);
    // 一位代表任意权重位，各列的权重移位和提交控制相同。
    localparam int p_count_width=$clog2(p_size+1);
    logic [p_count_width-1:0] loaded_rows;
    logic has_tile;
    logic [p_size-1:0] active_rows;
    wire signed [0:0] weight_in[p_size], data_in[p_size];
    wire signed [1:0] sum_in[p_size], sum_reference[p_size], sum_candidate[p_size];
    for(genvar c=0;c<p_size;c++)begin:g_inputs
        assign weight_in[c]=i_weight;
        assign data_in[c]='0;
        assign sum_in[c]='0;
    end
    ws_systolic_array #(.SIZE(p_size),.DATA_IN_WIDTH(1),.WEIGHT_WIDTH(1),.ACC_WIDTH(2),.p_exchange_weights(1'b1)) reference (
        .clk(clk),.rst_n(rst_n),.weight_commit(i_commit),.store_weight_req(i_store),
        .weight_in(weight_in),.data_in(data_in),.sum_in(sum_in),.sum_out(sum_reference)
    );
    ws_systolic_array #(.SIZE(p_size),.DATA_IN_WIDTH(1),.WEIGHT_WIDTH(1),.ACC_WIDTH(2),.p_exchange_weights(1'b0)) candidate (
        .clk(clk),.rst_n(rst_n),.weight_commit(i_commit),.store_weight_req(i_store),
        .weight_in(weight_in),.data_in(data_in),.sum_in(sum_in),.sum_out(sum_candidate)
    );
    // 只要求每次提交前已覆盖完整分块，允许额外装载以及任意装载暂停。
    always_ff @(posedge clk) begin
        if(!rst_n)begin
            loaded_rows<='0;
            has_tile<=1'b0;
            active_rows<='0;
        end else begin
            assume(!i_commit || loaded_rows==p_count_width'(p_size));
            if(i_commit)begin
                loaded_rows<=i_store ? p_count_width'(1) : '0;
                has_tile<=1'b1;
            end else if(i_store && loaded_rows<p_count_width'(p_size))begin
                loaded_rows<=loaded_rows+1'b1;
            end
            active_rows<=(active_rows<<1) | p_size'(has_tile || i_commit);
        end
    end
    for(genvar r=0;r<p_size;r++)begin:g_check
        always_comb if(rst_n && loaded_rows>p_count_width'(r))
            assert(reference.gen_row[r].gen_col[0].ws_cell.weight_prefetch==candidate.gen_row[r].gen_col[0].ws_cell.weight_prefetch);
        always_comb if(rst_n && active_rows[r])
            assert(reference.gen_row[r].gen_col[0].ws_cell.weight_active==candidate.gen_row[r].gen_col[0].ws_cell.weight_active);
    end
endmodule
