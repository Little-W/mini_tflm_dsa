/* verilator lint_off DECLFILENAME */
module ia_request_stage_observer;
    longint unsigned request_wait_cycles = 0;
    longint unsigned issued_commands = 0;
    longint unsigned prefetch_commands = 0;
    longint unsigned internal_cache_hits = 0;
    longint unsigned cancelled_reservations = 0;
    longint unsigned unreserved_grants = 0;
    logic demand_issued, prefetch_issued;
    logic [$bits(ia_loader.request_descriptor)-1:0] saved_demand;
    logic [$bits(ia_loader.prefetch_descriptor)-1:0] saved_prefetch;

    always @(posedge ia_loader.clk) begin
        demand_issued = 1'b0;
        prefetch_issued = 1'b0;
        if (ia_loader.rst_n && ia_loader.p_register_dma_request) begin
            assert (ia_loader.request_permission ==
                    (ia_loader.load_ia_granted && ia_loader.load_ia_req))
                else $fatal(1, "External grant qualification differs");
            request_wait_cycles += 64'(ia_loader.load_ia_req && !ia_loader.load_ia_granted);
            unreserved_grants += 64'(ia_loader.load_ia_granted && !ia_loader.load_ia_req);
            cancelled_reservations += 64'(ia_loader.load_ia_req &&
                                         (ia_loader.init_cfg || ia_loader.cache_flush));
            internal_cache_hits += 64'(ia_loader.cache_hit_event);
            demand_issued = ia_loader.u_ctrl.load_issue;
            prefetch_issued = ia_loader.prefetch_issue;
            if (demand_issued) saved_demand = ia_loader.request_descriptor;
            if (prefetch_issued) saved_prefetch = ia_loader.prefetch_descriptor;
        end
    end

    always @(negedge ia_loader.clk) begin
        if (ia_loader.rst_n && ia_loader.p_register_dma_request && ia_loader.ext_dma_start) begin
            assert (ia_loader.load_ia_granted && ia_loader.load_ia_req)
                else $fatal(1, "DMA command has no reserved external grant");
            if (ia_loader.prefetch_start) begin
                assert (prefetch_issued && ia_loader.dma_descriptor == saved_prefetch)
                    else $fatal(1, "Prefetch command differs from its accepted descriptor");
                prefetch_commands++;
            end else begin
                assert (demand_issued && ia_loader.dma_descriptor == saved_demand)
                    else $fatal(1, "Demand command differs from its accepted descriptor");
            end
            issued_commands++;
        end
    end

    final begin
        if (ia_loader.p_register_dma_request)
            $display("IA_REQUEST_STAGE_PASS wait_cycles=%0d commands=%0d prefetch_commands=%0d cache_hits=%0d cancelled_reservations=%0d unreserved_grants=%0d",
                     request_wait_cycles, issued_commands, prefetch_commands,
                     internal_cache_hits, cancelled_reservations, unreserved_grants);
    end
endmodule
bind ia_loader ia_request_stage_observer u_request_stage_observer();
/* verilator lint_on DECLFILENAME */
