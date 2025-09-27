// =============================================
// vec_s8_to_fifo: s8向量打包为32位并输出的FIFO模块
// ---------------------------------------------
// 设计思路：
//   1. 双区FIFO设计（Ping-Pong Buffer）：
//      - 每区为方形存储：VLEN×VLEN，存储VLEN个完整向量
//      - 写满一区后自动切换到另一区，实现连续数据流处理
//      - 读写分离：写区域和读区域可以不同，提高吞吐率
//
//   2. 数据流控制：
//      - 输入阶段：连续接收s8向量，检测in_valid下降沿作为批次结束标志
//      - 输出阶段：32位打包输出，每4个s8字节组成一个32位数据
//      - 状态机控制：IDLE->REQ->OUTPUT三态切换
//
//   3. 握手协议设计：
//      - 双重握手：先请求-确认获取有效字节数，再数据-就绪传输
//      - 避免数据丢失：确保有效字节数与数据同步传输
//
// ---------------------------------------------
// 时序要求：
//   输入时序：
//     - in_valid高电平期间连续输入向量数据
//     - in_valid下降沿标志当前批次结束，触发区域切换
//     - 写指针在每个in_valid上升沿递增
//
//   输出握手时序：
//     1. 模块检测到有数据时拉高output_req
//     2. 主机在下一周期或延后几周期拉高req_ack，同时提供vec_valid_num_col
//     3. 模块锁存vec_valid_num_col，开始数据输出流程
//     4. output_valid/output_ready标准握手，每次传输36位数据
//     5. 传输完成后自动切换读区域并重置状态
//
//   关键约束：
//     - req_ack必须与vec_valid_num_col同时有效
//     - output_ptr从0递增到(VLEN/4-1)，对应VLEN个字节的32位打包
//     - 区域切换仅在批次结束（is_last_vec）或读完成时发生
//
// ---------------------------------------------
// 接口说明：
//   clk, rstn              -- 时钟与复位
//   in_valid               -- 输入数据有效（连续高电平输入，下降沿标志批次结束）
//   in_vec_s8[VLEN]        -- 输入s8向量数组
//   output_req             -- 请求输出信号（模块->主机，有数据待输出时为高）
//   req_ack                -- 主机确认信号（主机->模块，确认接收请求）
//   vec_valid_num_col      -- 主机给出的有效字节数（与req_ack同时有效）
//   output_valid           -- FIFO输出数据有效（标准握手信号）
//   output_ready           -- 外部请求弹出数据（标准握手信号）
//   output_mask            -- 输出数据有效性掩码（高4位）
//   output_data            -- 输出数据（低32位）
//   fifo_full_flag         -- 两块FIFO都被占用时为高（背压信号）
//
// 数据格式：
//   - 输入：每次输入VLEN个signed [7:0]数据
//   - 输出：36位=4位mask+32位数据，mask[i]对应data[8*i+7:8*i]字节有效性
//   - mask编码：4'b1111=全部有效，4'b0111=前3字节有效，依此类推
// =============================================

module vec_s8_to_fifo #(
    parameter integer VLEN = 16
) (
    input  wire                           clk,
    input  wire                           rstn,
    input  wire                           in_valid,
    input  wire signed [             7:0] in_vec_s8        [VLEN],
    output wire                           output_req,
    input  wire        [$clog2(VLEN)-1:0] vec_valid_num_col,
    output wire                           output_valid,
    output wire                           output_switch_row,
    input  wire                           output_ready,
    output wire        [             3:0] output_mask,
    output wire        [            31:0] output_data,
    output wire                           fifo_full_flag
);
    // 双区FIFO存储：存储完整向量，深度为VLEN
    reg signed [7:0] fifo_mem0[VLEN][VLEN];  // 区域0：VLEN个向量，每个VLEN长度
    reg signed [7:0] fifo_mem1[VLEN][VLEN];  // 区域1：VLEN个向量，每个VLEN长度
    reg [$clog2(VLEN):0] fifo_wptr0, fifo_count0;  // 区域0写指针和向量计数
    reg [$clog2(VLEN):0] fifo_wptr1, fifo_count1;  // 区域1写指针和向量计数
    reg  fifo_sel;  // 0:写0区, 1:写1区
    reg  fifo_read_sel;  // 0:读0区, 1:读1区

    // 检测in_valid下降沿作为最后一个向量信号
    reg  in_valid_q;
    wire is_last_vec = in_valid_q & ~in_valid;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) in_valid_q <= 1'b0;
        else in_valid_q <= in_valid;
    end

    // 输出握手状态机
    typedef enum reg [1:0] {
        IDLE   = 2'b00,
        REQ    = 2'b01,
        OUTPUT = 2'b10
    } state_t;
    state_t                    output_state;
    reg     [$clog2(VLEN)-1:0] stored_valid_num;  // 记录的有效字节数
    reg     [  $clog2(VLEN):0] output_ptr;  // 输出指针（32位打包索引）

    // 输出状态机

    // 写入FIFO：存储完整向量
    integer j;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            fifo_wptr0  <= 0;
            fifo_count0 <= 0;
            fifo_wptr1  <= 0;
            fifo_count1 <= 0;
            fifo_sel    <= 0;
        end else if (in_valid) begin
            // 写入当前向量到指定区域
            if (!fifo_sel && fifo_wptr0 < VLEN) begin
                for (j = 0; j < VLEN; j = j + 1) begin
                    fifo_mem0[fifo_wptr0][j] <= in_vec_s8[j];
                end
                fifo_wptr0  <= fifo_wptr0 + 1;
                fifo_count0 <= fifo_count0 + 1;
            end else if (fifo_sel && fifo_wptr1 < VLEN) begin
                for (j = 0; j < VLEN; j = j + 1) begin
                    fifo_mem1[fifo_wptr1][j] <= in_vec_s8[j];
                end
                fifo_wptr1  <= fifo_wptr1 + 1;
                fifo_count1 <= fifo_count1 + 1;
            end
        end else if (is_last_vec) begin
            // 检测到最后一个向量，切换区域
            fifo_sel <= ~fifo_sel;
        end
    end

    // 32位打包逻辑（基于stored_valid_num和当前读区域数据）
    reg [          31:0] pack_data;
    reg [           3:0] pack_mask;
    reg [$clog2(VLEN):0] read_vec_ptr;
    reg [          31:0] pack_data_reg;
    reg [           3:0] pack_mask_reg;
    reg                  output_valid_reg;

    // 组合逻辑：根据当前output_ptr生成输出数据
    always_comb begin
        read_vec_ptr = (output_ptr / (VLEN / 4));
        if (fifo_read_sel == 0) begin
            pack_data = {
                fifo_mem0[read_vec_ptr][output_ptr*4+3],
                fifo_mem0[read_vec_ptr][output_ptr*4+2],
                fifo_mem0[read_vec_ptr][output_ptr*4+1],
                fifo_mem0[read_vec_ptr][output_ptr*4+0]
            };
        end else begin
            pack_data = {
                fifo_mem1[read_vec_ptr][output_ptr*4+3],
                fifo_mem1[read_vec_ptr][output_ptr*4+2],
                fifo_mem1[read_vec_ptr][output_ptr*4+1],
                fifo_mem1[read_vec_ptr][output_ptr*4+0]
            };
        end
        if (stored_valid_num > output_ptr * 4 + 3) pack_mask = 4'b1111;
        else if (stored_valid_num > output_ptr * 4 + 2) pack_mask = 4'b0111;
        else if (stored_valid_num > output_ptr * 4 + 1) pack_mask = 4'b0011;
        else if (stored_valid_num > output_ptr * 4 + 0) pack_mask = 4'b0001;
        else pack_mask = 4'b0000;
    end

    // 时序逻辑：注册输出数据和有效信号
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            pack_data_reg    <= 0;
            pack_mask_reg    <= 0;
            output_valid_reg <= 0;
        end else begin
            if (output_state == OUTPUT) begin
                pack_data_reg    <= pack_data;
                pack_mask_reg    <= pack_mask;
                output_valid_reg <= 1'b1;
            end else begin
                output_valid_reg <= 1'b0;
            end
        end
    end

    // 输出信号
    assign output_req     = (output_state == REQ);
    assign output_valid   = output_valid_reg;
    assign output_mask    = pack_mask_reg;
    assign output_data    = pack_data_reg;
    assign fifo_full_flag = (fifo_count0 > 0) && (fifo_count1 > 0);

endmodule
