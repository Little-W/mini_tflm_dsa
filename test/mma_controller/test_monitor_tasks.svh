`ifndef TEST_MONITOR_TASKS_SVH
`define TEST_MONITOR_TASKS_SVH

// 监控任务：打印等待状态
task automatic monitor_arbitration();
    forever begin
        @(posedge clk);

        // IA Loader 监控
        if (ia_if.load_ia_req) begin
            if (!ia_if.load_ia_granted) begin
                // $display("%s  [%0t] [WAIT] IA Loader requesting, waiting for grant (icb_sel=%0d)%s",
                //          COLOR_GRAY, $time, ctrl_if.icb_sel, COLOR_RESET);
            end else begin
                $display("%s  [%0t] [GRANTED] IA Loader requesting and granted (icb_sel=%0d)%s",
                         COLOR_CYAN, $time, ctrl_if.icb_sel, COLOR_RESET);
            end
        end

        // Weight Loader 监控
        if (weight_if.load_weight_req) begin
            if (!weight_if.load_weight_granted) begin
                // $display(
                //     "%s  [%0t] [WAIT] Weight Loader requesting, waiting for grant (icb_sel=%0d)%s",
                //     COLOR_GRAY, $time, ctrl_if.icb_sel, COLOR_RESET);
            end else begin
                $display("%s  [%0t] [GRANTED] Weight Loader requesting and granted (icb_sel=%0d)%s",
                         COLOR_CYAN, $time, ctrl_if.icb_sel, COLOR_RESET);
            end
        end

        // Bias Loader 监控
        if (bias_if.load_bias_req) begin
            if (!bias_if.load_bias_granted) begin
                // $display(
                //     "%s  [%0t] [WAIT] Bias Loader requesting, waiting for grant (icb_sel=%0d)%s",
                //     COLOR_GRAY, $time, ctrl_if.icb_sel, COLOR_RESET);
            end else begin
                $display("%s  [%0t] [GRANTED] Bias Loader requesting and granted (icb_sel=%0d)%s",
                         COLOR_CYAN, $time, ctrl_if.icb_sel, COLOR_RESET);
            end
        end

        // Quant Loader 监控
        if (quant_if.load_quant_req) begin
            if (!quant_if.load_quant_granted) begin
                // $display(
                //     "%s  [%0t] [WAIT] Quant Loader requesting, waiting for grant (icb_sel=%0d)%s",
                //     COLOR_GRAY, $time, ctrl_if.icb_sel, COLOR_RESET);
            end else begin
                $display("%s  [%0t] [GRANTED] Quant Loader requesting and granted (icb_sel=%0d)%s",
                         COLOR_CYAN, $time, ctrl_if.icb_sel, COLOR_RESET);
            end
        end

        // OA Writer 监控
        if (oa_if.write_oa_req) begin
            if (!oa_if.write_oa_granted) begin
                // $display("%s  [%0t] [WAIT] OA Writer requesting, waiting for grant (icb_sel=%0d)%s",
                //          COLOR_GRAY, $time, ctrl_if.icb_sel, COLOR_RESET);
            end else begin
                $display("%s  [%0t] [GRANTED] OA Writer requesting and granted (icb_sel=%0d)%s",
                         COLOR_CYAN, $time, ctrl_if.icb_sel, COLOR_RESET);
            end
        end
    end
endtask

`endif  // TEST_MONITOR_TASKS_SVH
