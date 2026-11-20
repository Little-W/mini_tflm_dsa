`timescale 1ns/1ps
module tb_ps_channel_memory #(
    parameter int p_bank_bytes = 2048,
    parameter int p_banks = 7,
    parameter int p_cycles = 10000
);
    localparam int p_rows = p_bank_bytes/16;
    localparam int p_chunk_rows = p_rows/4;
    localparam int p_words = p_rows*p_banks;
    localparam int p_addr_width = $clog2(p_words);
    localparam int p_count_width = $clog2(p_banks+1);
    localparam int p_max_ia_banks = p_banks >= 8 ? 4 : 2;
    logic clk=0, rst_n=0, cfg_valid=0, capacity_fault;
    logic [p_count_width-1:0] cfg_ia_banks=1;
    logic [1:0] ia_read_en=0, ia_write_en=0;
    logic [p_addr_width-1:0] ia_read_addr[2], ia_write_addr[2];
    logic [127:0] ia_read_data[2], ia_write_data[2];
    logic [15:0] ia_write_mask[2];
    logic [3:0] ps_read_en=0, ps_write_en=0;
    logic [p_addr_width-1:0] ps_read_addr[4], ps_write_addr[4];
    logic [127:0] ps_read_data[4], ps_write_data[4];
    logic [127:0] memory[p_words];
    bit [15:0] known[p_words];
    bit configured=0, fault=0;
    int ia_banks=1;
    longint cycles=0, checked_bytes=0, read_checks=0, write_checks=0, fault_events=0;
    longint configurations=0, simultaneous_ps=0, mixed_accesses=0;

    ia_ps_channel_ram #(.p_bank_bytes(p_bank_bytes), .p_total_bytes(p_banks*p_bank_bytes)) dut (
        .clk(clk), .rst_n(rst_n), .i_cfg_valid(cfg_valid), .i_cfg_ia_banks(cfg_ia_banks),
        .o_capacity_fault(capacity_fault), .i_ia_read_en(ia_read_en), .i_ia_write_en(ia_write_en),
        .i_ia_read_addr(ia_read_addr), .i_ia_write_addr(ia_write_addr), .o_ia_read_data(ia_read_data),
        .i_ia_write_data(ia_write_data), .i_ia_write_mask(ia_write_mask),
        .i_ps_read_en(ps_read_en), .i_ps_write_en(ps_write_en),
        .i_ps_read_addr(ps_read_addr), .i_ps_write_addr(ps_write_addr),
        .o_ps_read_data(ps_read_data), .i_ps_write_data(ps_write_data)
    );

    task automatic idle;
        cfg_valid=0; ia_read_en=0; ia_write_en=0; ps_read_en=0; ps_write_en=0;
    endtask
    task automatic step;
        bit access, event_fault, valid_cfg;
        bit [1:0] ia_check;
        bit [3:0] ps_check;
        logic [127:0] expected_ia[2], expected_ps[4];
        bit [15:0] expected_ia_known[2], expected_ps_known[4];
        int read_port, write_port, read_location, write_location, ps_limit;
        bit same_location;
        clk=0; #2;
        access=configured && !fault && !cfg_valid;
        event_fault=0; ia_check=0; ps_check=0;
        ps_limit=(p_banks-ia_banks)*p_rows/4;
        if (access) begin
            for (int port_index=0;port_index<2;port_index++) begin
                if (ia_read_en[port_index] && int'(ia_read_addr[port_index])>=ia_banks*p_rows) event_fault=1;
                if (ia_write_en[port_index] && int'(ia_write_addr[port_index])>=ia_banks*p_rows) event_fault=1;
            end
            for (int bank=0;bank<ia_banks;bank++) begin
                read_port=-1; write_port=-1;
                for (int port_index=0;port_index<2;port_index++) begin
                    if (ia_read_en[port_index] && int'(ia_read_addr[port_index])<ia_banks*p_rows &&
                        int'(ia_read_addr[port_index])%ia_banks==bank) begin
                        if (read_port>=0) event_fault=1;
                        else read_port=port_index;
                    end
                    if (ia_write_en[port_index] && int'(ia_write_addr[port_index])<ia_banks*p_rows &&
                        int'(ia_write_addr[port_index])%ia_banks==bank) begin
                        if (write_port>=0) event_fault=1;
                        else write_port=port_index;
                    end
                end
                read_location=read_port<0 ? -1 : bank*p_rows+int'(ia_read_addr[read_port])/ia_banks;
                write_location=write_port<0 ? -1 : bank*p_rows+int'(ia_write_addr[write_port])/ia_banks;
                if (read_port>=0) begin
                    for (int port_index=0;port_index<2;port_index++) begin
                        if (ia_read_en[port_index] && int'(ia_read_addr[port_index])<ia_banks*p_rows &&
                            int'(ia_read_addr[port_index])%ia_banks==bank) begin
                            ia_check[port_index]=1;
                            expected_ia[port_index]=memory[read_location];
                            expected_ia_known[port_index]=known[read_location];
                        end
                    end
                end
                same_location=read_port>=0 && write_port>=0 && read_location==write_location && (|ia_write_mask[write_port]);
                if (same_location) event_fault=1;
                if (write_port>=0 && !same_location) begin
                    for (int byte_index=0;byte_index<16;byte_index++) begin
                        if (ia_write_mask[write_port][byte_index]) begin
                            memory[write_location][8*byte_index+:8]=ia_write_data[write_port][8*byte_index+:8];
                            known[write_location][byte_index]=1;
                        end
                    end
                    write_checks++;
                end
            end
            for (int channel=0;channel<4;channel++) begin
                if (ps_read_en[channel] && int'(ps_read_addr[channel])>=ps_limit) event_fault=1;
                if (ps_write_en[channel] && int'(ps_write_addr[channel])>=ps_limit) event_fault=1;
                // 参考模型按原始物理块和块内字号定位，不使用 RTL 的存储分段选择。
                read_location=(ia_banks+int'(ps_read_addr[channel])/p_chunk_rows)*p_rows+
                    channel*p_chunk_rows+int'(ps_read_addr[channel])%p_chunk_rows;
                write_location=(ia_banks+int'(ps_write_addr[channel])/p_chunk_rows)*p_rows+
                    channel*p_chunk_rows+int'(ps_write_addr[channel])%p_chunk_rows;
                if (ps_read_en[channel] && int'(ps_read_addr[channel])<ps_limit) begin
                    ps_check[channel]=1;
                    expected_ps[channel]=memory[read_location];
                    expected_ps_known[channel]=known[read_location];
                end
                same_location=ps_read_en[channel] && ps_write_en[channel] &&
                    int'(ps_read_addr[channel])<ps_limit && int'(ps_write_addr[channel])<ps_limit &&
                    ps_read_addr[channel]==ps_write_addr[channel];
                if (same_location) event_fault=1;
                if (ps_write_en[channel] && int'(ps_write_addr[channel])<ps_limit && !same_location) begin
                    memory[write_location]=ps_write_data[channel]; known[write_location]='1; write_checks++;
                end
            end
            if ((&ps_read_en) || (&ps_write_en)) simultaneous_ps++;
            if (((|ia_read_en) || (|ia_write_en)) && ((|ps_read_en) || (|ps_write_en))) mixed_accesses++;
        end else if ((|ia_read_en) || (|ia_write_en) || (|ps_read_en) || (|ps_write_en)) begin
            event_fault=1;
        end
        if (!rst_n) begin
            configured=0; fault=0; ia_banks=1; ia_check=0; ps_check=0;
        end else if (cfg_valid) begin
            valid_cfg=(cfg_ia_banks==1 || cfg_ia_banks==2 || cfg_ia_banks==4) && int'(cfg_ia_banks)<=p_max_ia_banks;
            configured=valid_cfg; if (valid_cfg) ia_banks=int'(cfg_ia_banks);
            fault=!valid_cfg || event_fault; configurations++;
        end else if (event_fault) begin fault=1; fault_events++; end
        clk=1; #2;
        if (capacity_fault!==fault) $fatal(1,"Fault mismatch at cycle %0d got %0b expected %0b",cycles,capacity_fault,fault);
        for (int port_index=0;port_index<2;port_index++) begin
            if (ia_check[port_index]) begin
                read_checks++;
                for (int byte_index=0;byte_index<16;byte_index++) begin
                    if (expected_ia_known[port_index][byte_index]) begin
                        if (ia_read_data[port_index][8*byte_index+:8]!==expected_ia[port_index][8*byte_index+:8])
                            $fatal(1,"IA read mismatch cycle %0d port %0d byte %0d",cycles,port_index,byte_index);
                        checked_bytes++;
                    end
                end
            end
        end
        for (int channel=0;channel<4;channel++) begin
            if (ps_check[channel]) begin
                read_checks++;
                for (int byte_index=0;byte_index<16;byte_index++) begin
                    if (expected_ps_known[channel][byte_index]) begin
                        if (ps_read_data[channel][8*byte_index+:8]!==expected_ps[channel][8*byte_index+:8])
                            $fatal(1,"PS read mismatch cycle %0d channel %0d byte %0d",cycles,channel,byte_index);
                        checked_bytes++;
                    end
                end
            end
        end
        clk=0; #1; cycles++;
    endtask
    task automatic configure(input int count);
        idle(); cfg_valid=1; cfg_ia_banks=p_count_width'(count); step(); idle();
    endtask
    task automatic random_data;
        for(int port_index=0;port_index<2;port_index++) begin
            for(int word_index=0;word_index<4;word_index++) ia_write_data[port_index][word_index*32+:32]=$urandom;
            ia_write_mask[port_index]=16'($urandom);
        end
        for(int channel=0;channel<4;channel++) begin
            for(int word_index=0;word_index<4;word_index++) ps_write_data[channel][word_index*32+:32]=$urandom;
        end
    endtask
    initial begin
        for(int i=0;i<2;i++) begin ia_read_addr[i]=0; ia_write_addr[i]=0; ia_write_data[i]=0;ia_write_mask[i]=0;end
        for(int i=0;i<4;i++) begin ps_read_addr[i]=0; ps_write_addr[i]=0; ps_write_data[i]=0;end
        step(); rst_n=1; configure(1);
        // 初始化全部物理字，再在不同 IA 分配下检查同一批数据。
        for(int row=0;row<p_rows;row++) begin
            idle(); random_data(); ia_write_en=1;ia_write_addr[0]=p_addr_width'(row);ia_write_mask[0]='1;step();
        end
        for(int row=0;row<(p_banks-1)*p_chunk_rows;row++) begin
            idle();random_data();ps_write_en='1;
            for(int channel=0;channel<4;channel++)ps_write_addr[channel]=p_addr_width'(row);
            step();
        end
        for(int allocation=1;allocation<=p_max_ia_banks;allocation*=2) begin
            configure(allocation);
            for(int address=0;address<allocation*p_rows;address++)begin
                idle();ia_read_en=1;ia_read_addr[0]=p_addr_width'(address);step();
            end
            for(int address=0;address<(p_banks-allocation)*p_chunk_rows;address++)begin
                idle();ps_read_en='1;
                for(int channel=0;channel<4;channel++)ps_read_addr[channel]=p_addr_width'(address);
                step();
            end
        end
        for(int iteration=0;iteration<p_cycles;iteration++) begin
            idle(); random_data();
            if(fault || !configured || iteration%137==0) begin
                configure(1<<$urandom_range(0,p_max_ia_banks==4 ? 2:1));
            end else begin
                ia_read_en=2'($urandom);ia_write_en=2'($urandom);ps_read_en=4'($urandom);ps_write_en=4'($urandom);
                for(int port_index=0;port_index<2;port_index++)begin
                    ia_read_addr[port_index]=p_addr_width'($urandom_range(0,ia_banks*p_rows-1));
                    ia_write_addr[port_index]=p_addr_width'($urandom_range(0,ia_banks*p_rows-1));
                end
                for(int channel=0;channel<4;channel++)begin
                    ps_read_addr[channel]=p_addr_width'($urandom_range(0,(p_banks-ia_banks)*p_chunk_rows-1));
                    ps_write_addr[channel]=p_addr_width'($urandom_range(0,(p_banks-ia_banks)*p_chunk_rows-1));
                end
                if(iteration%31==0) ia_read_addr[0]=p_addr_width'(ia_banks*p_rows);
                if(iteration%37==0) ps_write_addr[2]=p_addr_width'((p_banks-ia_banks)*p_chunk_rows);
                if(iteration%41==0) begin ps_read_en[1]=1;ps_write_en[1]=1;ps_write_addr[1]=ps_read_addr[1];end
                if(iteration%47==0) begin ia_read_en[0]=1;ia_write_en[0]=1;ia_write_addr[0]=ia_read_addr[0];end
                if(iteration%53==0) begin ia_read_en=3;ia_read_addr[1]=ia_read_addr[0];end
                if(iteration%59==0)begin ia_write_en=3;ia_write_addr[1]=ia_write_addr[0];end
                if(iteration%73==0)begin ia_write_mask[0]=0;ia_read_en[0]=1;ia_write_en[0]=1;ia_write_addr[0]=ia_read_addr[0];end
                step();
            end
            if(iteration%251==0) begin idle();rst_n=0;step();rst_n=1;end
            if(iteration%257==0) configure(3);
        end
        // 错误后重新配置并读取全部有效地址，检查写入隔离和配置切换后的保持。
        for(int allocation=1;allocation<=p_max_ia_banks;allocation*=2)begin
            configure(allocation);
            for(int address=0;address<allocation*p_rows;address++)begin
                idle();ia_read_en=1;ia_read_addr[0]=p_addr_width'(address);step();
            end
            for(int address=0;address<(p_banks-allocation)*p_chunk_rows;address++)begin
                idle();ps_read_en='1;
                for(int channel=0;channel<4;channel++)ps_read_addr[channel]=p_addr_width'(address);
                step();
            end
        end
        $display("PS_CHANNEL_MEMORY_PASS banks=%0d bank_bytes=%0d cycles=%0d checked_bytes=%0d read_checks=%0d write_checks=%0d fault_events=%0d configurations=%0d simultaneous_ps=%0d mixed_accesses=%0d",p_banks,p_bank_bytes,cycles,checked_bytes,read_checks,write_checks,fault_events,configurations,simultaneous_ps,mixed_accesses);
        $finish;
    end
endmodule
