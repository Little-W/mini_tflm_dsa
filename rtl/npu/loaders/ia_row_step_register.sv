`default_nettype none

// 普通行步长与复用组步长共用计算输入，并在同一配置边沿保存。
(* keep_hierarchy = "yes" *)
module ia_row_step_register #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_size = 16
) (
    input wire logic clk,
    input wire logic rst_n,
    input wire logic i_enable,
    input wire logic i_tile_packed,
    input wire logic i_use_16bits,
    input wire logic [p_width-1:0] i_reuse_num,
    input wire logic [p_width-1:0] i_row_stride,
    input wire logic [p_width-1:0] i_packed_tiles,
    output logic [p_width-1:0] o_tile_step,
    output logic [p_width-1:0] o_group_step
);
    //! 0. 辅助定义
    //! ------------------

    localparam int p_log2_size = $clog2(p_size);
    logic [p_width-1:0] tile_step_nxt, group_step_nxt;
    logic [p_width-1:0] tile_step, group_step;
    logic [6:0] reuse_factor;
    logic [2:0] reuse_shift;
    (* use_dsp = "yes" *) logic [p_width-1:0] row_product;

    //! 1. 输入计算
    //! ------------------

    assign tile_step_nxt = i_tile_packed ?
        (i_packed_tiles << (2*p_log2_size + (i_use_16bits ? 1 : 0))) :
        (i_row_stride << p_log2_size);

    if (p_width >= 7) begin : g_encoded_factor
        // 复用数量编码为窄系数，完整字节步长共用同一个乘法结果。
        always_comb begin
            reuse_factor = 7'd1;
            case (i_reuse_num)
                p_width'(2): reuse_factor = 7'd2;
                p_width'(4): reuse_factor = 7'd4;
                p_width'(8): reuse_factor = 7'd8;
                p_width'(16): reuse_factor = 7'd16;
                p_width'(25): reuse_factor = 7'd25;
                p_width'(32): reuse_factor = 7'd32;
                p_width'(64): reuse_factor = 7'd64;
                default: ;
            endcase
            reuse_shift = 3'd0;
            case (i_reuse_num)
                p_width'(2): reuse_shift = 3'd1;
                p_width'(4): reuse_shift = 3'd2;
                p_width'(8): reuse_shift = 3'd3;
                p_width'(16): reuse_shift = 3'd4;
                p_width'(32): reuse_shift = 3'd5;
                p_width'(64): reuse_shift = 3'd6;
                default: ;
            endcase
        end
        // 地址步长保留 p_width 位模乘结果，溢出部分不参与地址更新。
        assign row_product = p_width'(tile_step_nxt * reuse_factor);
        always_comb begin
            // 未知数据保留移位与定宽加法的四态传播顺序。
            group_step_nxt = tile_step_nxt << reuse_shift;
            if (i_reuse_num == p_width'(25)) begin
                group_step_nxt = (tile_step_nxt << 4) + (tile_step_nxt << 3) + tile_step_nxt;
            end
            case (^tile_step_nxt)
                1'b0, 1'b1: group_step_nxt = row_product;
                default: ;
            endcase
        end
    end else begin : g_narrow_factor
        // 窄参数保持常量截断后的首项匹配顺序。
        always_comb begin
            group_step_nxt = tile_step_nxt;
            case (i_reuse_num)
                p_width'(1): group_step_nxt = tile_step_nxt;
                p_width'(2): group_step_nxt = tile_step_nxt << 1;
                p_width'(4): group_step_nxt = tile_step_nxt << 2;
                p_width'(8): group_step_nxt = tile_step_nxt << 3;
                p_width'(16): group_step_nxt = tile_step_nxt << 4;
                p_width'(25): group_step_nxt = (tile_step_nxt << 4) + (tile_step_nxt << 3) + tile_step_nxt;
                p_width'(32): group_step_nxt = tile_step_nxt << 5;
                p_width'(64): group_step_nxt = tile_step_nxt << 6;
                default: ;
            endcase
        end
    end

    //! 2. 寄存器更新
    //! ------------------

    // 两种步长在同一配置接收边沿保存，其他周期共同保持。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tile_step <= '0;
            group_step <= '0;
        end else if (i_enable) begin
            tile_step <= tile_step_nxt;
            group_step <= group_step_nxt;
        end
    end

    //! 3. 输出生成
    //! ------------------

    assign o_tile_step = tile_step;
    assign o_group_step = group_step;
endmodule

`default_nettype wire
