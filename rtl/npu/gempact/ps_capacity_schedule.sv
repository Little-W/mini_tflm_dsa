// Capacity-triggered on-chip frame completion. No reset/retry, scratch DDR,
// division, or multiplication. Data storage / DMA are external service ports.
// Command commit is strictly sequential; a committed prefix is never reissued.
module ps_capacity_schedule #(
    parameter integer MAX_ROWS=32,MAX_COLS=25,
    parameter bit PREALLOCATED_BASE=0,
    parameter integer K_W=16,PAGE_W=12,
    parameter logic[23:0] NEXT_DELTA=24'd262144
)(
    input logic clk,rst_n,start,
    input logic[5:0] cfg_rows,cfg_cols,
    input logic[K_W-1:0] cfg_k_tiles,
    input logic[PAGE_W-1:0] cfg_initial_pages,free_pages,
    input logic meta_initialized,meta_wide,meta_ready,
    input logic[23:0] meta_headroom,
    output logic[5:0] query_row,query_col,
    output logic[K_W-1:0] query_k,
    output logic command_valid,
    input logic command_ready,command_complete,
    output logic command_last_k,command_finish_mode,
    output logic[1:0] required_pages,
    output logic frame_released,done,error,
    output logic[2:0] state_debug
);
    typedef enum logic[2:0]{IDLE,ISSUE,WAIT_RESULT,ADVANCE,FINISH,FAIL} st_t;
    st_t st;
    logic[5:0] rows,cols,row,col;
    logic[K_W-1:0] k,kt,kt_last,normal_k;
    logic[5:0] normal_col;
    logic draining;
    logic[MAX_COLS-1:0] active_cols;
    logic[PAGE_W:0] normal_need;
    assign state_debug=st;
    assign query_row=row;assign query_col=col;assign query_k=k;
    assign command_last_k=k==kt_last;
    assign command_finish_mode=draining;
    always_comb begin
        if(command_last_k)required_pages=0;
        else if(!meta_initialized)required_pages=PREALLOCATED_BASE?0:3;
        else if(!meta_wide && meta_headroom<NEXT_DELTA)required_pages=1;
        else required_pages=0;
    end
    assign normal_need=(PAGE_W+1)'(required_pages)+(PAGE_W+1)'(rows);
    assign command_valid=st==ISSUE && meta_ready && active_cols[col] &&
        (draining ? {1'b0,free_pages}>=(PAGE_W+1)'(required_pages) : {1'b0,free_pages}>=normal_need);
    assign done=st==FINISH || st==FAIL;assign error=st==FAIL;
    always_ff @(posedge clk)begin
        if(!rst_n)begin
            st<=IDLE;rows<=0;cols<=0;row<=0;col<=0;k<=0;kt<=0;kt_last<='1;
            draining<=0;active_cols<=0;normal_k<=0;normal_col<=0;frame_released<=0;
        end else begin
            frame_released<=0;
            case(st)
                IDLE:if(start)begin
                    rows<=cfg_rows;cols<=cfg_cols;kt<=cfg_k_tiles;kt_last<=cfg_k_tiles-1'b1;row<=0;col<=0;k<=0;
                    draining<=0;active_cols<='1;
                    if(cfg_rows==0 || cfg_rows>MAX_ROWS || cfg_cols==0 || cfg_cols>MAX_COLS || cfg_k_tiles==0 ||
                       {1'b0,free_pages} < {1'b0,cfg_initial_pages}+(PAGE_W+1)'(cfg_rows))st<=FAIL;
                    else st<=ISSUE;
                end
                ISSUE:begin
                    if(!meta_ready)begin end
                    else if(!active_cols[col])begin
                        row<=0;
                        if(col==cols-1'b1)begin col<=0;if(k==kt_last || active_cols==0)st<=FINISH;else k<=k+1'b1;end
                        else col<=col+1'b1;
                    end else if(!draining && {1'b0,free_pages}<normal_need)begin
                        if(k==0)st<=FAIL;
                        else begin draining<=1;normal_k<=k;normal_col<=col;end
                    end else if(draining && {1'b0,free_pages}<(PAGE_W+1)'(required_pages))st<=FAIL;
                    else if(command_valid && command_ready)st<=WAIT_RESULT;
                end
                WAIT_RESULT:if(command_complete)st<=ADVANCE;
                ADVANCE:begin
                    if(row!=rows-1'b1)begin row<=row+1'b1;st<=ISSUE;end
                    else begin
                        row<=0;st<=ISSUE;
                        if(draining)begin
                            if(k!=kt_last)k<=k+1'b1;
                            else begin
                                active_cols[col]<=0;frame_released<=1;draining<=0;k<=normal_k;
                                if(normal_col==cols-1'b1)begin col<=0;if(normal_k==kt_last)st<=FINISH;else k<=normal_k+1'b1;end
                                else col<=normal_col+1'b1;
                            end
                        end else if(col!=cols-1'b1)col<=col+1'b1;
                        else begin col<=0;if(k==kt_last)st<=FINISH;else k<=k+1'b1;end
                    end
                end
                FINISH,FAIL:if(!start)st<=IDLE;
                default:st<=FAIL;
            endcase
        end
    end
`ifndef SYNTHESIS
    always @(posedge clk)if(rst_n && command_valid && command_ready)begin
        assert(query_row<rows && query_col<cols && query_k<kt);
        if(draining)assert(meta_initialized) else $fatal(1,"draining an uninitialized partial sum");
    end
`endif
endmodule
