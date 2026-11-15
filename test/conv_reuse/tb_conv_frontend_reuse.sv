module tb_conv_frontend_reuse;
    import conv_im2col_pkg::*;
    logic clk;
    initial begin clk=0;forever #5 clk=~clk;end
    logic rst_n=0,cfg_valid=0,cfg_ready;
    conv_cfg_t cfg,reference_cfg;
    logic tile_valid=0,tile_ready;
    logic [31:0] tile_p0=0,tile_q0=0;
    logic [2:0] tile_rows=0;
    logic [1:0] tile_slot=0;
    logic wr_valid,wr_ready;
    logic [1:0] wr_slot,wr_row,wr_col,wr_mask;
    logic signed[15:0] wr_data[2];
    logic tile_done,tile_error,error,busy;
    logic[31:0] stat_hits,stat_misses,stat_read_bytes;
    logic arvalid,arready,rvalid,rready,rlast;
    logic[31:0] araddr,rdata;
    logic[7:0] arlen;
    logic[2:0] arsize;
    logic[1:0] arburst,rresp;
    logic[31:0] allocation_base=32'h1003,allocation_bytes=9,epoch=1;
    logic block_ar=0,mem_active;
    longint unsigned read_bytes,ar_count;
    logic[31:0] writer_rng;
    int written=0,tiles=0;
    bit seen[4][4];
    conv_im2col_frontend #(.SIZE(4),.SLOT_W(2),.CACHE_SETS(2)) dut(
        .cfg_sched_r(32'd0),.cfg_sched_groups(32'd0),.tile_group(32'd0),.*);
    axi_counted_memory mem(.clk,.rst_n,.allocation_base,.allocation_bytes,.epoch,.block_ar,
        .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,
        .read_bytes,.ar_count,.active(mem_active));

    function automatic int direct_value(input int row,input int col);
        int p,q,oy,ox,ky,kx,ch,iy,ix;
        logic[31:0] address;
        logic[7:0] byte_value;
        p=32'(tile_p0)+row;q=32'(tile_q0)+col;
        if(q>=32'(reference_cfg.kernel_h)*32'(reference_cfg.kernel_w)*32'(reference_cfg.group_c)) return 0;
        oy=p/32'(reference_cfg.output_w);ox=p%32'(reference_cfg.output_w);
        ch=q%32'(reference_cfg.group_c);q=q/32'(reference_cfg.group_c);
        ky=q/32'(reference_cfg.kernel_w);kx=q%32'(reference_cfg.kernel_w);
        iy=oy*32'(reference_cfg.stride_h)-32'(reference_cfg.pad_top)+ky*32'(reference_cfg.dilation_h);
        ix=ox*32'(reference_cfg.stride_w)-32'(reference_cfg.pad_left)+kx*32'(reference_cfg.dilation_w);
        if(iy<0 || iy>=32'(reference_cfg.input_h) || ix<0 || ix>=32'(reference_cfg.input_w)) return 0;
        address=reference_cfg.input_base+32'((iy*32'(reference_cfg.input_w)+ix)*32'(reference_cfg.input_c)+32'(reference_cfg.group_offset)+ch);
        byte_value=8'((address*32'd29)^(address>>4)^epoch);
        return 32'($signed(byte_value))+32'($signed(reference_cfg.input_offset));
    endfunction

    always @(posedge clk) begin
        if(!rst_n) begin wr_ready<=0;writer_rng<=32'h23456789;end
        else begin
            writer_rng<={writer_rng[30:0],writer_rng[31]^writer_rng[21]^writer_rng[1]^writer_rng[0]};
            wr_ready<=writer_rng[0] || writer_rng[4];
            if(wr_valid && wr_ready) begin
                if(!busy || wr_slot!=tile_slot) $fatal(1,"invalid frontend write context");
                for(int l=0;l<2;l++) if(wr_mask[l]) begin
                    if(32'(wr_row)>=32'(tile_rows) || 32'(wr_col)+l>=4 || seen[wr_row][32'(wr_col)+l])
                        $fatal(1,"write coordinate or duplicate output");
                    if(32'($signed(wr_data[l]))!=direct_value(32'(wr_row),32'(wr_col)+l))
                        $fatal(1,"wrong/stale frontend value row=%0d col=%0d",wr_row,32'(wr_col)+l);
                    seen[wr_row][32'(wr_col)+l]=1;written=written+1;
                end
            end
        end
    end

    task automatic configure(input int mode,input logic[31:0] new_epoch);
        @(negedge clk);cfg='0;
        cfg.input_base=32'h1003;cfg.input_offset=17;
        cfg.stride_h=1;cfg.stride_w=1;cfg.dilation_h=1;cfg.dilation_w=1;
        if(mode==0) begin
            cfg.input_h=3;cfg.input_w=3;cfg.input_c=1;cfg.group_c=1;
            cfg.kernel_h=3;cfg.kernel_w=3;cfg.output_h=3;cfg.output_w=3;
            cfg.pad_top=1;cfg.pad_left=1;allocation_bytes=9;
        end else begin
            cfg.input_h=1;cfg.input_w=1;cfg.input_c=4;cfg.group_c=4;
            cfg.kernel_h=1;cfg.kernel_w=1;cfg.output_h=1;cfg.output_w=1;allocation_bytes=4;
            cfg.bypass_cache=mode==1;
            if(mode==2) begin cfg.pad_top=10;cfg.pad_left=10;end
        end
        epoch=new_epoch;reference_cfg=cfg;cfg_valid=1;
        do @(posedge clk);while(!cfg_ready);
        @(negedge clk);cfg_valid=0;cfg='0;
        if(error) $fatal(1,"valid configuration rejected");
    endtask

    task automatic tile(input int p,input int q,input int rows,input int expected_bytes,
                        input int expected_ars,input string name);
        longint unsigned before_bytes,before_ars;
        @(negedge clk);tile_p0=32'(p);tile_q0=32'(q);tile_rows=3'(rows);tile_slot=2'(tiles);
        before_bytes=read_bytes;before_ars=ar_count;written=0;
        for(int r=0;r<4;r++) for(int c=0;c<4;c++) seen[r][c]=0;
        tile_valid=1;
        do @(posedge clk);while(!tile_ready);
        @(negedge clk);tile_valid=0;
        do @(posedge clk);while(!tile_done && !tile_error);
        @(negedge clk);
        if(error || tile_error || written!=rows*4 || mem_active || rvalid) $fatal(1,"tile failure or incomplete drain");
        if(read_bytes-before_bytes!=64'(expected_bytes) || ar_count-before_ars!=64'(expected_ars))
            $fatal(1,"unexpected external reads in %s: bytes=%0d ars=%0d",name,read_bytes-before_bytes,ar_count-before_ars);
        $display("FRONTEND_REUSE_CASE name=%s bytes=%0d ars=%0d writes=%0d",name,read_bytes-before_bytes,ar_count-before_ars,written);
        tiles=tiles+1;
    endtask

    initial begin
        cfg='0;reference_cfg='0;
        repeat(5) @(posedge clk);@(negedge clk);rst_n=1;
        configure(0,1);
        tile(0,4,4,9,2,"cold_overlapping_windows");
        for(int i=0;i<9;i++) if(mem.byte_reads[i]!=1) $fatal(1,"cold input byte duplicated or skipped");
        $display("FRONTEND_COLD_INPUT_BYTES unique=9 max_reads_per_byte=1 allocation_overread=0");
        tile(0,4,4,0,0,"identical_tile_resident");
        tile(3,4,4,0,0,"new_overlapping_windows_resident");
        configure(0,23);
        tile(0,4,4,9,2,"same_address_changed_input_new_task");
        for(int i=0;i<9;i++) if(mem.byte_reads[i]!=2) $fatal(1,"new task did not reread each input byte once");
        configure(1,7);
        tile(0,1,1,3,3,"bypass_first_word");
        tile(0,2,1,0,0,"bypass_same_word_across_tiles");
        tile(0,0,1,4,4,"bypass_other_word_then_revisit");
        configure(2,7);
        tile(0,0,1,0,0,"all_padding_no_input_reads");
        for(int i=0;i<9;i++) begin
            int expected;
            expected=(i==0) ? 3 : (i<4 ? 4 : 2);
            if(mem.byte_reads[i]!=32'(expected)) $fatal(1,"frontend per-byte counts differ");
            $display("FRONTEND_EXTERNAL_BYTE address=%h reads=%0d",allocation_base+32'(i),mem.byte_reads[i]);
        end
        if(read_bytes!=25 || ar_count!=11) $fatal(1,"incorrect final traffic total");
        $display("FRONTEND_REUSE_PASS tiles=%0d actual_read_bytes=%0d actual_ar_handshakes=%0d",tiles,read_bytes,ar_count);
        $finish;
    end
    initial begin #1000000;$fatal(1,"frontend reuse timeout");end
endmodule
