// Passive simulation instrumentation, absent from synthesis and datapath.
`ifndef SYNTHESIS
`ifdef GEMMORA_PS_SECTOR_CODEC
`ifdef PS_CODEC_MEASURE
module ps_codec_measure #(
    parameter integer FRAMES=25, ROWS=13702
)(input logic clk,rst_n,write_en,read_en,frame_end,
  input logic long_record,input logic [15:0] exception_mask,
  input logic [31:0] used_sectors,
  input logic [3:0] bank_we,bank_re,
  input logic capacity_fault);
    longint unsigned cycle,frame,wr,rd,longs,exceptions,sector_w,sector_r;
    longint unsigned last_wr,last_rd,last_longs,last_exceptions,last_sw,last_sr;
    integer fd;string filename;
    logic commit_q,commit_qq;
    initial begin
        fd=0;
        if($value$plusargs("PS_FRAME_LOG=%s",filename)) begin
            fd=$fopen(filename,"w");
            if(!fd)$fatal(1,"cannot open PS frame trace");
            $fdisplay(fd,"frame,cycle,rows_written,rows_read,long_rows,exception_values,payload_write_bytes,payload_read_bytes,occupied_payload_bytes,allocator_wait_cycles,port_wait_cycles,capacity_fault");
        end
    end
    always @(posedge clk) begin
        if(!rst_n) begin
            cycle=0;frame=0;wr=0;rd=0;longs=0;exceptions=0;sector_w=0;sector_r=0;
            last_wr=0;last_rd=0;last_longs=0;last_exceptions=0;last_sw=0;last_sr=0;
            commit_q<=0;commit_qq<=0;
        end else begin
            cycle++;
            commit_q<=frame_end;commit_qq<=commit_q;
            if(write_en&&!capacity_fault)begin wr++;longs+=int'(long_record);exceptions+=$countones(exception_mask);end
            if(read_en&&!capacity_fault)rd++;
            sector_w+=$countones(bank_we);sector_r+=$countones(bank_re);
        end
    end
    always @(negedge clk) if(rst_n && commit_qq && wr>last_wr)begin
        if(fd)$fdisplay(fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,0,0,%0d",frame,cycle,wr-last_wr,rd-last_rd,longs-last_longs,exceptions-last_exceptions,16*(sector_w-last_sw),16*(sector_r-last_sr),16*used_sectors,capacity_fault);
        frame++;last_wr=wr;last_rd=rd;last_longs=longs;last_exceptions=exceptions;last_sw=sector_w;last_sr=sector_r;
    end
    final if(fd)$fclose(fd);
endmodule
bind ps_buffer_wide_fifo ps_codec_measure #(.FRAMES(FRAME_COUNT),.ROWS(DEPTH)) u_codec_measure(
 .clk(clk),.rst_n(rst_n),.write_en(ram_write_en_q),.read_en(ram_read_en),
 .frame_end(ia_l1_switch_i&&!ia_l1_switch_i_d),
 .long_record(u_ps_fifo_ram.encode_long),.exception_mask(u_ps_fifo_ram.exception_mask),
 .used_sectors(32'(u_ps_fifo_ram.used_sectors)),
 .bank_we({u_ps_fifo_ram.bank_we[3],u_ps_fifo_ram.bank_we[2],u_ps_fifo_ram.bank_we[1],u_ps_fifo_ram.bank_we[0]}),
 .bank_re({u_ps_fifo_ram.bank_re[3],u_ps_fifo_ram.bank_re[2],u_ps_fifo_ram.bank_re[1],u_ps_fifo_ram.bank_re[0]}),
 .capacity_fault(u_ps_fifo_ram.capacity_fault));
`endif
`endif
`endif
