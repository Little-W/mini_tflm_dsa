`timescale 1ns/1ps
module tb_four_state;
    logic [31:0] lhs, rhs0, rhs1;
    logic rhs_select, add_enable;
    wire generic_equal, generic_padding;
    wire restore_generic_equal;
    integer cases_checked = 0;
    integer selected_lane;

    packed_add_formal #(.p_lane_width(8)) u_packed (
        .i_lhs(lhs), .i_rhs0(rhs0), .i_rhs1(rhs1),
        .i_rhs_select(rhs_select), .i_add_enable(add_enable),
        .o_equivalent(generic_equal), .o_padding_zero(generic_padding)
    );
    restore_add_formal #(.p_offset_width(9)) u_restore (
        .i_bytes(lhs), .i_offset(rhs0[8:0]), .o_equivalent(restore_generic_equal)
    );

    task check_outputs;
        if (u_packed.actual !== u_packed.expected)
            $fatal(1, "Generic packed byte outputs differ");
        if (u_restore.actual !== u_restore.expected)
            $fatal(1, "Generic restored outputs differ");
        cases_checked = cases_checked + 1;
    endtask

    initial begin
        // 四组同时产生低八位溢出，随后检查负数对应的八位模式。
        lhs = '1; rhs0 = '1; rhs1 = '1;
        rhs_select = 1'b0; add_enable = 1'b1;
        #1; check_outputs();
        lhs = 32'h80808080; rhs0 = 32'h80808080;
        #1; check_outputs();
        for (integer cycle = 0; cycle < 100000; cycle++) begin
            lhs = $urandom; rhs0 = $urandom; rhs1 = $urandom;
            rhs_select = $urandom_range(0, 1);
            add_enable = $urandom_range(0, 1);
            selected_lane = cycle % 4;
            // 独立注入未知位和高阻位，检查相邻通道仍保留各自结果。
            if (cycle % 7 == 0) lhs[selected_lane*8 +: 4] = 'x;
            if (cycle % 11 == 0) rhs0[selected_lane*8 +: 8] = 'x;
            if (cycle % 13 == 0) rhs1[selected_lane*8 +: 4] = 'z;
            #1; check_outputs();
        end
        $display("PACKED_ADD_FOUR_STATE_PASS cases=%0d comparisons=%0d", cases_checked, 2*cases_checked);
        $finish;
    end
endmodule
