module buffer_pending #(
  parameter int SIZE=16,
  parameter int DATA_WIDTH=16
) (
  input logic clk, rst_n, cache_flush,
  input logic request_load, request_done, response_slot, request_send, request_discard,
  input logic row_valid, row_slot,
  input logic [$clog2(SIZE)-1:0] row_idx,
  input logic signed [DATA_WIDTH-1:0] row_data [SIZE],
  output logic bounds, relation,
  output logic [3:0] pending_loads, pending_sends,
  output logic [1:0] dma_pending,
  output logic [3:0] storage_objects
);
  logic load_start, load_ready, load_slot_id, load_done;
  logic load_commit, load_commit_slot, discard_ready, weight_data_valid;
  logic weight_sending_done, store_weight_req, delayed_done;
  logic signed [DATA_WIDTH-1:0] weight_out [SIZE];
  assign load_start = request_load && load_ready;
  assign load_done = request_done && dma_pending[response_slot];
  kernel_loader_buffer #(.DATA_WIDTH(DATA_WIDTH),.SIZE(SIZE)) dut (
    .clk, .rst_n, .cache_flush, .discard_head(request_discard),
    .load_start, .load_slot_id, .row_valid, .row_slot, .row_idx, .row_data,
    .load_done, .done_slot(response_slot), .send_start(request_send),
    .load_ready, .load_commit, .load_commit_slot, .discard_ready,
    .weight_data_valid, .weight_sending_done, .store_weight_req, .weight_out
  );
  always_ff @(posedge clk) begin
    if (!rst_n || cache_flush) begin
      dma_pending <= '0;
      pending_loads <= '0;
      pending_sends <= '0;
      delayed_done <= 1'b0;
    end else begin
      delayed_done <= weight_sending_done;
      if (load_done) dma_pending[response_slot] <= 1'b0;
      if (load_start) dma_pending[load_slot_id] <= 1'b1;
      pending_loads <= pending_loads + 4'(load_start) - 4'(load_done);
      pending_sends <= pending_sends + 4'(load_start) - 4'(delayed_done) - 4'(dut.discard_fire);
    end
  end
  assign storage_objects = 4'(dut.slot_reserved[0]) + 4'(dut.slot_reserved[1]) +
    4'(dut.send_active || dut.send_prefetch) + 4'(weight_sending_done) + 4'(delayed_done);
  assign bounds = !rst_n || (pending_loads <= 2 && pending_sends <= 3);
  assign relation = !rst_n || (pending_loads == 4'(dma_pending[0]) + 4'(dma_pending[1]) &&
    pending_sends == storage_objects && (dma_pending & ~dut.slot_reserved) == 0 &&
    (dut.slot_loaded & ~dut.slot_reserved) == 0 && (dut.slot_loaded & dma_pending) == 0 &&
    (!dut.load_done_q || (dut.slot_reserved[dut.done_slot_q] && !dma_pending[dut.done_slot_q])) &&
    (!dut.send_pending || dut.slot_reserved[dut.rd_slot]) &&
    (4'(dut.send_active) + 4'(dut.send_prefetch) + 4'(weight_sending_done) + 4'(delayed_done)) <= 1 &&
    (4'(dut.send_active) + 4'(dut.send_prefetch) + 4'(dut.send_pending)) <= 1);
endmodule
