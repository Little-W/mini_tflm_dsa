// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module kernel_loader_buffer_observer;

always @(posedge kernel_loader_buffer.clk)if(kernel_loader_buffer.rst_n)begin
            if(kernel_loader_buffer.discard_fire)assert(!kernel_loader_buffer.send_start)else $fatal(1,"kernel discard and send overlap");
            if(kernel_loader_buffer.load_start)assert(kernel_loader_buffer.load_ready)else $fatal(1,"kernel load without a free slot");
            if(kernel_loader_buffer.row_valid_q)assert(kernel_loader_buffer.slot_reserved[kernel_loader_buffer.row_slot_q])else $fatal(1,"kernel response has no reserved slot");
            if(kernel_loader_buffer.load_done_q)assert(kernel_loader_buffer.slot_reserved[kernel_loader_buffer.done_slot_q] && !kernel_loader_buffer.slot_loaded[kernel_loader_buffer.done_slot_q])
                else $fatal(1,"kernel completion slot state mismatch");

end
endmodule
bind kernel_loader_buffer kernel_loader_buffer_observer tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
