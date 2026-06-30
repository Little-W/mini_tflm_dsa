module ddr_icb_mem_model #(
    parameter int unsigned WIDTH  = 32,
    parameter int unsigned ADDR_W = 19,
    parameter int unsigned LEN_W  = 4,
    parameter int unsigned MW     = WIDTH / 8,
    parameter int unsigned DP     = 131072
) (
    input  logic              clk,
    input  logic              rst_n,

    input  logic              sa_icb_cmd_valid,
    output logic              sa_icb_cmd_ready,
    input  logic [ADDR_W-1:0] sa_icb_cmd_addr,
    input  logic              sa_icb_cmd_read,
    input  logic [LEN_W-1:0]  sa_icb_cmd_len,
    input  logic [WIDTH-1:0]  sa_icb_cmd_wdata,
    input  logic [MW-1:0]     sa_icb_cmd_wmask,
    input  logic              sa_icb_w_valid,
    output logic              sa_icb_w_ready,
    output logic              sa_icb_rsp_valid,
    input  logic              sa_icb_rsp_ready,
    output logic [WIDTH-1:0]  sa_icb_rsp_rdata,
    output logic              sa_icb_rsp_err
);

    typedef enum logic [2:0] {
        S_IDLE,
        S_CMD_WAIT,
        S_WRITE_WAIT,
        S_RSP_WAIT,
        S_RSP
    } state_t;

    state_t state;

    logic [WIDTH-1:0] mem_r [0:DP-1];

    int unsigned rand_enable;
    int unsigned cmd_max_lat;
    int unsigned w_max_lat;
    int unsigned rsp_max_lat;
    int unsigned seed;

    int unsigned wait_cnt;
    logic cmd_read_r;
    logic [ADDR_W-1:0] cmd_addr_r;
    logic [LEN_W-1:0] cmd_len_r;
    logic [WIDTH-1:0] cmd_wdata_r;
    logic [MW-1:0] cmd_wmask_r;
    logic [LEN_W:0] rsp_left;
    logic [ADDR_W-1:0] rsp_addr;
    logic [WIDTH-1:0] rsp_data_r;

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
        seed        = 32'hdd12_cafe;
        void'($value$plusargs("DDR_RAND_LAT=%d", rand_enable));
        void'($value$plusargs("DDR_CMD_MAX_LAT=%d", cmd_max_lat));
        void'($value$plusargs("DDR_W_MAX_LAT=%d", w_max_lat));
        void'($value$plusargs("DDR_RSP_MAX_LAT=%d", rsp_max_lat));
        void'($value$plusargs("DDR_SEED=%d", seed));
        dummy = $urandom(seed);
        if (rand_enable != 0) begin
            $display("[DDR_MEM] seed=%0d read_cmd_max=%0d write_cmd_max=%0d rsp_max=%0d",
                     seed, cmd_max_lat, w_max_lat, rsp_max_lat);
        end
    end

    wire cmd_hs = sa_icb_cmd_valid && sa_icb_cmd_ready;
    wire w_hs   = sa_icb_w_valid && sa_icb_w_ready;
    wire rsp_hs = sa_icb_rsp_valid && sa_icb_rsp_ready;
    wire [ADDR_W-3:0] cmd_word_idx = cmd_addr_r[ADDR_W-1:2];
    wire [ADDR_W-3:0] bus_word_idx = sa_icb_cmd_addr[ADDR_W-1:2];
    wire [ADDR_W-1:0] rsp_next_addr = rsp_addr + ADDR_W'(MW);

    assign sa_icb_cmd_ready = (state == S_CMD_WAIT) && (wait_cnt == 0);
    assign sa_icb_w_ready   = (state == S_WRITE_WAIT) && (wait_cnt == 0);
    assign sa_icb_rsp_valid = (state == S_RSP);
    assign sa_icb_rsp_rdata = rsp_data_r;
    assign sa_icb_rsp_err   = 1'b0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= S_IDLE;
            wait_cnt   <= 0;
            cmd_read_r <= 1'b0;
            cmd_addr_r <= '0;
            cmd_len_r  <= '0;
            cmd_wdata_r <= '0;
            cmd_wmask_r <= '0;
            rsp_left   <= '0;
            rsp_addr   <= '0;
            rsp_data_r <= '0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (sa_icb_cmd_valid) begin
                        wait_cnt <= pick_wait(cmd_max_lat);
                        state      <= S_CMD_WAIT;
                    end
                end

                S_CMD_WAIT: begin
                    if (!sa_icb_cmd_valid) begin
                        state <= S_IDLE;
                    end else if (wait_cnt != 0) begin
                        wait_cnt <= wait_cnt - 1;
                    end else if (cmd_hs) begin
                        cmd_read_r  <= sa_icb_cmd_read;
                        cmd_addr_r  <= sa_icb_cmd_addr;
                        cmd_len_r   <= sa_icb_cmd_len;
                        cmd_wdata_r <= sa_icb_cmd_wdata;
                        cmd_wmask_r <= sa_icb_cmd_wmask;
                        if (sa_icb_cmd_read) begin
                            rsp_left   <= {1'b0, sa_icb_cmd_len} + 1'b1;
                            rsp_addr   <= sa_icb_cmd_addr;
                            rsp_data_r <= mem_r[bus_word_idx];
                            wait_cnt   <= pick_wait(rsp_max_lat);
                            state      <= S_RSP_WAIT;
                        end else begin
                            wait_cnt <= pick_wait(w_max_lat);
                            state    <= S_WRITE_WAIT;
                        end
                    end
                end

                S_WRITE_WAIT: begin
                    if (wait_cnt != 0) begin
                        wait_cnt <= wait_cnt - 1;
                    end else if (w_hs) begin
                        for (int b = 0; b < MW; b++) begin
                            if (cmd_wmask_r[b]) begin
                                mem_r[cmd_word_idx][b*8+:8] <= cmd_wdata_r[b*8+:8];
                            end
                        end
                        rsp_data_r <= '0;
                        wait_cnt   <= pick_wait(rsp_max_lat);
                        state      <= S_RSP_WAIT;
                    end
                end

                S_RSP_WAIT: begin
                    if (wait_cnt != 0) begin
                        wait_cnt <= wait_cnt - 1;
                    end else begin
                        state <= S_RSP;
                    end
                end

                S_RSP: begin
                    if (rsp_hs) begin
                        if (cmd_read_r && (rsp_left > 1)) begin
                            rsp_left   <= rsp_left - 1'b1;
                            rsp_addr   <= rsp_next_addr;
                            rsp_data_r <= mem_r[rsp_next_addr[ADDR_W-1:2]];
                            wait_cnt   <= pick_wait(rsp_max_lat);
                            state      <= S_RSP_WAIT;
                        end else begin
                            rsp_left <= '0;
                            state    <= S_IDLE;
                        end
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
