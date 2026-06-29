module ps_buffer_fifo #(
    parameter int unsigned DEPTH      = 16,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic signed [DATA_WIDTH-1:0] data_in,
    input  logic                         input_valid_i,
    input  logic                         is_init_data_i,
    input  logic                         ia_l1_switch_i,
    input  logic                         send_ia_trigger_i,
    output logic signed [DATA_WIDTH-1:0] data_out,
    output logic                         input_valid_o,
    output logic                         is_init_data_o,
    output logic                         ia_l1_switch_o,
    output logic                         send_ia_trigger_o
);
    localparam int unsigned ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
    localparam int unsigned CNT_W  = (DEPTH <= 1) ? 1 : $clog2(DEPTH + 1);

    localparam logic [ADDR_W-1:0] DEPTH_LAST_ADDR = DEPTH - 1;
    localparam logic [CNT_W-1:0]  DEPTH_COUNT     = DEPTH;

    logic [ADDR_W-1:0]             write_ptr;
    logic [ADDR_W-1:0]             read_ptr;
    logic [CNT_W-1:0]              frame_len;
    logic [CNT_W-1:0]              replay_count;
    logic                         ia_l1_switch_i_d;
    logic                         send_ia_trigger_i_d;

    logic                         ram_write_en;
    logic                         ram_read_en;
    logic [ADDR_W-1:0]             ram_write_addr;
    logic [ADDR_W-1:0]             ram_read_addr;
    logic [CNT_W-1:0]              write_ptr_ext;
    logic signed [DATA_WIDTH-1:0] ram_read_data;
    logic                         replay_data_valid;

    assign ram_write_en   = input_valid_i;
    assign ram_read_en    = (replay_count != '0);
    assign ram_write_addr = write_ptr;
    assign ram_read_addr  = read_ptr;
    assign write_ptr_ext  = write_ptr;

    // RAM read data is valid in the same externally-observed cycle as
    // replay_data_valid because both are registered on the same clock edge.
    assign data_out = replay_data_valid ? ram_read_data : '0;

    pseudo_dual_port_ram #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_W)
    ) u_ps_fifo_ram (
        .clk   (clk),
        .ena   (1'b1),
        .enb   (ram_read_en),
        .wea   (ram_write_en),
        .addra (ram_write_addr),
        .dia   (data_in),
        .addrb (ram_read_addr),
        .dob   (ram_read_data)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            write_ptr           <= '0;
            read_ptr            <= '0;
            frame_len           <= '0;
            replay_count        <= '0;
            ia_l1_switch_i_d    <= 1'b0;
            send_ia_trigger_i_d <= 1'b0;
            input_valid_o       <= 1'b0;
            is_init_data_o      <= 1'b0;
            ia_l1_switch_o      <= 1'b0;
            send_ia_trigger_o   <= 1'b0;
            replay_data_valid   <= 1'b0;
        end else begin
            ia_l1_switch_i_d    <= ia_l1_switch_i;
            send_ia_trigger_i_d <= send_ia_trigger_i;

            input_valid_o       <= input_valid_i;
            is_init_data_o      <= is_init_data_i;
            ia_l1_switch_o      <= ia_l1_switch_i;
            send_ia_trigger_o   <= send_ia_trigger_i;

            // Align external data_out masking with the synchronous RAM read.
            replay_data_valid <= ram_read_en;

            if (input_valid_i) begin
                if (write_ptr != DEPTH_LAST_ADDR) begin
                    write_ptr <= write_ptr + 1'b1;
                end
            end

            if (ia_l1_switch_i && !ia_l1_switch_i_d) begin
                if (input_valid_i) begin
                    frame_len <= (write_ptr == DEPTH_LAST_ADDR) ?
                                 DEPTH_COUNT : write_ptr_ext + 1'b1;
                end else begin
                    frame_len <= write_ptr_ext;
                end
                write_ptr    <= '0;
                read_ptr     <= '0;
                replay_count <= '0;
            end

            if (send_ia_trigger_i && !send_ia_trigger_i_d) begin
                read_ptr     <= '0;
                replay_count <= frame_len;
            end else if (replay_count != '0) begin
                if (replay_count == 1) begin
                    replay_count <= '0;
                    read_ptr     <= '0;
                end else begin
                    replay_count <= replay_count - 1'b1;
                    read_ptr     <= read_ptr + 1'b1;
                end
            end
        end
    end
endmodule
