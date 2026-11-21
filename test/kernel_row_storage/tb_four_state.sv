`timescale 1ns/1ps
module tb_kernel_buffer_four_state #(
    parameter integer SIZE=16,
    parameter integer DATA_WIDTH=16
);
    localparam integer IW=$clog2(SIZE);
    localparam integer CW=9+IW;
    localparam integer PW=SIZE*DATA_WIDTH;
    logic clk=0;
    logic rst_n,cache_flush,discard_head,load_start,row_valid,row_slot,load_done,done_slot,send_start;
    logic [IW-1:0] row_idx;
    logic [PW-1:0] row_payload,collision_payload;
    wire signed [DATA_WIDTH-1:0] row_data[SIZE];
    wire load_slot_id,load_ready,load_commit,load_commit_slot,discard_ready;
    wire weight_data_valid,weight_sending_done,store_weight_req;
    wire ref_load_slot_id,ref_load_ready,ref_load_commit,ref_load_commit_slot,ref_discard_ready;
    wire ref_weight_data_valid,ref_weight_sending_done,ref_store_weight_req;
    wire signed [DATA_WIDTH-1:0] weight_out[SIZE],ref_weight_out[SIZE];
    logic [31:0] rng=32'h8952a619;
    logic [CW-1:0] controls,saved_controls;
    integer cycles=0,checks=0,known_words=0,unknown_words=0,unknown_control_cycles=0,collision_checks=0;
    for(genvar i=0;i<SIZE;i++) assign row_data[i]=row_payload[i*DATA_WIDTH+:DATA_WIDTH];
    kernel_loader_buffer #(.SIZE(SIZE),.DATA_WIDTH(DATA_WIDTH)) dut(
        .clk,.rst_n,.cache_flush,.discard_head,.load_start,.load_slot_id,.row_valid,.row_slot,.row_idx,.row_data,
        .load_done,.done_slot,.send_start,.load_ready,.load_commit,.load_commit_slot,.discard_ready,
        .weight_data_valid,.weight_sending_done,.store_weight_req,.weight_out);
    kernel_loader_buffer_ref #(.SIZE(SIZE),.DATA_WIDTH(DATA_WIDTH)) reference(
        .clk,.rst_n,.cache_flush,.discard_head,.load_start,.load_slot_id(ref_load_slot_id),.row_valid,.row_slot,.row_idx,.row_data,
        .load_done,.done_slot,.send_start,.load_ready(ref_load_ready),.load_commit(ref_load_commit),
        .load_commit_slot(ref_load_commit_slot),.discard_ready(ref_discard_ready),.weight_data_valid(ref_weight_data_valid),
        .weight_sending_done(ref_weight_sending_done),.store_weight_req(ref_store_weight_req),.weight_out(ref_weight_out));
    task randomize_word;
        rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
    endtask
    task clear_inputs;
        cache_flush=0;discard_head=0;load_start=0;row_valid=0;row_slot=0;row_idx=0;
        load_done=0;done_slot=0;send_start=0;row_payload=0;
    endtask
    task compare_outputs;
        if({load_slot_id,load_ready,load_commit,load_commit_slot,discard_ready,weight_data_valid,weight_sending_done,store_weight_req} !==
           {ref_load_slot_id,ref_load_ready,ref_load_commit,ref_load_commit_slot,ref_discard_ready,ref_weight_data_valid,ref_weight_sending_done,ref_store_weight_req})
            $fatal(1,"控制结果不同 cycle=%0d",cycles);
        checks=checks+8;
        for(integer i=0;i<SIZE;i=i+1)begin
            if(weight_out[i]!==ref_weight_out[i])$fatal(1,"权重结果不同 cycle=%0d lane=%0d current=%h reference=%h",cycles,i,weight_out[i],ref_weight_out[i]);
            checks=checks+1;
            if((^weight_out[i])===1'bx)unknown_words=unknown_words+1;else known_words=known_words+1;
        end
    endtask
    task tick;
        #2;clk=1;#2;cycles=cycles+1;compare_outputs();clk=0;#1;
    endtask
    task reset_inputs;
        clear_inputs();rst_n=0;repeat(3)tick();rst_n=1;tick();
    endtask
    task load_frame(input integer first_row,input integer with_unknown);
        integer slot;
        slot=load_slot_id;load_start=1;tick();load_start=0;
        for(integer r=first_row;r<SIZE;r=r+1)begin
            row_valid=1;row_slot=1'(slot);row_idx=IW'(r);
            for(integer bit_index=0;bit_index<PW;bit_index=bit_index+1)begin
                randomize_word();row_payload[bit_index]=rng[0];
            end
            if(with_unknown!=0)begin
                row_payload[(r*7)%PW]=1'bx;
                row_payload[(r*11+1)%PW]=1'bz;
            end
            load_done=(r==SIZE-1);done_slot=1'(slot);tick();
        end
        clear_inputs();repeat(2)tick();
        if(weight_data_valid!==1'b1)$fatal(1,"已完成的权重帧不可发送");
        send_start=1;tick();send_start=0;repeat(SIZE+4)tick();
    endtask
    task collision_case;
        reset_inputs();
        force dut.row_slot_q=1'b0;force reference.row_slot_q=1'b0;
        force dut.row_idx_q=0;force reference.row_idx_q=0;
        force dut.active_storage=0;force reference.active_storage=0;
        force dut.slot_reserved=2'b11;force reference.slot_reserved=2'b11;
        force dut.row_data_vec_q=collision_payload;force reference.row_data_vec_q=collision_payload;
        force dut.row_valid_q=1'b1;force reference.row_valid_q=1'b1;
        force dut.send_pending=1'b0;force reference.send_pending=1'b0;
        force dut.send_prefetch=1'b0;force reference.send_prefetch=1'b0;
        force dut.send_active=1'b0;force reference.send_active=1'b0;
        force dut.emit_col_idx=0;force reference.emit_col_idx=0;
        force dut.send_valid_cols=SIZE;force reference.send_valid_cols=SIZE;
        collision_payload={PW{1'b0}};collision_payload[DATA_WIDTH-1:0]=DATA_WIDTH'(53);tick();
        force dut.send_active=1'b1;force reference.send_active=1'b1;
        collision_payload[DATA_WIDTH-1:0]=DATA_WIDTH'(101);tick();
        if(weight_out[0]!==DATA_WIDTH'(53))$fatal(1,"同地址读写未返回原有数据");
        collision_checks=collision_checks+1;
        force dut.row_valid_q=1'b0;force reference.row_valid_q=1'b0;tick();
        if(weight_out[0]!==DATA_WIDTH'(101))$fatal(1,"写入数据未在后续读取返回");
        collision_checks=collision_checks+1;
        release dut.row_slot_q;release reference.row_slot_q;release dut.row_idx_q;release reference.row_idx_q;
        release dut.active_storage;release reference.active_storage;release dut.slot_reserved;release reference.slot_reserved;
        release dut.row_data_vec_q;release reference.row_data_vec_q;release dut.row_valid_q;release reference.row_valid_q;
        release dut.send_pending;release reference.send_pending;release dut.send_prefetch;release reference.send_prefetch;
        release dut.send_active;release reference.send_active;release dut.emit_col_idx;release reference.emit_col_idx;
        release dut.send_valid_cols;release reference.send_valid_cols;
        reset_inputs();
    endtask
    initial begin
        reset_inputs();
        // 部分行保持未初始化，所有输出位仍逐周期比较。
        load_frame(SIZE-1,0);
        for(integer frame=0;frame<48;frame=frame+1)begin
            if(frame%7==0)reset_inputs();
            load_frame(0,frame%3!=0);
        end
        collision_case();
        for(integer trial=0;trial<256;trial=trial+1)begin
            reset_inputs();
            for(integer step=0;step<12;step=step+1)begin
                randomize_word();controls=CW'(rng);controls[CW-1]=1'b1;saved_controls=controls;
                for(integer bit_index=0;bit_index<PW;bit_index=bit_index+1)begin
                    randomize_word();row_payload[bit_index]=rng[0];
                end
                if(step%3==1)begin controls[(trial+step)%CW]=1'bx;unknown_control_cycles=unknown_control_cycles+1;end
                if(step%3==2)begin controls[(trial+step)%CW]=1'bz;unknown_control_cycles=unknown_control_cycles+1;end
                {rst_n,cache_flush,discard_head,load_start,row_valid,row_slot,load_done,done_slot,send_start,row_idx}=controls;
                tick();
            end
        end
        if(known_words<1000||unknown_words<SIZE-1||collision_checks!=2)$fatal(1,"场景检查数量不足");
        $display("BUFFER_FOUR_STATE_PASS cycles=%0d checks=%0d known_words=%0d unknown_words=%0d unknown_control_cycles=%0d collision_checks=%0d",
                 cycles,checks,known_words,unknown_words,unknown_control_cycles,collision_checks);
        $finish;
    end
endmodule
