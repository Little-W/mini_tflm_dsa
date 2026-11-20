// SPDX-License-Identifier: Apache-2.0
module vector_writeback_overlap_observer();
  longint unsigned response_reissues=0,error_response_waits=0;
  always @(posedge vector_writeback.clk) if (vector_writeback.rst_n) begin
    assert(!(vector_writeback.request_fire && vector_writeback.publish_fire));
    if (vector_writeback.c_st==vector_writeback.RESPONSE && vector_writeback.wr_done) begin
      if (vector_writeback.wr_error) begin
        assert(!vector_writeback.publish_fire);
        if (vector_writeback.pending_bytes!=0) error_response_waits<=error_response_waits+1;
      end else if (vector_writeback.publish_fire) begin
        assert(vector_writeback.n_st==vector_writeback.REQUEST);
        response_reissues<=response_reissues+1;
      end
    end
  end
  final begin
    assert(response_reissues>0 && error_response_waits>0);
    $display("VECTOR_WRITEBACK_OVERLAP_PASS reissues=%0d error_waits=%0d",response_reissues,error_response_waits);
  end
endmodule
bind vector_writeback vector_writeback_overlap_observer tb_overlap();
