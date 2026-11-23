`timescale 1ns/1ps

// Observe addressable PS frames and verify every recovered INT32 lane.
module ps_stream_capture #(
    parameter integer FRAME_COUNT = 16,
    parameter integer MAX_FRAME_ROWS = 64,
    parameter integer PAYLOAD_BANKS = 4
) (
    input wire clk, rst_n,
    input wire [63:0] cycle, job,
    input wire frame_accept, frame_complete,
    input wire [31:0] frame_id, frame_rows,
    input wire frame_init, frame_final,
    input wire write_valid,
    input wire [511:0] write_data,
    input wire replay_valid,
    input wire [511:0] replay_data,
    input wire [PAYLOAD_BANKS-1:0] payload_write_en, payload_read_en,
    input wire decoded_write_en, decoded_read_en, replay_bypass,
    input wire [31:0] occupied_payload_bytes
);
    reg [511:0] expected [FRAME_COUNT * MAX_FRAME_ROWS];
    reg [FRAME_COUNT * MAX_FRAME_ROWS-1:0] live_rows = '0;
    integer active_id = 0, active_rows = 0, write_row = 0, read_row = 0;
    bit active = 0, active_init = 0, active_final = 0;
    integer live = 0, fd = 0;
    string filename;
    longint unsigned writes = 0, reads = 0, discarded = 0, frames = 0;
    longint unsigned payload_write_bytes = 0, payload_read_bytes = 0;
    longint unsigned fifo_write_bytes = 0, fifo_read_bytes = 0, direct_rows = 0;
    longint unsigned peak_payload_bytes = 0;
    initial begin
        if ($value$plusargs("PS_EVENTS=%s", filename)) begin
            fd = $fopen(filename, "w");
            assert(fd != 0) else $fatal(1, "Cannot open PS event file");
            $fdisplay(fd, "H version=3 lanes=16 bits=32 frames=%0d rows=%0d", FRAME_COUNT, MAX_FRAME_ROWS);
        end
    end
    always @(posedge clk) begin : observe_write
        integer index;
        if (!rst_n) begin
            if (live != 0 || active) begin
                discarded += 64'(live);
                if (fd != 0) $fdisplay(fd, "X cycle=%0d job=%0d rows=%0d", cycle, job, live);
            end
            live_rows = '0; live = 0; active = 0;
            active_id = 0; active_rows = 0; write_row = 0; read_row = 0;
        end else begin
            if (write_valid) begin
                assert(active && !active_final && write_row < active_rows)
                    else $fatal(1, "PS write outside the active descriptor");
                index = active_id * MAX_FRAME_ROWS + write_row;
                assert(!live_rows[index]) else $fatal(1, "PS replacement precedes recovery of the old row");
                expected[index] = write_data; live_rows[index] = 1'b1;
                live++; writes++;
                if (fd != 0) $fdisplay(fd, "W cycle=%0d job=%0d frame=%0d row=%0d data=%0128x",
                    cycle, job, active_id, write_row, write_data);
                write_row++;
            end
            if (frame_complete) begin
                assert(active && write_row == (active_final ? 0 : active_rows) &&
                       read_row == (active_init ? 0 : active_rows))
                    else $fatal(1, "Incomplete PS frame at completion");
                if (fd != 0) $fdisplay(fd, "E cycle=%0d job=%0d frame=%0d", cycle, job, active_id);
                active = 0; frames++;
            end
            // 当前帧的数据和完成事件先处理，随后接收同拍到达的下一帧描述符。
            if (frame_accept) begin
                assert(!active && frame_id < FRAME_COUNT && frame_rows > 0 && frame_rows <= MAX_FRAME_ROWS)
                    else $fatal(1, "Invalid PS observer descriptor");
                active = 1; active_id = int'(frame_id); active_rows = int'(frame_rows);
                active_init = frame_init; active_final = frame_final;
                write_row = 0; read_row = 0;
                for (int row=0; row<MAX_FRAME_ROWS; row++) begin
                    index = active_id * MAX_FRAME_ROWS + row;
                    assert(live_rows[index] == (!frame_init && row < active_rows))
                        else $fatal(1, "PS frame occupancy differs at acceptance");
                end
                if (fd != 0) $fdisplay(fd, "F cycle=%0d job=%0d frame=%0d rows=%0d init=%0d final=%0d",
                    cycle, job, active_id, active_rows, active_init, active_final);
            end
            payload_write_bytes += 16 * $countones(payload_write_en);
            payload_read_bytes += 16 * $countones(payload_read_en);
            fifo_write_bytes += decoded_write_en ? 64 : 0;
            fifo_read_bytes += decoded_read_en ? 64 : 0;
            direct_rows += replay_bypass;
            if (64'(occupied_payload_bytes) > peak_payload_bytes) peak_payload_bytes = 64'(occupied_payload_bytes);
        end
    end
    always @(negedge clk) begin : observe_replay
        integer index;
        if (rst_n && replay_valid) begin
            assert(active && !active_init && read_row < active_rows)
                else $fatal(1, "PS replay outside the active descriptor");
            index = active_id * MAX_FRAME_ROWS + read_row;
            assert(live_rows[index] && replay_data === expected[index])
                else $fatal(1, "PS INT32 mismatch job=%0d frame=%0d row=%0d expected=%0128x actual=%0128x",
                            job, active_id, read_row, expected[index], replay_data);
            live_rows[index] = 1'b0; live--; reads++;
            if (fd != 0) $fdisplay(fd, "R cycle=%0d job=%0d frame=%0d row=%0d data=%0128x",
                cycle, job, active_id, read_row, replay_data);
            read_row++;
        end
    end
    final begin
        assert(live == 0 && !active && writes == reads + discarded)
            else $error("Incomplete PS recovery writes=%0d reads=%0d discarded=%0d live=%0d", writes, reads, discarded, live);
        $display("PS_STREAM_SUMMARY writes=%0d reads=%0d discarded=%0d frames=%0d payload_write_bytes=%0d payload_read_bytes=%0d fifo_write_bytes=%0d fifo_read_bytes=%0d direct_rows=%0d peak_payload_bytes=%0d",
            writes, reads, discarded, frames, payload_write_bytes, payload_read_bytes,
            fifo_write_bytes, fifo_read_bytes, direct_rows, peak_payload_bytes);
        if (fd != 0) $fclose(fd);
    end
endmodule
