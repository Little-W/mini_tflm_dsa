// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按帧保存输入数据和实际帧长，回放请求按帧顺序读取同步存储器。
module ps_buffer_wide_fifo #(
    parameter int unsigned DEPTH       = 16,
    parameter int unsigned DATA_WIDTH  = 512,
    parameter int unsigned FRAME_COUNT = 1,
    parameter int unsigned MAX_FRAME_LEN = DEPTH
) (
    input  wire logic                  clk,
    input  wire logic                  rst_n,
    input  wire logic [DATA_WIDTH-1:0] data_in,
    input  wire logic                  input_valid_i,
    input  wire logic                  ia_l1_switch_i,
    input  wire logic                  send_ia_trigger_i,
    input  wire logic                  replay_enable_i,
    output logic [DATA_WIDTH-1:0] data_out,
    output logic capacity_fault,
    output logic replay_ready
);
    localparam int unsigned ADDR_W      = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
    localparam int unsigned CNT_W       = (DEPTH <= 1) ? 1 : $clog2(DEPTH + 1);
    localparam int unsigned FRAME_IDX_W = (FRAME_COUNT <= 1) ? 1 : $clog2(FRAME_COUNT);
    localparam int unsigned FRAME_CNT_W = (FRAME_COUNT < 1) ? 1 : $clog2(FRAME_COUNT + 1);
    localparam int unsigned FRAME_LEN_W = (MAX_FRAME_LEN <= 1) ? 1 : $clog2(MAX_FRAME_LEN + 1);
    localparam int unsigned EXT_W       = CNT_W + 1;

    localparam logic [ADDR_W-1:0]      DEPTH_LAST_ADDR = ADDR_W'(DEPTH - 1);
    localparam logic [CNT_W-1:0]       DEPTH_COUNT     = CNT_W'(DEPTH);
    localparam logic [FRAME_CNT_W-1:0] FRAME_COUNT_C   = FRAME_CNT_W'(FRAME_COUNT);

    logic [ADDR_W-1:0]      write_ptr;
    logic [ADDR_W-1:0]      read_ptr;
    logic [ADDR_W-1:0]      write_base;
    logic [ADDR_W-1:0]      read_base;
    logic [FRAME_LEN_W-1:0] frame_len;
    logic [FRAME_LEN_W-1:0] frame_len_fifo [FRAME_COUNT];
    logic [FRAME_IDX_W-1:0] frame_wr_ptr;
    logic [FRAME_IDX_W-1:0] frame_rd_ptr;
    logic [FRAME_CNT_W-1:0] frame_count;
    logic [FRAME_LEN_W-1:0] replay_count;
    logic                   ia_l1_switch_i_d;
    logic                   send_ia_trigger_i_d;

    logic                   ram_write_en;
    logic                   ram_read_en;
    logic [ADDR_W-1:0]      ram_write_addr;
    logic [ADDR_W-1:0]      ram_read_addr;
    logic [CNT_W-1:0]       write_ptr_ext;
    logic [FRAME_LEN_W-1:0] frame_len_next;
    logic [FRAME_LEN_W-1:0] replay_frame_len;
    logic [DATA_WIDTH-1:0]  ram_read_data;
    logic                   read_forward_valid;
    logic [DATA_WIDTH-1:0]  read_forward_data;
    logic                   ram_write_en_q;
    logic [ADDR_W-1:0]      ram_write_addr_q;
    logic [DATA_WIDTH-1:0]  ram_write_data_q;
    logic                   replay_data_valid;
    logic [CNT_W:0]         ram_write_addr_ext;
    logic [CNT_W:0]         write_base_next_ext;
    logic [CNT_W:0]         read_base_next_ext;
    logic [ADDR_W-1:0]      write_base_next;
    logic [ADDR_W-1:0]      read_base_next;
    logic [ADDR_W-1:0]      read_ptr_inc;
    logic [FRAME_IDX_W-1:0] frame_wr_ptr_inc;
    logic [FRAME_IDX_W-1:0] frame_rd_ptr_inc;

    assign replay_ready = (frame_count != '0) && (replay_count == '0);
    assign ram_write_en   = input_valid_i;
    assign ram_read_en    = (replay_count != '0);
    assign ram_read_addr  = read_ptr;
    assign write_ptr_ext  = write_ptr;
    assign frame_len_next = input_valid_i
                          ? FRAME_LEN_W'(write_ptr_ext + CNT_W'(1))
                          : FRAME_LEN_W'(write_ptr_ext);
    assign frame_len      = (frame_count != '0) ? frame_len_fifo[frame_rd_ptr] : '0;
    assign replay_frame_len = (frame_count != '0) ? frame_len : frame_len_next;

    assign ram_write_addr_ext = EXT_W'(write_base) + EXT_W'(write_ptr);
    assign write_base_next_ext = EXT_W'(write_base) + EXT_W'(frame_len_next);
    assign read_base_next_ext = EXT_W'(read_base) + EXT_W'(replay_frame_len);
    assign ram_write_addr = (ram_write_addr_ext >= EXT_W'(DEPTH_COUNT)) ?
                            ADDR_W'(ram_write_addr_ext - EXT_W'(DEPTH_COUNT)) :
                            ADDR_W'(ram_write_addr_ext);
    assign write_base_next = (write_base_next_ext >= EXT_W'(DEPTH_COUNT)) ?
                             ADDR_W'(write_base_next_ext - EXT_W'(DEPTH_COUNT)) :
                             ADDR_W'(write_base_next_ext);
    assign read_base_next = (read_base_next_ext >= EXT_W'(DEPTH_COUNT)) ?
                            ADDR_W'(read_base_next_ext - EXT_W'(DEPTH_COUNT)) :
                            ADDR_W'(read_base_next_ext);
    assign read_ptr_inc = (read_ptr == DEPTH_LAST_ADDR) ? '0 : (read_ptr + 1'b1);
    assign frame_wr_ptr_inc = (FRAME_COUNT <= 1) ? '0 :
                              ((frame_wr_ptr == FRAME_IDX_W'(FRAME_COUNT - 1)) ?
                               '0 : (frame_wr_ptr + 1'b1));
    assign frame_rd_ptr_inc = (FRAME_COUNT <= 1) ? '0 :
                              ((frame_rd_ptr == FRAME_IDX_W'(FRAME_COUNT - 1)) ?
                               '0 : (frame_rd_ptr + 1'b1));

    assign data_out = replay_data_valid ?
        (read_forward_valid ? read_forward_data : ram_read_data) : '0;

    // 同步读写地址相同时转发已保存的写入数据，读端返回本次写入值。
    // 转发资格与同步读取结果在同一时钟边沿保存。
    always_ff @(posedge clk) begin
        if (!rst_n) read_forward_valid <= 1'b0;
        else begin
            read_forward_valid <= ram_read_en && ram_write_en_q &&
                                  ram_read_addr == ram_write_addr_q;
            if (ram_read_en && ram_write_en_q && ram_read_addr == ram_write_addr_q)
                read_forward_data <= ram_write_data_q;
        end
    end

    assign capacity_fault=1'b0;
    ps_buffer_exact_ram #(
        .DEPTH(DEPTH),
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH (ADDR_W)
    ) u_ps_fifo_ram (
        .clk   (clk),
        .ena   (1'b1),
        .enb   (ram_read_en),
        .wea   (ram_write_en_q),
        .addra (ram_write_addr_q),
        .dia   (ram_write_data_q),
        .addrb (ram_read_addr),
        .dob   (ram_read_data)
    );

    always_ff @(posedge clk) begin
        ram_write_addr_q <= ram_write_addr;
        ram_write_data_q <= data_in;
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            ram_write_en_q      <= 1'b0;
            write_ptr           <= '0;
            read_ptr            <= '0;
            write_base          <= '0;
            read_base           <= '0;
            frame_wr_ptr        <= '0;
            frame_rd_ptr        <= '0;
            frame_count         <= '0;
            replay_count        <= '0;
            ia_l1_switch_i_d    <= 1'b0;
            send_ia_trigger_i_d <= 1'b0;
            replay_data_valid   <= 1'b0;
            for (int frame_i = 0; frame_i < FRAME_COUNT; frame_i++) begin
                frame_len_fifo[frame_i] <= '0;
            end
        end else begin
            logic push_frame;
            logic pop_frame;

            // 切换与回放请求均按上升沿接收，同周期入队和出队保持帧计数。
            push_frame = ia_l1_switch_i && !ia_l1_switch_i_d && (frame_len_next != '0);
            pop_frame  = send_ia_trigger_i && !send_ia_trigger_i_d &&
                         replay_enable_i && ((frame_count != '0) || push_frame) &&
                         (replay_count == '0);

            ia_l1_switch_i_d    <= ia_l1_switch_i;
            send_ia_trigger_i_d <= send_ia_trigger_i;
            replay_data_valid   <= ram_read_en;
            ram_write_en_q      <= ram_write_en;

            if (input_valid_i) begin
                write_ptr <= write_ptr + 1'b1;
            end

            if (ia_l1_switch_i && !ia_l1_switch_i_d) begin
                if (frame_len_next != '0) begin
                    frame_len_fifo[frame_wr_ptr] <= frame_len_next;
                    frame_wr_ptr <= frame_wr_ptr_inc;
                    write_base   <= write_base_next;

                end
                write_ptr    <= '0;
            end

            if (send_ia_trigger_i && !send_ia_trigger_i_d) begin
                if (pop_frame) begin
                    read_ptr     <= read_base;
                    read_base    <= read_base_next;
                    replay_count <= replay_frame_len;
                    frame_rd_ptr <= frame_rd_ptr_inc;

                end
            end

            if (!pop_frame && (replay_count != '0)) begin
                if (replay_count == 1) begin
                    replay_count <= '0;
                end else begin
                    replay_count <= replay_count - 1'b1;
                    read_ptr     <= read_ptr_inc;
                end
            end

            if (push_frame && !pop_frame) begin
                if (frame_count < FRAME_COUNT_C) begin
                    frame_count <= frame_count + 1'b1;
                end
            end else if (!push_frame && pop_frame) begin
                frame_count <= frame_count - 1'b1;
            end
        end
    end
endmodule

`default_nettype wire
