module tb_shared_bank_registers;
    localparam int PROFILES = 19;
    localparam logic [31:0] CAPS [PROFILES] = '{
        32'h01100037,32'h01100037,32'h01100037,32'h0110003f,32'h01100027,
        32'h01100027,32'h01100027,32'h01100027,32'h01100027,32'h00000000,
        32'h01100037,32'h01100037,32'h01100037,32'h01100037,32'h01100037,
        32'h01100037,32'h01100037,32'h01100037,32'h01100037};
    localparam int unsigned TOTAL [PROFILES] = '{12288,14336,16384,14336,0,0,0,0,0,0,
        18432,6144,7168,8192,9216,24576,28672,32768,36864};
    localparam int unsigned BANK_BYTES [PROFILES] = '{2048,2048,2048,2048,0,0,0,0,0,0,
        2048,1024,1024,1024,1024,4096,4096,4096,4096};
    localparam int unsigned POOL [PROFILES] = '{10240,12288,14336,12288,12288,2048,4096,6144,8192,0,
        16384,5120,6144,7168,8192,20480,24576,28672,32768};
    localparam logic [31:0] MASK [PROFILES] = '{32'h16,32'h16,32'h16,32'h16,0,0,0,0,0,0,
        32'h16,32'h16,32'h16,32'h16,32'h16,32'h16,32'h16,32'h16,32'h16};
    localparam logic [31:0] ALL = (32'd1<<PROFILES)-1;
    logic clk=0,rst_n=0;
    always #5 clk=~clk;
    logic [15:0] awaddr=0,araddr=0;
    logic [31:0] wdata=0;
    logic [3:0] wstrb=0;
    logic awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
    logic sa_ready=1,done_valid=0;
    wire [PROFILES-1:0] awready,wready,bvalid,arready,rvalid,busy,calc_start;
    wire [1:0] bresp [PROFILES],rresp [PROFILES];
    wire [31:0] rdata [PROFILES],allocation [PROFILES];
    logic [31:0] expected_allocation [PROFILES];
    bit expected_busy=0;
    integer checks=0,reads=0,writes=0,rejected=0;

    for(genvar i=0;i<PROFILES;i++) begin:g_profile
        npu_axil_reg_if #(
            .PS_CAPS(CAPS[i]),.PS_POOL_BYTES(POOL[i]),.IA_CACHE_BYTES(2048),
            .AXI_DATA_BITS((i%2)!=0 ? 64 : 32),
            .SHARED_TOTAL_BYTES(TOTAL[i]),.SHARED_BANK_BYTES(BANK_BYTES[i]),
            .SHARED_IA_BANK_MASK(MASK[i]),.PS_DIRECTORY_ROWS(TOTAL[i]!=0 ? 1024 : 0)
        ) dut (
            .clk,.rst_n,
            .s_axil_awaddr(awaddr),.s_axil_awprot(3'd0),.s_axil_awvalid(awvalid),.s_axil_awready(awready[i]),
            .s_axil_wdata(wdata),.s_axil_wstrb(wstrb),.s_axil_wvalid(wvalid),.s_axil_wready(wready[i]),
            .s_axil_bresp(bresp[i]),.s_axil_bvalid(bvalid[i]),.s_axil_bready(bready),
            .s_axil_araddr(araddr),.s_axil_arprot(3'd0),.s_axil_arvalid(arvalid),.s_axil_arready(arready[i]),
            .s_axil_rdata(rdata[i]),.s_axil_rresp(rresp[i]),.s_axil_rvalid(rvalid[i]),.s_axil_rready(rready),
            .npu_sa_ready(sa_ready),.npu_done_valid(done_valid),.npu_err_code(2'd0),
            .npu_busy(busy[i]),.calc_start(calc_start[i]),.cfg_shared_ia_banks(allocation[i])
        );
    end

    task automatic check(input bit good,input string message);
        if(!good)$fatal(1,"%s",message);
        checks++;
    endtask

    function automatic logic[31:0] expected_read(input int profile,input logic[15:0] address);
        case(address)
            16'h0124:return CAPS[profile];
            16'h0134:return TOTAL[profile]!=0 ? TOTAL[profile]-expected_allocation[profile]*BANK_BYTES[profile] :
                32'(POOL[profile]);
            16'h0138:return TOTAL[profile]!=0 ? expected_allocation[profile]*BANK_BYTES[profile] : 32'd2048;
            16'h0100:return TOTAL[profile];
            16'h0104:return BANK_BYTES[profile];
            16'h00f4:return (profile%2)!=0 ? 32'd64 : 32'd32;
            16'h00f0:return (profile%2)!=0 ? 32'd2048 : 32'd1024;
            16'h0108:return expected_allocation[profile];
            16'h010c:return MASK[profile];
            16'h0110:return TOTAL[profile]!=0 ? 32'd1024 : 32'd0;
            default:return 32'd0;
        endcase
    endfunction

    task automatic read_register(input logic[15:0] address);
        @(negedge clk);araddr=address;arvalid=1;
        do @(posedge clk);while(32'(arready)!=ALL);
        @(negedge clk);arvalid=0;
        wait(32'(rvalid)==ALL);
        repeat(4) begin
            @(negedge clk);
            for(int i=0;i<PROFILES;i++)
                check(rvalid[i] && rresp[i]==0 && rdata[i]==expected_read(i,address),
                      $sformatf("read profile=%0d addr=%h value=%h expected=%h",i,address,rdata[i],expected_read(i,address)));
        end
        rready=1;@(posedge clk);@(negedge clk);rready=0;
        reads+=PROFILES;
    endtask

    task automatic check_capacities;
        read_register(16'h0134);read_register(16'h0138);read_register(16'h0108);
        for(int i=0;i<PROFILES;i++) begin
            check(allocation[i]==expected_allocation[i],"allocation output");
            if(TOTAL[i]!=0)
                check(expected_read(i,16'h0134)+expected_read(i,16'h0138)==TOTAL[i],"shared byte conservation");
        end
    endtask

    task automatic write_register(input logic[15:0] address,input logic[31:0] value,
                                  input logic[3:0] strobes,input bit data_first=0);
        logic[1:0] responses[PROFILES];
        logic[31:0] candidate;
        for(int i=0;i<PROFILES;i++) begin
            responses[i]=0;
            if(expected_busy && address!=16'h0004) responses[i]=2;
            else if(address==16'h0108) begin
                candidate=expected_allocation[i];
                for(int b=0;b<4;b++)if(strobes[b])candidate[b*8+:8]=value[b*8+:8];
                if(TOTAL[i]==0 || candidate>=32 || !MASK[i][candidate[4:0]]) responses[i]=2;
                else expected_allocation[i]=candidate;
            end
        end
        if(data_first)begin
            @(negedge clk);wdata=value;wstrb=strobes;wvalid=1;
            do @(posedge clk);while(32'(wready)!=ALL);
            @(negedge clk);wvalid=0;
            repeat(2)@(negedge clk);
            awaddr=address;awvalid=1;
            do @(posedge clk);while(32'(awready)!=ALL);
            @(negedge clk);awvalid=0;
        end else begin
            @(negedge clk);awaddr=address;awvalid=1;
            do @(posedge clk);while(32'(awready)!=ALL);
            @(negedge clk);awvalid=0;
            repeat(2)@(negedge clk);
            wdata=value;wstrb=strobes;wvalid=1;
            do @(posedge clk);while(32'(wready)!=ALL);
            @(negedge clk);wvalid=0;
        end
        wait(32'(bvalid)==ALL);
        repeat(5)begin
            @(negedge clk);
            for(int i=0;i<PROFILES;i++)begin
                check(bvalid[i] && bresp[i]==responses[i],$sformatf("write profile=%0d addr=%h data=%h strb=%h response=%0d expected=%0d",i,address,value,strobes,bresp[i],responses[i]));
                check(allocation[i]==expected_allocation[i],"allocation remains stable during response backpressure");
            end
        end
        bready=1;@(posedge clk);@(negedge clk);bready=0;
        writes+=PROFILES;
        for(int i=0;i<PROFILES;i++)if(responses[i]!=0)rejected++;
    endtask

    initial begin
        for(int i=0;i<PROFILES;i++)expected_allocation[i]=TOTAL[i]!=0 ? 1 : 0;
        repeat(5)@(negedge clk);rst_n=1;
        read_register(16'h0124);read_register(16'h0100);read_register(16'h0104);
        read_register(16'h010c);read_register(16'h0110);
        read_register(16'h00f4);read_register(16'h00f0);check_capacities();
        for(int n=0;n<=8;n++)begin
            write_register(16'h0108,32'(n),4'hf,1'(n));check_capacities();
        end
        write_register(16'h0108,32'd1,4'hf);check_capacities();
        write_register(16'h0108,32'hffffaa02,4'h1,1);check_capacities();
        write_register(16'h0108,32'h00000100,4'h2);check_capacities();
        write_register(16'h0108,32'hffff0000,4'h2,1);check_capacities();
        write_register(16'h0108,32'hffff0004,4'h3);check_capacities();
        write_register(16'h0108,32'hffffffff,4'h0,1);check_capacities();
        write_register(16'h0108,32'h01000001,4'hf);check_capacities();
        write_register(16'h0108,32'd32,4'hf,1);check_capacities();
        for(int b=0;b<4;b++)begin
            write_register(16'h0108,32'hffffffff,4'(1<<b),1'(b));check_capacities();
        end
        write_register(16'h0100,32'hffffffff,4'hf);
        write_register(16'h0104,32'hffffffff,4'hf,1);
        write_register(16'h010c,32'hffffffff,4'hf);
        write_register(16'h0110,32'hffffffff,4'hf,1);
        read_register(16'h0100);read_register(16'h0104);read_register(16'h010c);read_register(16'h0110);
        write_register(16'h0108,32'd1,4'hf);check_capacities();
        write_register(16'h0000,32'd1,4'h1);expected_busy=1;
        check(32'(busy)==ALL,"START establishes busy for every profile");
        write_register(16'h0108,32'd2,4'hf);check_capacities();
        write_register(16'h0108,32'd4,4'h1,1);check_capacities();
        write_register(16'h0108,32'd1,4'h0);check_capacities();
        write_register(16'h0004,32'd4,4'h1,1);
        check(32'(busy)==ALL,"STATUS write preserves active task");
        @(negedge clk);done_valid=1;@(posedge clk);@(negedge clk);done_valid=0;expected_busy=0;
        check(busy=='0,"completion releases configuration");
        write_register(16'h0108,32'd2,4'hf);check_capacities();
        @(negedge clk);rst_n=0;repeat(3)@(negedge clk);rst_n=1;
        for(int i=0;i<PROFILES;i++)expected_allocation[i]=TOTAL[i]!=0 ? 1 : 0;
        check_capacities();read_register(16'h010c);read_register(16'h0110);
        $display("{\"passed\":true,\"profiles\":%0d,\"register_reads\":%0d,\"register_writes\":%0d,\"rejected_writes\":%0d,\"checks\":%0d}",PROFILES,reads,writes,rejected,checks);
        $finish;
    end
    initial begin #1000000;$fatal(1,"shared allocation register test timeout");end
endmodule
