module compare_pending #(parameter int W=87) (
    input logic [W-1:0] issued,
    input logic [1:0] pending_loads, pending_sends,
    input logic load_done, send_done,
    output logic equivalent
);
    logic [W-1:0] loaded, sent, loaded_next, sent_next;
    logic [1:0] remaining_loads, remaining_sends;
    logic issued_zero, issued_one, loads_wrap, sends_wrap;
    logic final_load_compare, final_sent_compare;
    assign loaded = issued - W'(pending_loads);
    assign sent = issued - W'(pending_sends);
    assign loaded_next = loaded + W'(load_done);
    assign sent_next = sent + W'(1);
    assign remaining_loads = pending_loads - 2'(load_done);
    assign remaining_sends = pending_sends - 2'd1;
    assign issued_zero = issued == '0;
    assign issued_one = issued == W'(1);
    assign loads_wrap = (remaining_loads != 0 && issued_zero) ||
        (remaining_loads == 2 && issued_one);
    assign sends_wrap = (remaining_sends != 0 && issued_zero) ||
        (remaining_sends == 2 && issued_one);
    assign final_load_compare = pending_loads == 1 || (pending_loads == 2 && issued_zero);
    assign final_sent_compare = (sends_wrap != loads_wrap) ? sends_wrap :
        (remaining_sends <= remaining_loads);
    assign equivalent = (pending_loads > 2 || (load_done && pending_loads == 0) ||
        (send_done && pending_sends == 0)) ||
        ((!load_done || final_load_compare == (loaded_next >= issued)) &&
         (!send_done || final_sent_compare == (sent_next >= loaded_next)));
endmodule
