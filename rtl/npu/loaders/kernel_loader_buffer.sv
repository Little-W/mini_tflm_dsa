module kernel_loader_buffer #(
    parameter int unsigned DATA_WIDTH = 8,
    parameter int unsigned SIZE = 4
) (
    input logic clk, rst_n,
    input logic cache_flush = 1'b0,
    input logic discard_head = 1'b0,
    input logic load_start,
    output logic load_slot_id,
    input logic row_valid,
    input logic row_slot,
    input logic [$clog2(SIZE)-1:0] row_idx,
    input logic signed [DATA_WIDTH-1:0] row_data [SIZE],
    input logic load_done,
    input logic done_slot,
    input logic send_start,
    output logic load_ready,
    output logic load_commit,
    output logic load_commit_slot,
    output logic discard_ready,
    output logic weight_data_valid,
    output logic weight_sending_done,
    output logic store_weight_req,
    output logic signed [DATA_WIDTH-1:0] weight_out [SIZE]
);
    localparam int SLOT_COUNT=2;
    localparam int IDX_W=(SIZE<=1)?1:$clog2(SIZE);
    localparam int VALID_W=$clog2(SIZE+1);
    localparam int ROW_VEC_W=DATA_WIDTH*SIZE;
    logic wr_slot,rd_slot;
    logic [SLOT_COUNT-1:0] slot_reserved,slot_loaded;
    logic [1:0] valid_count;
    logic [VALID_W-1:0] load_valid_cols[SLOT_COUNT],slot_valid_cols[SLOT_COUNT];
    logic [VALID_W-1:0] send_valid_cols;
    logic [IDX_W-1:0] emit_col_idx;
    logic send_active,send_pending,send_prefetch,row_rd_en;
    logic row_valid_q,row_slot_q,load_done_q,done_slot_q;
    logic [IDX_W-1:0] row_idx_q;
    logic [SIZE-1:0] row_wr_bank_q;
    logic [ROW_VEC_W-1:0] row_data_vec,row_data_vec_q;
    logic [ROW_VEC_W-1:0] row_rd_data[SIZE];
    assign load_slot_id=wr_slot;
    assign load_ready=!cache_flush && !slot_reserved[wr_slot];
    assign weight_data_valid=!cache_flush && slot_loaded[rd_slot] && !send_active && !send_pending && !send_prefetch;
    assign discard_ready=weight_data_valid;
    wire discard_fire=discard_head && discard_ready;
    always_comb begin
        row_data_vec='0;
        for(int c=0;c<SIZE;c++)row_data_vec[c*DATA_WIDTH+:DATA_WIDTH]=row_data[c];
    end
    for(genvar row_bank=0;row_bank<SIZE;row_bank++)begin:gen_row_ram
        kernel_loader_row_ram #(.DATA_WIDTH(ROW_VEC_W),.DEPTH(SLOT_COUNT),.ADDR_WIDTH(1)) u_row_ram(
            .clk,.wr_en(row_wr_bank_q[row_bank] && slot_reserved[row_slot_q] && !cache_flush),
            .wr_addr(row_slot_q),.wr_data(row_data_vec_q),.rd_en(row_rd_en),
            .rd_addr(rd_slot),.rd_data(row_rd_data[row_bank]));
    end
    always_ff @(posedge clk)begin
        if(!rst_n || cache_flush)begin
            wr_slot<=0;rd_slot<=0;slot_reserved<=0;slot_loaded<=0;valid_count<=0;
            send_valid_cols<=0;emit_col_idx<=0;send_active<=0;send_pending<=0;send_prefetch<=0;
            row_valid_q<=0;row_slot_q<=0;load_done_q<=0;done_slot_q<=0;row_idx_q<=0;
            row_wr_bank_q<=0;row_data_vec_q<=0;row_rd_en<=0;
            store_weight_req<=0;weight_sending_done<=0;load_commit<=0;load_commit_slot<=0;
            for(int s=0;s<SLOT_COUNT;s++)begin load_valid_cols[s]<=0;slot_valid_cols[s]<=0;end
            for(int c=0;c<SIZE;c++)weight_out[c]<=0;
        end else begin
            logic send_complete_event;
            logic [VALID_W-1:0] row_count_next;
            send_complete_event=0;
            row_count_next=load_valid_cols[row_slot_q];
            if(row_valid_q && VALID_W'(row_idx_q)+VALID_W'(1)>row_count_next)
                row_count_next=VALID_W'(row_idx_q)+VALID_W'(1);
            row_valid_q<=row_valid;row_slot_q<=row_slot;row_idx_q<=row_idx;
            load_done_q<=load_done;done_slot_q<=done_slot;row_data_vec_q<=row_data_vec;
            row_wr_bank_q<='0;
            if(row_valid)row_wr_bank_q[row_idx]<=1'b1;
            row_rd_en<=0;store_weight_req<=0;weight_sending_done<=0;load_commit<=0;
            if(load_start && load_ready)begin
                slot_reserved[wr_slot]<=1;
                slot_loaded[wr_slot]<=0;
                load_valid_cols[wr_slot]<=0;
                wr_slot<=~wr_slot;
            end
            if(row_valid_q)load_valid_cols[row_slot_q]<=row_count_next;
            if(load_done_q)begin
                load_commit<=1;load_commit_slot<=done_slot_q;
                slot_loaded[done_slot_q]<=1;
                slot_valid_cols[done_slot_q]<=row_valid_q && row_slot_q==done_slot_q ?
                    row_count_next : load_valid_cols[done_slot_q];
            end
            if(discard_fire)begin
                slot_reserved[rd_slot]<=0;slot_loaded[rd_slot]<=0;rd_slot<=~rd_slot;
            end
            if(send_start && weight_data_valid && !discard_fire)begin
                send_pending<=1;row_rd_en<=1;send_valid_cols<=slot_valid_cols[rd_slot];
            end
            if(send_pending)begin
                send_pending<=0;send_prefetch<=1;
                // Each row RAM has captured the complete tile in its output
                // register. Reuse its storage while these registers feed PEs.
                slot_reserved[rd_slot]<=0;slot_loaded[rd_slot]<=0;
            end else if(send_prefetch && !send_active)begin
                // Emit physical rows in reverse; column c uses reduction (row+c)%SIZE.
                send_active<=1;send_prefetch<=0;store_weight_req<=1;
                for(int c=0;c<SIZE;c++)weight_out[c]<=VALID_W'(c)<send_valid_cols ?
                    $signed(row_rd_data[c][((SIZE-1+c)%SIZE)*DATA_WIDTH+:DATA_WIDTH]) : '0;
                if(SIZE==1)begin send_active<=0;weight_sending_done<=1;send_complete_event=1;end
                else emit_col_idx<=IDX_W'(SIZE-2);
            end else if(send_active)begin
                store_weight_req<=1;
                for(int c=0;c<SIZE;c++)weight_out[c]<=VALID_W'(c)<send_valid_cols ?
                    $signed(row_rd_data[c][((int'(emit_col_idx)+c)%SIZE)*DATA_WIDTH+:DATA_WIDTH]) : '0;
                if(emit_col_idx==0)begin send_active<=0;weight_sending_done<=1;send_complete_event=1;end
                else emit_col_idx<=emit_col_idx-1'b1;
            end
            if(send_complete_event)rd_slot<=~rd_slot;
            case({load_done_q,(send_pending || discard_fire)})
                2'b10:valid_count<=valid_count+1'b1;
                2'b01:valid_count<=valid_count-1'b1;
                default:;
            endcase

        end
    end
endmodule

module kernel_loader_row_ram #(
    parameter int unsigned DATA_WIDTH = 128,
    parameter int unsigned DEPTH = 2,
    parameter int unsigned ADDR_WIDTH = 1
) (
    input  logic                  clk,
    input  logic                  wr_en,
    input  logic [ADDR_WIDTH-1:0] wr_addr,
    input  logic [DATA_WIDTH-1:0] wr_data,
    input  logic                  rd_en,
    input  logic [ADDR_WIDTH-1:0] rd_addr,
    output logic [DATA_WIDTH-1:0] rd_data
);

`ifdef ASIC_SRAM
  smic40_sram_1r1w #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH)) u_sram (
    .clk(clk), .write_enable(wr_en), .write_address(wr_addr), .write_data(wr_data),
    .write_mask({DATA_WIDTH{1'b1}}), .read_enable(rd_en), .read_address(rd_addr), .read_data(rd_data));
`else
  (* ram_style = "block" *) logic [DATA_WIDTH-1:0] mem [0:DEPTH-1];

  always_ff @(posedge clk) begin
    if (wr_en) begin
      mem[wr_addr] <= wr_data;
    end
    if (rd_en) begin
      rd_data <= mem[rd_addr];
    end
  end

`endif

endmodule
