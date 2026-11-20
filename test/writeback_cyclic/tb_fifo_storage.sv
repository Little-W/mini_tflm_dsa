`timescale 1ns/1ps
module tb_fifo_storage;
    localparam BUS_WIDTH=`TB_BUS_WIDTH, NB=BUS_WIDTH/8, VLEN=16, BANKS=32, BEATS=VLEN/NB;
    logic clk=0;
    always #5 clk=!clk;
    logic in_valid=0,write_bank_blocked=0,ram_read_en=0,issue_transpose_mode=0;
    logic [4:0] write_bank=0,read_bank=0;
    logic [3:0] write_ptr=0,issue_read_ptr=0;
    logic [$clog2(BEATS)-1:0] issue_beat_idx=0;
    logic [127:0] in_vec_s8=0;
    wire [BUS_WIDTH-1:0] old_data,new_data;
    fifo_storage_extracted #(.BUS_WIDTH(BUS_WIDTH),.p_cyclic_storage(0)) old_storage(
        .*,.output_data(old_data),.output_mask(),.o_wr_en(),.o_wr_addr(),.o_rd_addr(),.o_wr_data());
    fifo_storage_extracted #(.BUS_WIDTH(BUS_WIDTH),.p_cyclic_storage(1)) new_storage(
        .*,.output_data(new_data),.output_mask(),.o_wr_en(),.o_wr_addr(),.o_rd_addr(),.o_wr_data());
    byte unsigned memory[BANKS][VLEN][VLEN];
    logic [BUS_WIDTH-1:0] expected='0;
    bit checking=0;
    int cycles=0,checked_bytes=0,collisions=0,holds=0;
    task automatic step(input bit wr,input int tile,input int row,input bit blocked,
        input bit rd,input int rtile,input int rrow,input int beat,input bit transpose);
        @(negedge clk);
        in_valid=wr;write_bank=5'(tile);write_ptr=4'(row);write_bank_blocked=blocked;
        ram_read_en=rd;read_bank=5'(rtile);issue_read_ptr=4'(rrow);
        issue_beat_idx=$clog2(BEATS)'(beat);issue_transpose_mode=transpose;
        for(int col=0;col<VLEN;col++) in_vec_s8[col*8+:8]=8'($urandom());
        if(rd) begin
            for(int lane=0;lane<NB;lane++)
                expected[lane*8+:8]=transpose ? memory[rtile][beat*NB+lane][rrow] : memory[rtile][rrow][beat*NB+lane];
            checking=1;
            if(wr&&!blocked&&tile==rtile&& (transpose ? (row/NB==beat) : row==rrow)) collisions++;
        end else if(checking) holds++;
        // 期望读取值在写入参考数组前形成，覆盖同步同地址读取旧数据。
        if(wr&&!blocked) for(int col=0;col<VLEN;col++) memory[tile][row][col]=in_vec_s8[col*8+:8];
        @(posedge clk);#1;
        cycles++;
        if(checking) begin
            assert(old_data===expected&&new_data===expected)
                else $fatal(1,"storage mismatch cycle=%0d transpose=%0d tile=%0d row=%0d beat=%0d old=%h new=%h expected=%h",
                    cycles,transpose,rtile,rrow,beat,old_data,new_data,expected);
            checked_bytes+=NB;
        end
    endtask
    initial begin
        for(int tile=0;tile<BANKS;tile++) for(int row=0;row<VLEN;row++)
            step(1,tile,row,0,0,0,0,0,0);
        for(int mode=0;mode<2;mode++) for(int tile=0;tile<BANKS;tile++)
            for(int row=0;row<VLEN;row++) for(int beat=0;beat<BEATS;beat++)
                step(0,0,0,0,1,tile,row,beat,1'(mode));
        for(int mode=0;mode<2;mode++) for(int tile=0;tile<BANKS;tile++)
            for(int row=0;row<VLEN;row++) for(int beat=0;beat<BEATS;beat++) begin
                step(1,tile,mode ? beat*NB+(row%NB) : row,0,1,tile,row,beat,1'(mode));
                step(0,0,0,0,1,tile,row,beat,1'(mode));
            end
        repeat(20000) step($urandom_range(0,1),$urandom_range(0,BANKS-1),$urandom_range(0,VLEN-1),
            $urandom_range(0,7)==0,$urandom_range(0,7)!=0,$urandom_range(0,BANKS-1),
            $urandom_range(0,VLEN-1),$urandom_range(0,BEATS-1),$urandom_range(0,1));
        assert(collisions>=BANKS*VLEN*BEATS*2&&holds>0);
        $display("FIFO_STORAGE_PASS cycles=%0d checked_bytes=%0d collisions=%0d holds=%0d",cycles,checked_bytes,collisions,holds);
        $finish;
    end
endmodule
