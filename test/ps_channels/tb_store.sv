`timescale 1ns/1ps
module tb_ps_channel_store #(
    parameter int p_bank_bytes = 2048,
    parameter int p_banks = 7
);
    localparam int p_rows=p_bank_bytes/16;
    localparam int p_max_ia_banks=p_banks>=8 ? 4 : 2;
    localparam int p_max_frame_rows=p_rows*p_max_ia_banks/2;
    localparam int p_addr_width=$clog2(p_banks*p_rows);
    localparam int p_count_width=$clog2(p_banks+1);
    logic clk=0,rst_n=0,cfg_valid=0;
    logic [p_count_width-1:0] cfg_ia_banks=1;
    logic [31:0] cfg_pool_bank_count=p_banks-1,cfg_directory_stride=1;
    logic frame_request=0,frame_accept=0,frame_init=0,frame_final=0;
    logic [3:0] frame_id=0;
    logic [31:0] frame_rows=1,frame_reserve_rows=1;
    logic write_valid=0,write_frame_end=0,replay_trigger=0;
    logic [511:0] write_data=0;
    wire [1:0] frame_ready,frame_pressure,capacity_fault,frame_complete,replay_valid,memory_fault;
    wire [511:0] replay_data[2];
    logic [511:0] expected_rows[16][p_max_frame_rows];
    logic [511:0] next_rows[p_max_frame_rows];
    longint cycles=0,commands=0,checked_int32=0,pressure_checks=0,overlap_cycles=0,configurations=0;

    for(genvar variant=0;variant<2;variant++) begin:g_variant
        wire [3:0] ram_read_en,ram_write_en;
        wire [p_addr_width-1:0] ram_read_addr[4],ram_write_addr[4];
        wire [127:0] ram_read_data[4],ram_write_data[4];
        wire [127:0] ia_read_data[2];
        ps_frame_store #(.MAX_FRAME_ROWS(p_max_frame_rows),.FRAME_COUNT(16),
            .POOL_BYTES((p_banks-1)*p_bank_bytes),.BANK_BYTES(p_bank_bytes),
            .EXTERNAL_RAM(1),.p_fixed_ps_channels(variant==1),.RAM_ADDR_BITS(p_addr_width)) u_store (
            .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_pool_bank_words(32'(p_rows)),
            .cfg_pool_bank_count(cfg_pool_bank_count),.cfg_directory_stride(cfg_directory_stride),
            .ram_read_en(ram_read_en),.ram_read_addr(ram_read_addr),.ram_read_data(ram_read_data),
            .ram_write_en(ram_write_en),.ram_write_addr(ram_write_addr),.ram_write_data(ram_write_data),
            .frame_request(frame_request),.frame_accept(frame_accept),.frame_id(frame_id),
            .frame_rows(frame_rows),.frame_reserve_rows(frame_reserve_rows),.frame_word_cap(3'd4),
            .frame_init(frame_init),.frame_final(frame_final),.force_raw_i(1'b1),
            .frame_ready(frame_ready[variant]),.frame_pressure(frame_pressure[variant]),
            .capacity_fault(capacity_fault[variant]),.frame_complete(frame_complete[variant]),
            .write_valid(write_valid),.write_data(write_data),.write_frame_end(write_frame_end),
            .replay_trigger(replay_trigger),.replay_data(replay_data[variant]),.replay_valid(replay_valid[variant])
        );
        if(variant==1) begin:g_channels
            ia_ps_channel_ram #(.p_bank_bytes(p_bank_bytes),.p_total_bytes(p_banks*p_bank_bytes)) u_ram (
                .clk(clk),.rst_n(rst_n),.i_cfg_valid(cfg_valid),.i_cfg_ia_banks(cfg_ia_banks),
                .o_capacity_fault(memory_fault[variant]),.i_ia_read_en(2'b0),.i_ia_write_en(2'b0),
                .i_ia_read_addr('{default:'0}),.i_ia_write_addr('{default:'0}),.o_ia_read_data(ia_read_data),
                .i_ia_write_data('{default:'0}),.i_ia_write_mask('{default:'0}),
                .i_ia_shared_write_data(128'd0),
                .i_ps_read_en(ram_read_en),.i_ps_write_en(ram_write_en),
                .i_ps_read_addr(ram_read_addr),.i_ps_write_addr(ram_write_addr),
                .o_ps_read_data(ram_read_data),.i_ps_write_data(ram_write_data)
            );
        end else begin:g_rotating
            ia_ps_shared_ram #(.BANK_BYTES(p_bank_bytes),.TOTAL_BYTES(p_banks*p_bank_bytes)) u_ram (
                .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_ia_banks(cfg_ia_banks),
                .capacity_fault(memory_fault[variant]),.ia_read_en(2'b0),.ia_write_en(2'b0),
                .ia_read_addr('{default:'0}),.ia_write_addr('{default:'0}),.ia_read_data(ia_read_data),
                .ia_write_data('{default:'0}),.ia_write_mask('{default:'0}),
                .ps_read_en(ram_read_en),.ps_write_en(ram_write_en),
                .ps_read_addr(ram_read_addr),.ps_write_addr(ram_write_addr),
                .ps_read_data(ram_read_data),.ps_write_data(ram_write_data)
            );
        end
    end

    task automatic compare_outputs;
        if(frame_ready[0]!==frame_ready[1] || frame_pressure[0]!==frame_pressure[1] ||
           capacity_fault[0]!==capacity_fault[1] || frame_complete[0]!==frame_complete[1] ||
           replay_valid[0]!==replay_valid[1] || replay_data[0]!==replay_data[1])
            $fatal(1,"Store output differs at cycle %0d",cycles);
        if((|capacity_fault) || (|memory_fault)) $fatal(1,"Storage fault at cycle %0d",cycles);
    endtask
    task automatic step;
        clk=0;#2;compare_outputs();clk=1;#2;compare_outputs();clk=0;#1;cycles++;
    endtask
    task automatic idle;
        cfg_valid=0;frame_request=0;frame_accept=0;write_valid=0;write_frame_end=0;replay_trigger=0;
    endtask
    task automatic configure(input int allocation,input int stride);
        idle();cfg_valid=1;cfg_ia_banks=p_count_width'(allocation);
        cfg_pool_bank_count=32'(p_banks-allocation);cfg_directory_stride=32'(stride);
        step();cfg_valid=0;step();step();configurations++;
    endtask
    task automatic command(input int id,input bit initial_frame,input bit final_frame,input int count,input int stride);
        int wait_cycles,read_count,write_count;
        bit expected_stream;
        for(int row=0;row<count;row++)begin
            for(int lane=0;lane<16;lane++)next_rows[row][lane*32+:32]=$urandom;
        end
        frame_id=4'(id);frame_rows=32'(count);frame_reserve_rows=32'(stride);
        frame_init=initial_frame;frame_final=final_frame;frame_request=1;wait_cycles=0;
        #2;
        while(!frame_ready[0])begin step();wait_cycles++;if(wait_cycles>1000)$fatal(1,"Frame admission timeout");end
        frame_accept=1;step();frame_accept=0;frame_request=0;
        read_count=initial_frame ? count : 0;write_count=final_frame ? count : 0;expected_stream=0;
        if(!initial_frame)begin repeat(2)step();replay_trigger=1;step();replay_trigger=0;end
        wait_cycles=0;
        while(read_count<count || write_count<count)begin
            write_valid=write_count<count && (initial_frame || read_count>=4 || read_count==count) && $urandom_range(0,3)!=0;
            if(write_valid)write_data=next_rows[write_count];
            step();wait_cycles++;
            if(write_valid)write_count++;
            if(replay_valid[0])begin
                if(initial_frame || read_count>=count)$fatal(1,"Unexpected replay data");
                if(replay_data[0]!==expected_rows[id][read_count])$fatal(1,"INT32 replay mismatch id %0d row %0d",id,read_count);
                checked_int32+=16;read_count++;expected_stream=read_count<count;
                if(write_valid)overlap_cycles++;
            end else if(expected_stream)$fatal(1,"Replay stream stalled");
            if(wait_cycles>count*8+100)$fatal(1,"Frame data timeout");
        end
        write_valid=0;write_frame_end=1;step();write_frame_end=0;wait_cycles=0;
        while(!frame_complete[0])begin step();wait_cycles++;if(wait_cycles>100)$fatal(1,"Frame completion timeout");end
        if(!final_frame)for(int row=0;row<count;row++)expected_rows[id][row]=next_rows[row];
        commands++;step();
    endtask
    task automatic pressure(input int id,input int stride);
        int wait_cycles;
        frame_request=1;frame_id=4'(id);frame_rows=1;frame_reserve_rows=32'(stride);frame_init=1;frame_final=0;
        #2;wait_cycles=0;
        while(!frame_pressure[0])begin
            if(frame_ready[0])$fatal(1,"Out-of-capacity frame was admitted");
            step();wait_cycles++;if(wait_cycles>10)$fatal(1,"Capacity pressure timeout");
        end
        repeat(3)begin
            if(frame_ready[0] || !frame_pressure[0])$fatal(1,"Capacity pressure mismatch");
            step();pressure_checks++;
        end
        frame_request=0;step();
    endtask
    initial begin
        int stride,admitted,count;
        step();step();rst_n=1;
        for(int allocation=1;allocation<=p_max_ia_banks;allocation*=2)begin
            for(int epoch=0;epoch<6;epoch++)begin
                case(epoch)
                    0:stride=1;
                    1:stride=7;
                    2:stride=16;
                    3:stride=47;
                    4:stride=p_rows/2;
                    default:stride=p_max_frame_rows;
                endcase
                configure(allocation,stride);
                admitted=((p_banks-allocation)*p_rows/4)/stride;
                if(admitted>16)admitted=16;
                for(int id=0;id<admitted;id++)begin
                    count=(id&1)==0 ? stride : (stride+1)/2;
                    command(id,1,0,count,stride);
                end
                if(admitted<16)pressure(admitted,stride);
                for(int iteration=0;iteration<3;iteration++)begin
                    for(int id=admitted-1;id>=0;id--)begin
                        count=(id&1)==0 ? stride : (stride+1)/2;
                        command(id,0,0,count,stride);
                    end
                end
                for(int id=0;id<admitted;id++)begin
                    count=(id&1)==0 ? stride : (stride+1)/2;
                    command(id,0,1,count,stride);
                end
            end
        end
        idle();rst_n=0;step();rst_n=1;configure(1,16);command(0,1,0,16,16);
        idle();rst_n=0;step();rst_n=1;configure(1,7);command(0,1,0,7,7);command(0,0,1,7,7);
        $display("PS_CHANNEL_STORE_PASS banks=%0d bank_bytes=%0d cycles=%0d commands=%0d checked_int32=%0d pressure_checks=%0d overlap_cycles=%0d configurations=%0d",p_banks,p_bank_bytes,cycles,commands,checked_int32,pressure_checks,overlap_cycles,configurations);
        $finish;
    end
endmodule
