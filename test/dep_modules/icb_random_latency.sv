module icb_random_latency #(
    parameter int unsigned WIDTH  = 32,
    parameter int unsigned ADDR_W = 19,
    parameter int unsigned LEN_W  = 4,
    parameter int unsigned MW     = WIDTH / 8,
    parameter int unsigned RSP_FIFO_DEPTH = 64
) (
    input  logic              clk,
    input  logic              rst_n,

    input  logic              s_icb_cmd_valid,
    output logic              s_icb_cmd_ready,
    input  logic [ADDR_W-1:0] s_icb_cmd_addr,
    input  logic              s_icb_cmd_read,
    input  logic [LEN_W-1:0]  s_icb_cmd_len,
    input  logic [WIDTH-1:0]  s_icb_cmd_wdata,
    input  logic [MW-1:0]     s_icb_cmd_wmask,
    input  logic              s_icb_w_valid,
    output logic              s_icb_w_ready,
    output logic              s_icb_rsp_valid,
    input  logic              s_icb_rsp_ready,
    output logic [WIDTH-1:0]  s_icb_rsp_rdata,
    output logic              s_icb_rsp_err,

    output logic              m_icb_cmd_valid,
    input  logic              m_icb_cmd_ready,
    output logic [ADDR_W-1:0] m_icb_cmd_addr,
    output logic              m_icb_cmd_read,
    output logic [LEN_W-1:0]  m_icb_cmd_len,
    output logic [WIDTH-1:0]  m_icb_cmd_wdata,
    output logic [MW-1:0]     m_icb_cmd_wmask,
    output logic              m_icb_w_valid,
    input  logic              m_icb_w_ready,
    input  logic              m_icb_rsp_valid,
    output logic              m_icb_rsp_ready,
    input  logic [WIDTH-1:0]  m_icb_rsp_rdata,
    input  logic              m_icb_rsp_err
);

    int unsigned rand_enable;
    int unsigned cmd_max_lat;
    int unsigned w_max_lat;
    int unsigned rsp_max_lat;
    int unsigned seed;

    logic cmd_active;
    logic w_active;
    int unsigned cmd_wait;
    int unsigned w_wait;

    localparam int unsigned RSP_PTR_W = $clog2(RSP_FIFO_DEPTH);
    logic [WIDTH-1:0] rsp_data_fifo [RSP_FIFO_DEPTH];
    logic             rsp_err_fifo  [RSP_FIFO_DEPTH];
    int unsigned      rsp_wait_fifo [RSP_FIFO_DEPTH];
    logic [RSP_PTR_W-1:0] rsp_wptr;
    logic [RSP_PTR_W-1:0] rsp_rptr;
    logic [RSP_PTR_W:0]   rsp_count;

    function automatic int unsigned pick_wait(input int unsigned max_lat);
        if ((rand_enable == 0) || (max_lat == 0)) begin
            pick_wait = 0;
        end else begin
            pick_wait = $urandom_range(max_lat, 0);
        end
    endfunction

    initial begin
        int unsigned dummy;
        rand_enable = 0;
        cmd_max_lat = 0;
        w_max_lat   = 0;
        rsp_max_lat = 0;
        seed        = 32'h5eed_cafe;
        void'($value$plusargs("DDR_RAND_LAT=%d", rand_enable));
        void'($value$plusargs("DDR_CMD_MAX_LAT=%d", cmd_max_lat));
        void'($value$plusargs("DDR_W_MAX_LAT=%d", w_max_lat));
        void'($value$plusargs("DDR_RSP_MAX_LAT=%d", rsp_max_lat));
        void'($value$plusargs("DDR_SEED=%d", seed));
        dummy = $urandom(seed);
        if (rand_enable != 0) begin
            $display("[DDR_LAT] enabled seed=%0d cmd_max=%0d w_max=%0d rsp_max=%0d",
                     seed, cmd_max_lat, w_max_lat, rsp_max_lat);
        end
    end

    wire cmd_bypass = (rand_enable == 0) || (cmd_max_lat == 0);
    wire w_bypass   = (rand_enable == 0) || (w_max_lat == 0);
    wire rsp_bypass = (rand_enable == 0) || (rsp_max_lat == 0);
    wire cmd_open   = cmd_bypass || (cmd_active && (cmd_wait == 0));
    wire w_open     = w_bypass || (w_active && (w_wait == 0));
    wire rsp_fifo_empty = (rsp_count == 0);
    wire rsp_fifo_full  = (rsp_count == RSP_FIFO_DEPTH);
    wire rsp_fifo_ready = !rsp_fifo_empty && (rsp_wait_fifo[rsp_rptr] == 0);
    wire rsp_delay_mode = !rsp_bypass;
    wire rsp_enq = rsp_delay_mode && m_icb_rsp_valid && m_icb_rsp_ready;
    wire rsp_deq = rsp_delay_mode && s_icb_rsp_valid && s_icb_rsp_ready;

    assign m_icb_cmd_valid = s_icb_cmd_valid && cmd_open;
    assign s_icb_cmd_ready = m_icb_cmd_ready && cmd_open;
    assign m_icb_cmd_addr  = s_icb_cmd_addr;
    assign m_icb_cmd_read  = s_icb_cmd_read;
    assign m_icb_cmd_len   = s_icb_cmd_len;
    assign m_icb_cmd_wdata = s_icb_cmd_wdata;
    assign m_icb_cmd_wmask = s_icb_cmd_wmask;

    assign m_icb_w_valid = s_icb_w_valid && w_open;
    assign s_icb_w_ready = m_icb_w_ready && w_open;

    assign s_icb_rsp_valid = rsp_delay_mode ? rsp_fifo_ready : m_icb_rsp_valid;
    assign m_icb_rsp_ready = rsp_delay_mode ? !rsp_fifo_full : s_icb_rsp_ready;
    assign s_icb_rsp_rdata = rsp_delay_mode ? rsp_data_fifo[rsp_rptr] : m_icb_rsp_rdata;
    assign s_icb_rsp_err   = rsp_delay_mode ? rsp_err_fifo[rsp_rptr] : m_icb_rsp_err;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cmd_active <= 1'b0;
            w_active   <= 1'b0;
            cmd_wait   <= 0;
            w_wait     <= 0;
            rsp_wptr   <= '0;
            rsp_rptr   <= '0;
            rsp_count  <= '0;
        end else if (rand_enable == 0) begin
            cmd_active <= 1'b0;
            w_active   <= 1'b0;
            cmd_wait   <= 0;
            w_wait     <= 0;
            rsp_wptr   <= '0;
            rsp_rptr   <= '0;
            rsp_count  <= '0;
        end else begin
            if (cmd_bypass || !s_icb_cmd_valid) begin
                cmd_active <= 1'b0;
                cmd_wait   <= 0;
            end else if (!cmd_active) begin
                cmd_active <= 1'b1;
                cmd_wait   <= pick_wait(cmd_max_lat);
            end else if (cmd_wait != 0) begin
                cmd_wait <= cmd_wait - 1;
            end else if (s_icb_cmd_ready) begin
                cmd_active <= 1'b0;
            end

            if (w_bypass || !s_icb_w_valid) begin
                w_active <= 1'b0;
                w_wait   <= 0;
            end else if (!w_active) begin
                w_active <= 1'b1;
                w_wait   <= pick_wait(w_max_lat);
            end else if (w_wait != 0) begin
                w_wait <= w_wait - 1;
            end else if (s_icb_w_ready) begin
                w_active <= 1'b0;
            end

            if (rsp_bypass) begin
                rsp_wptr  <= '0;
                rsp_rptr  <= '0;
                rsp_count <= '0;
            end else begin
                if (rsp_enq) begin
                    rsp_data_fifo[rsp_wptr] <= m_icb_rsp_rdata;
                    rsp_err_fifo[rsp_wptr]  <= m_icb_rsp_err;
                    rsp_wait_fifo[rsp_wptr] <= pick_wait(rsp_max_lat);
                    rsp_wptr <= rsp_wptr + 1'b1;
                end

                if (!rsp_fifo_empty && (rsp_wait_fifo[rsp_rptr] != 0)) begin
                    rsp_wait_fifo[rsp_rptr] <= rsp_wait_fifo[rsp_rptr] - 1;
                end

                if (rsp_deq) begin
                    rsp_rptr <= rsp_rptr + 1'b1;
                end

                case ({rsp_enq, rsp_deq})
                    2'b10: rsp_count <= rsp_count + 1'b1;
                    2'b01: rsp_count <= rsp_count - 1'b1;
                    default: rsp_count <= rsp_count;
                endcase
            end
        end
    end

endmodule
