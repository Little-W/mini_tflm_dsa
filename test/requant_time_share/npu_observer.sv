// SPDX-License-Identifier: Apache-2.0
module requant_group_npu_observer #(parameter int p_rows=512);
    integer input_remaining=0, output_remaining=0, issued_pending=0;
    longint unsigned groups=0, input_rows=0, output_rows=0, issued_rows=0;
    longint unsigned canceled_rows=0, maximum_rows=0;
    always @(posedge requant_group_buffer.clk) begin
        if(!requant_group_buffer.rst_n || requant_group_buffer.i_clear)begin
            canceled_rows<=canceled_rows+64'(output_remaining);
            input_remaining<=0;
            output_remaining<=0;
            issued_pending<=0;
        end else begin
            assert(requant_group_buffer.stored_rows_q<=p_rows);
            assert(input_remaining>=0 && input_remaining<=p_rows);
            assert(requant_group_buffer.pending_rows_q==output_remaining);
            assert(output_remaining==input_remaining+int'(requant_group_buffer.stored_rows_q)+
                int'(requant_group_buffer.head_valid_q)+issued_pending);
            if(requant_group_buffer.i_group_start)begin
                assert(requant_group_buffer.o_group_ready && output_remaining==0);
                assert(requant_group_buffer.i_group_rows>0 && requant_group_buffer.i_group_rows<=p_rows);
                input_remaining<=int'(requant_group_buffer.i_group_rows)-int'(requant_group_buffer.push_row);
                output_remaining<=int'(requant_group_buffer.i_group_rows);
                groups<=groups+1;
                if(requant_group_buffer.i_group_rows>maximum_rows)
                    maximum_rows<=requant_group_buffer.i_group_rows;
            end else begin
                if(requant_group_buffer.push_row)begin
                    assert(input_remaining>0);
                    input_remaining<=input_remaining-1;
                end
                if(requant_group_buffer.i_output_valid)begin
                    assert(output_remaining>0 && issued_pending>0);
                    output_remaining<=output_remaining-1;
                end
            end
            case({requant_group_buffer.consume_row,requant_group_buffer.i_output_valid})
                2'b10:issued_pending<=issued_pending+1;
                2'b01:issued_pending<=issued_pending-1;
                default:begin end
            endcase
            if(requant_group_buffer.push_row)input_rows<=input_rows+1;
            if(requant_group_buffer.consume_row)issued_rows<=issued_rows+1;
            if(requant_group_buffer.i_output_valid)output_rows<=output_rows+1;
        end
    end
    final $display("REQUANT_GROUP_NPU_PASS groups=%0d inputs=%0d issued=%0d outputs=%0d canceled=%0d maximum_rows=%0d",
                   groups,input_rows,issued_rows,output_rows,canceled_rows,maximum_rows);
endmodule
bind requant_group_buffer requant_group_npu_observer #(.p_rows(p_rows)) u_requant_group_observer();
