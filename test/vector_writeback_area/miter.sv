// SPDX-License-Identifier: Apache-2.0
module miter #(
    parameter int TILE=16,
    parameter int BUS_WIDTH=64,
    parameter bit BYTE_ONLY=1'b0,
    parameter int CYCLES=30000
);
    localparam int COUNT_WIDTH=$clog2(4*TILE+1);
    logic clk=0, rst_n=0;
    logic request_valid=0, request_byte_output=0, request_coalesce=0;
    logic request_last=0, flush=0, wr_granted=0, src_wready=0;
    logic wr_done=0, wr_error=0;
    logic [31:0] request_address=0;
    logic [COUNT_WIDTH-1:0] request_bytes=0;
    logic [32*TILE-1:0] result_words=0;
    wire [1:0] request_ready, busy, done, error, wr_req, wr_start, src_wvalid;
    wire [31:0] wr_base_addr[2], wr_row_stride[2], wr_rows_to_write[2];
    wire [7:0] wr_burst_len_m1[2];
    wire [BUS_WIDTH-1:0] src_wdata[2];
    wire [BUS_WIDTH/8-1:0] src_wmask[2];

    vector_writeback #(.TILE(TILE), .BUS_WIDTH(BUS_WIDTH),
        .p_coalesce_bytes_only(BYTE_ONLY)) candidate (
        .clk, .rst_n, .request_valid, .request_ready(request_ready[0]), .request_address,
        .request_bytes, .request_byte_output, .result_words, .request_coalesce,
        .request_last, .flush, .busy(busy[0]), .done(done[0]), .error(error[0]),
        .wr_req(wr_req[0]), .wr_start(wr_start[0]), .wr_granted,
        .wr_base_addr(wr_base_addr[0]), .wr_row_stride(wr_row_stride[0]),
        .wr_rows_to_write(wr_rows_to_write[0]), .wr_burst_len_m1(wr_burst_len_m1[0]),
        .src_wdata(src_wdata[0]), .src_wmask(src_wmask[0]), .src_wvalid(src_wvalid[0]),
        .src_wready, .wr_done, .wr_error
    );
    vector_writeback_reference #(.TILE(TILE), .BUS_WIDTH(BUS_WIDTH)) reference_design (
        .clk, .rst_n, .request_valid, .request_ready(request_ready[1]), .request_address,
        .request_bytes, .request_byte_output, .result_words, .request_coalesce,
        .request_last, .flush, .busy(busy[1]), .done(done[1]), .error(error[1]),
        .wr_req(wr_req[1]), .wr_start(wr_start[1]), .wr_granted,
        .wr_base_addr(wr_base_addr[1]), .wr_row_stride(wr_row_stride[1]),
        .wr_rows_to_write(wr_rows_to_write[1]), .wr_burst_len_m1(wr_burst_len_m1[1]),
        .src_wdata(src_wdata[1]), .src_wmask(src_wmask[1]), .src_wvalid(src_wvalid[1]),
        .src_wready, .wr_done, .wr_error
    );

    integer cycle, lane;
    integer accepted=0, output_beats=0, resets=0;
    logic [31:0] next_address=32'hfff8;
    initial begin
        for (cycle=0;cycle<CYCLES;cycle=cycle+1) begin
            clk=0;
            rst_n=(cycle>=3 && cycle%5003!=0);
            request_valid=($urandom_range(0,3)!=0);
            request_byte_output=$urandom_range(0,1);
            request_bytes=COUNT_WIDTH'($urandom_range(1,4*TILE));
            if (request_byte_output && $urandom_range(0,7)!=0) begin
                request_bytes=COUNT_WIDTH'($urandom_range(1,TILE));
            end
            // 向量引擎只允许字节结果合并；通用模式也覆盖数据字合并。
            request_coalesce=($urandom_range(0,3)!=0) && (!BYTE_ONLY || request_byte_output);
            request_last=($urandom_range(0,7)==0);
            flush=($urandom_range(0,31)==0);
            wr_granted=($urandom_range(0,3)!=0);
            src_wready=($urandom_range(0,3)!=0);
            wr_done=($urandom_range(0,3)==0);
            wr_error=($urandom_range(0,4)==0);
            request_address=next_address;
            for (lane=0;lane<TILE;lane=lane+1) begin
                result_words[32*lane+:32]=$urandom;
            end
            #1;
            if (rst_n && cycle>4) begin
                if (request_ready[0] !== request_ready[1] || busy[0] !== busy[1] ||
                    done[0] !== done[1] || error[0] !== error[1] || wr_req[0] !== wr_req[1] ||
                    wr_start[0] !== wr_start[1] || src_wvalid[0] !== src_wvalid[1]) begin
                    $fatal(1,"Control mismatch at cycle %0d",cycle);
                end
                if (wr_req[0] &&
                    {wr_base_addr[0],wr_row_stride[0],wr_rows_to_write[0],wr_burst_len_m1[0]} !==
                    {wr_base_addr[1],wr_row_stride[1],wr_rows_to_write[1],wr_burst_len_m1[1]}) begin
                    $fatal(1,"Request mismatch at cycle %0d",cycle);
                end
                if (src_wvalid[0]) begin
                    if (src_wmask[0] !== src_wmask[1] || src_wdata[0] !== src_wdata[1]) begin
                        $fatal(1,"Data mismatch at cycle %0d",cycle);
                    end
                    if (src_wready) begin
                        output_beats=output_beats+1;
                    end
                end
            end
            if (!rst_n) begin
                resets=resets+1;
            end
            if (request_valid && request_ready[0]) begin
                accepted=accepted+1;
                next_address=next_address+32'(request_bytes);
                if ($urandom_range(0,15)==0) begin
                    next_address=next_address+$urandom_range(1,7);
                end
            end
            clk=1;
            #1;
        end
        if (accepted<100 || output_beats<100 || resets<4) begin
            $fatal(1,"Insufficient exercised transactions");
        end
        $display("WRITEBACK_EQUIVALENCE_PASS tile=%0d bus=%0d byte_only=%0d cycles=%0d accepted=%0d beats=%0d resets=%0d",
                 TILE,BUS_WIDTH,BYTE_ONLY,CYCLES,accepted,output_beats,resets);
        $finish;
    end
endmodule
