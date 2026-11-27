// SPDX-License-Identifier: Apache-2.0
// 在实际缓存实例中统计请求接收、处理、响应保存及返回之间的周期。
module conv_cache_throughput_observer;
  bit enabled, trace_enabled;
  longint unsigned cycle, accepted, processed, saved, returned;
  longint unsigned last_accept, last_return, trace_count;
  longint unsigned preview_processed, queued_processed, active_cycles, no_response;
  longint unsigned accept_gap[65], return_gap[65];
  longint unsigned process_latency[65], save_latency[65], return_latency[65];
  longint unsigned process_times[$], save_times[$], return_times[$];
  longint unsigned timestamp, interval;
  integer bucket;
  initial begin
    enabled = $test$plusargs("CACHE_THROUGHPUT_PROFILE");
    trace_enabled = $test$plusargs("CACHE_THROUGHPUT_TRACE");
  end
  always @(posedge conv_windowed_cache.clk) begin
    if (!conv_windowed_cache.rst_n) begin
      cycle=0; accepted=0; processed=0; saved=0; returned=0;
      last_accept=0; last_return=0; trace_count=0;
      preview_processed=0; queued_processed=0; active_cycles=0; no_response=0;
      process_times.delete(); save_times.delete(); return_times.delete();
      for(integer index=0;index<65;index++) begin
        accept_gap[index]=0; return_gap[index]=0; process_latency[index]=0;
        save_latency[index]=0; return_latency[index]=0;
      end
    end else if (enabled || trace_enabled) begin
      cycle++;
      if (conv_windowed_cache.configured && !conv_windowed_cache.clearing) active_cycles++;
      if (conv_windowed_cache.outstanding_count!=0 && !conv_windowed_cache.rsp_valid) no_response++;
      if (conv_windowed_cache.accepted_request) begin
        process_times.push_back(cycle); save_times.push_back(cycle); return_times.push_back(cycle);
        if (accepted!=0) begin
          interval=cycle-last_accept; bucket=interval>64 ? 64 : int'(interval);
          accept_gap[bucket]++;
        end
        last_accept=cycle; accepted++;
      end
      if (conv_windowed_cache.req_fire) begin
        if (process_times.size()==0) $fatal(1,"CACHE_PROFILE_PROCESS_ORDER");
        timestamp=process_times.pop_front(); interval=cycle-timestamp;
        bucket=interval>64 ? 64 : int'(interval); process_latency[bucket]++; processed++;
        if(conv_windowed_cache.preview_active) preview_processed++;
        else queued_processed++;
      end
      if (conv_windowed_cache.response_push) begin
        if (save_times.size()==0) $fatal(1,"CACHE_PROFILE_SAVE_ORDER");
        timestamp=save_times.pop_front(); interval=cycle-timestamp;
        bucket=interval>64 ? 64 : int'(interval); save_latency[bucket]++; saved++;
      end
      if (conv_windowed_cache.consumed_response) begin
        if (return_times.size()==0) $fatal(1,"CACHE_PROFILE_RETURN_ORDER");
        timestamp=return_times.pop_front(); interval=cycle-timestamp;
        bucket=interval>64 ? 64 : int'(interval); return_latency[bucket]++;
        if (returned!=0) begin
          interval=cycle-last_return; bucket=interval>64 ? 64 : int'(interval);
          return_gap[bucket]++;
        end
        last_return=cycle; returned++;
      end
      if (trace_enabled && trace_count<512 &&
          (conv_windowed_cache.req_valid || conv_windowed_cache.outstanding_count!=0)) begin
        $display("CACHE_THROUGHPUT_TRACE cycle=%0d req=%b/%b addr=%h preview=%b/%b selected=%b paddr=%h fire=%b hit=%b rq=%0d rs=%0d out=%0d fg=%0d save=%b rsp=%b/%b work=%h",
          cycle,conv_windowed_cache.req_valid,conv_windowed_cache.req_ready,conv_windowed_cache.req_addr,
          conv_windowed_cache.preview_valid,conv_windowed_cache.preview_active,
          conv_windowed_cache.u_request_path.preview_selected_q,conv_windowed_cache.preview_addr,
          conv_windowed_cache.req_fire,conv_windowed_cache.lookup_hit,conv_windowed_cache.request_count,
          conv_windowed_cache.response_count,conv_windowed_cache.outstanding_count,
          conv_windowed_cache.fg_state,conv_windowed_cache.response_push,
          conv_windowed_cache.rsp_valid,conv_windowed_cache.rsp_ready,conv_windowed_cache.work_request.address);
        trace_count++;
      end
    end
  end
  final begin
    if (enabled || trace_enabled) begin
      $display("CACHE_THROUGHPUT_PROFILE cycles=%0d active=%0d accepted=%0d processed=%0d saved=%0d returned=%0d preview=%0d queued=%0d no_response=%0d",
        cycle,active_cycles,accepted,processed,saved,returned,preview_processed,queued_processed,no_response);
      for(integer index=0;index<65;index++) begin
        if(accept_gap[index] || return_gap[index] || process_latency[index] || save_latency[index] || return_latency[index])
          $display("CACHE_THROUGHPUT_BIN cycles=%0d accept_gap=%0d return_gap=%0d process=%0d save=%0d return=%0d",
            index,accept_gap[index],return_gap[index],process_latency[index],save_latency[index],return_latency[index]);
      end
    end
  end
endmodule

bind conv_windowed_cache conv_cache_throughput_observer throughput_observer();
