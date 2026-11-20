`timescale 1ns/1ps
module frame_address_tb #(
    parameter bit p_ready_mask_abort = 1'b1
);
    logic clk = 0;
    logic rst_n = 0;
    logic start = 0, abort_job = 0, result_rdy = 0;
    logic [31:0] p0, q0, column, total_depth;
    logic [31:0] ia_base, ia_stride, weight_base, weight_stride, dst_base, dst_stride;
    logic ia_packed, ia_s16, weight_packed, weight_s16, is_mode, output_s16;
    logic [1:0] start_rdy, result_vld;
    logic [31:0] ia_result [0:1], weight_result [0:1], dst_result [0:1];
    integer cycles = 0, completed = 0, cancelled = 0, reset_cases = 0, wait_checks = 0;
    integer abort_ready_checks = 0, idle_abort_checks = 0;
    integer abort_phase_checks [1:11] = '{default:0};
    integer reset_phase_checks [1:11] = '{default:0};
    logic [31:0] corners [0:13];

    for (genvar impl = 0; impl < 2; impl++) begin : g_impl
        frame_address_prepare #(.p_size(16),.p_use_dsp(impl != 0),
            .p_ready_mask_abort(p_ready_mask_abort)) u_prepare (
            .clk(clk),.rst_n(rst_n),.i_start(start),.i_abort(abort_job),
            .o_start_rdy(start_rdy[impl]),.i_result_rdy(result_rdy),.o_result_vld(result_vld[impl]),
            .i_p0(p0),.i_q0(q0),.i_column(column),.i_total_depth(total_depth),
            .i_ia_base(ia_base),.i_ia_stride(ia_stride),.i_ia_packed(ia_packed),.i_ia_s16(ia_s16),
            .i_weight_base(weight_base),.i_weight_stride(weight_stride),
            .i_weight_packed(weight_packed),.i_weight_s16(weight_s16),
            .i_dst_base(dst_base),.i_dst_stride(dst_stride),.i_is_mode(is_mode),.i_output_s16(output_s16),
            .o_ia_base(ia_result[impl]),.o_weight_base(weight_result[impl]),.o_dst_base(dst_result[impl])
        );
    end

    function automatic logic [31:0] operand_reference(
        input logic [31:0] base, row0, depth0, stride, total,
        input bit packed_layout, wide
    );
        logic [31:0] tiles, elements, relative_address;
        tiles = (total + 32'd15) >> 4;
        elements = (((row0 >> 4)*tiles + (depth0 >> 4)) << 8) + ((row0 & 32'd15) << 4);
        relative_address = packed_layout ? (elements << wide) : row0*stride + (depth0 << wide);
        return base + relative_address;
    endfunction

    task automatic random_context;
        p0 = $urandom; q0 = $urandom; column = $urandom; total_depth = $urandom;
        ia_base = $urandom; ia_stride = $urandom; weight_base = $urandom; weight_stride = $urandom;
        dst_base = $urandom; dst_stride = $urandom;
        {ia_packed,ia_s16,weight_packed,weight_s16,is_mode,output_s16} = 6'($urandom);
    endtask

    task automatic cycle;
        clk = 0; #1;
        clk = 1; #1;
        cycles++;
        if (start_rdy[0] !== start_rdy[1] || result_vld[0] !== result_vld[1])
            $fatal(1,"Control differs cycle=%0d",cycles);
        if (result_vld[0] && (ia_result[0] !== ia_result[1] || weight_result[0] !== weight_result[1] || dst_result[0] !== dst_result[1]))
            $fatal(1,"Primitive result differs cycle=%0d",cycles);
        // 中止后的控制状态为空闲，两种参数分别检查内部空闲与外部接受许可。
        if (abort_job) begin
            if (start_rdy !== (p_ready_mask_abort ? 2'b00 : 2'b11) || result_vld !== 2'b00)
                $fatal(1,"Abort readiness differs mask=%0d cycle=%0d",p_ready_mask_abort,cycles);
            abort_ready_checks++;
        end
    endtask

    task automatic run_case(input integer abort_at, reset_at, hold_cycles);
        logic [31:0] expected_ia, expected_weight, expected_dst;
        expected_ia = operand_reference(ia_base,p0,q0,ia_stride,total_depth,ia_packed,ia_s16);
        expected_weight = operand_reference(weight_base,column,q0,weight_stride,total_depth,weight_packed,weight_s16);
        expected_dst = dst_base + (is_mode ? column : p0)*dst_stride + ((is_mode ? p0 : column) << output_s16);
        start = 1; abort_job = 0; result_rdy = 0;
        cycle();
        if (start_rdy != 0 || result_vld != 0) $fatal(1,"Acceptance state differs");
        for (int age = 1; age <= 10; age++) begin
            random_context();
            start = 1'($urandom);
            if (age == abort_at || age == reset_at) begin
                abort_job = age == abort_at;
                rst_n = age != reset_at;
                start = 1'b1;
                cycle();
                if (result_vld != 0) $fatal(1,"Cancellation produced a result");
                abort_job = 0; rst_n = 1; start = 0;
                cycle();
                if (start_rdy != 3 || result_vld != 0) $fatal(1,"Cancellation recovery differs");
                if (age == abort_at) begin
                    cancelled++;
                    abort_phase_checks[age]++;
                end else begin
                    reset_cases++;
                    reset_phase_checks[age]++;
                end
                return;
            end
            cycle();
            if (age < 10 && result_vld != 0) $fatal(1,"Early result age=%0d",age);
            if (age == 10 && result_vld != 3) $fatal(1,"Result latency differs");
            if (start_rdy != 0) $fatal(1,"Preparation accepted a second context");
        end
        if (ia_result[0] !== expected_ia || weight_result[0] !== expected_weight || dst_result[0] !== expected_dst)
            $fatal(1,"Address differs ia=%08x/%08x weight=%08x/%08x dst=%08x/%08x",
                ia_result[0],expected_ia,weight_result[0],expected_weight,dst_result[0],expected_dst);
        for (int wait_cycle = 0; wait_cycle < hold_cycles; wait_cycle++) begin
            random_context(); start = 1'($urandom);
            cycle();
            if (result_vld != 3 || start_rdy != 0 || ia_result[0] !== expected_ia ||
                weight_result[0] !== expected_weight || dst_result[0] !== expected_dst)
                $fatal(1,"Waiting result changed");
            wait_checks++;
        end
        start = 0;
        if (abort_at == 11 || reset_at == 11) begin
            abort_job = abort_at == 11; rst_n = reset_at != 11;
            start = 1'b1;
            cycle();
            if (result_vld != 0) $fatal(1,"Waiting cancellation produced a result");
            abort_job = 0; rst_n = 1; start = 0;
            cycle();
            if (start_rdy != 3 || result_vld != 0) $fatal(1,"Waiting cancellation recovery differs");
            if (abort_at == 11) begin
                cancelled++;
                abort_phase_checks[11]++;
            end else begin
                reset_cases++;
                reset_phase_checks[11]++;
            end
        end else begin
            result_rdy = 1;
            cycle();
            if (start_rdy != 3 || result_vld != 0) $fatal(1,"Result acceptance differs");
            completed++;
        end
        result_rdy = 0;
    endtask

    initial begin
        corners = '{32'h00000000,32'h00000001,32'h0000000f,32'h00000010,
            32'h00000011,32'h0000ffff,32'h00010000,32'h0001ffff,
            32'h00020000,32'h7fffffff,32'h80000000,32'hfffffff0,
            32'hfffffffe,32'hffffffff};
        random_context(); cycle(); cycle(); rst_n = 1; cycle();
        for (int a = 0; a < 14; a++) begin
            for (int b = 0; b < 14; b++) begin
                for (int flags = 0; flags < 64; flags++) begin
                    random_context();
                    p0 = corners[a]; column = corners[b]; q0 = corners[(a+b)%14]; total_depth = corners[(3*a+b)%14];
                    ia_stride = corners[b]; weight_stride = corners[a]; dst_stride = corners[(a+3*b)%14];
                    ia_base = corners[(a+b+2)%14]; weight_base = corners[(a+b+7)%14]; dst_base = corners[(a+2*b)%14];
                    {ia_packed,ia_s16,weight_packed,weight_s16,is_mode,output_s16} = 6'(flags);
                    run_case(0,0,0);
                end
            end
        end
        for (int sample = 0; sample < 30000; sample++) begin
            random_context();
            if (sample % 7 == 0) run_case(1+(sample%11),0,int'($urandom_range(0,15)));
            else if (sample % 17 == 0) run_case(0,1+(sample%11),int'($urandom_range(0,15)));
            else run_case(0,0,int'($urandom_range(0,15)));
        end
        abort_job = 1; start = 1; cycle();
        if (start_rdy !== (p_ready_mask_abort ? 2'b00 : 2'b11) || result_vld != 0)
            $fatal(1,"Abort priority differs");
        idle_abort_checks++;
        abort_job = 0; start = 0; cycle();
        if (start_rdy != 3 || result_vld != 0) $fatal(1,"Idle abort recovery differs");
        for (int age = 1; age <= 11; age++) begin
            if (abort_phase_checks[age] == 0 || reset_phase_checks[age] == 0)
                $fatal(1,"Cancellation phase was not exercised age=%0d",age);
            $display("FRAME_ADDRESS_PHASE age=%0d abort=%0d reset=%0d",
                     age,abort_phase_checks[age],reset_phase_checks[age]);
        end
        $display("FRAME_ADDRESS_PASS completed=%0d cancelled=%0d reset_cases=%0d wait_checks=%0d cycles=%0d abort_ready_checks=%0d idle_abort_checks=%0d",
                 completed,cancelled,reset_cases,wait_checks,cycles,abort_ready_checks,idle_abort_checks);
        $finish;
    end
endmodule
