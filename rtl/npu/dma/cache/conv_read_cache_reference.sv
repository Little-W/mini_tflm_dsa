// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// SPDX-License-Identifier: Apache-2.0
// Blocking read-only cache. Policy 0: original LRU. Policy 1: geometric
// next-line-use. Policy 2: geometric next-use plus reversible XOR set indexing.
// A 16-byte transient buffer serves only the current consecutive line run.
/* 按地址组织共享输入缓存，保存读取请求并执行标签替换与数据填充。 */ module conv_read_cache_reference #(
  parameter int SETS=32,
  parameter int WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int BUS_WIDTH=32,
  parameter int READ_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=2,
  parameter int SI=$clog2(SETS),
  parameter int LB=$clog2(LINE_BYTES),
  parameter int WB=$clog2(LINE_BYTES/4),
  parameter int WI=(WAYS==1 ? 1 : $clog2(WAYS)),
  parameter int DEPTH=WAYS*SETS*(LINE_BYTES/4),
  parameter int DA=$clog2(DEPTH),
  parameter int TAGW=32-LB-SI
) (
  input wire logic clk /* 工作时钟 */, rst_n /* 低有效复位 */,
  input wire logic cfg_valid /* 缓存任务配置有效 */,
  output logic cfg_ready /* 缓存可接收任务配置 */,
  input wire logic [31:0] cfg_base /* 输入区域首字节地址 */, cfg_bytes /* 输入区域的字节数 */,
  input wire logic cfg_bypass /* 启用直接读取旁路 */,
  input wire logic cfg_geometry = 1'b0 /* 启用卷积几何事件信息 */,
  input wire logic req_valid /* 正式缓存读取请求有效 */,
  output logic req_ready /* 缓存可接收正式读取请求 */,
  input wire logic [31:0] req_addr /* 正式请求的字节地址 */,
  input wire logic req_geometry = 1'b0 /* 当前请求携带卷积几何事件信息 */,
  input wire logic req_event_first = 1'b0 /* 当前请求是几何事件的首个数据拍 */,
  input wire logic hint_valid = 1'b0 /* 下一次使用顺序提示有效 */,
  input wire logic [31:0] hint_next = 32'hffff_ffff /* 当前缓存行的下一次使用顺序 */,
  output logic hint_pending /* 当前缓存行仍等待下一次使用顺序提示 */,
  output logic rsp_valid /* 缓存读取响应有效 */,
  input wire logic rsp_ready /* 请求端可接收缓存读取响应 */,
  output logic [READ_WIDTH-1:0] rsp_data /* 返回请求端的读取数据 */,
  output logic rsp_error /* 当前读取响应携带错误 */,
  output logic arvalid /* AXI：读地址请求有效 */,
  input wire logic arready /* AXI：可接收读地址请求 */,
  output logic [31:0] araddr /* AXI：读突发首字节地址 */,
  output logic [7:0] arlen /* AXI：读突发传输拍数减一 */,
  output logic [2:0] arsize /* AXI：每个读数据拍字节数的二进制对数 */,
  output logic [1:0] arburst /* AXI：读突发地址递增类型 */,
  input wire logic rvalid /* AXI：读响应数据有效 */,
  output logic rready /* AXI：可接收读响应数据 */,
  input wire logic [BUS_WIDTH-1:0] rdata /* AXI：读响应数据 */,
  input wire logic [1:0] rresp /* AXI：读响应状态码 */,
  input wire logic rlast /* AXI：当前读突发的最后一个数据拍 */);
  localparam int p_read_bytes = READ_WIDTH / 8;
  localparam int p_read_shift = $clog2(p_read_bytes);
  localparam logic [31:0] INF = 32'hffff_ffff;
  typedef enum logic [3:0] {UNCONFIGURED, CLEAR, IDLE, TAG_READ, TAG_EVAL,
    HINT_WAIT, FILL_REQ, FILL, COMMIT, STREAM_READ, RAM_READ, RAM_WAIT, RESP} st_t;
  st_t state;
  logic [TAGW-1:0] tags [0:WAYS-1][0:SETS-1];
  logic valids [0:WAYS-1][0:SETS-1];
  logic [31:0] next_use [0:WAYS-1][0:SETS-1];
  logic lru [0:SETS-1];
  logic [TAGW-1:0] tag_q [0:WAYS-1];
  logic valid_q [0:WAYS-1];
  logic [31:0] next_q [0:WAYS-1];
  logic lru_q;
  logic [SI-1:0] set_q, clear_set, pending_set;
  logic [WI-1:0] way_q, chosen_way, victim_way, pending_way;
  logic [31:0] base_q, end_q, addr_q, line_base;
  logic [31:0] fill_first, fill_end, fetch_base, fetch_bytes;
  logic [32:0] fetch_limit;
  logic bypass_q, geometry_q, request_geometry_q, first_q, allocation_q;
  logic hint_seen;
  logic [31:0] hint_q;
  logic effective_hint_valid;
  logic [31:0] effective_hint, farthest;
  logic [TAGW-1:0] wanted_tag;
  logic hit, has_invalid, fill_error;
  logic transient_valid;
  logic [27:0] transient_tag;
  logic [31:0] transient_words [4];
  logic ram_ren, ram_wen;
  logic [DA-1:0] ram_raddr, ram_waddr;
  logic [READ_WIDTH-1:0] ram_rdata;
  logic span_req_valid, span_req_ready;
  logic span_rsp_valid, span_rsp_ready, span_last, span_error;
  logic [31:0] span_addr;
  (* keep = "true" *) logic [32:0] span_request_bytes_wide;
  // 完整起止地址相减后选择有效长度，避免长度选择与逐位进位串接。
  assign span_request_bytes_wide = {1'b0, fill_end} - {1'b0, fill_first};
  logic [BUS_WIDTH-1:0] span_data;
  logic [BUS_WIDTH/8-1:0] span_strb;
  logic span_busy;

  // 按读取宽度选择瞬态行中的连续数据，地址低位不改变返回分组。
  function automatic logic [READ_WIDTH-1:0] transient_read(input logic [31:0] address);
    logic [READ_WIDTH-1:0] value;
    value = '0;
    for (int word = 0; word < READ_WIDTH/32; word++) begin
      value[word*32 +: 32] = transient_words[(int'(address[3:2]) & (4-READ_WIDTH/32))+word];
    end
    return value;
  endfunction

  function automatic logic [SI-1:0] address_set(input logic [31:0] address,
                                                input logic geometric);
    logic [SI-1:0] raw_set;
    raw_set = SI'(address >> LB);
    return raw_set ^ ((geometric && CACHE_POLICY==2) ? SI'(address >> (LB+SI)) : SI'(0));
  endfunction
  assign cfg_ready = state==UNCONFIGURED || (state==IDLE && !hint_pending);
  assign req_ready = state==IDLE && !cfg_valid &&
    !(hint_pending && (req_event_first || req_addr[31:LB]!=addr_q[31:LB]));
  assign rsp_valid = state==RESP;
  assign wanted_tag = addr_q[31:LB+SI];
  assign line_base = {addr_q[31:LB],{LB{1'b0}}};
  assign fetch_base = bypass_q ? {addr_q[31:p_read_shift],{p_read_shift{1'b0}}} : line_base;
  assign fetch_bytes = bypass_q ? 32'(p_read_bytes) : 32'(LINE_BYTES);
  assign fill_first = fetch_base<base_q ? base_q : fetch_base;
  assign fetch_limit = {1'b0,fetch_base}+{1'b0,fetch_bytes};
  assign fill_end = fetch_limit>{1'b0,end_q} ? end_q : fetch_limit[31:0];
  assign effective_hint_valid = hint_seen || hint_valid;
  assign effective_hint = hint_seen ? hint_q : hint_next;

  always_comb begin
    hit=0; has_invalid=0;
    chosen_way = WAYS==1 ? WI'(0) : WI'(lru_q);
    victim_way=0; farthest=next_q[0];
    for (int w=1; w<WAYS; w++)
      if (next_q[w]>farthest) begin farthest=next_q[w];victim_way=WI'(w);end
    if (request_geometry_q) chosen_way=victim_way;
    for (int w=WAYS-1; w>=0; w--)
      if (!valid_q[w]) begin chosen_way=WI'(w);has_invalid=1;end
    for (int w=0; w<WAYS; w++)
      if (valid_q[w] && tag_q[w]==wanted_tag) begin hit=1;chosen_way=WI'(w);end
  end
  assign ram_ren = state==RAM_READ;
  assign ram_raddr = DA'((32'(way_q)*SETS+32'(set_q))*(LINE_BYTES/4)
                         +((addr_q>>2)&(LINE_BYTES/4-1)));
  // Non-admitted misses MUST NOT overwrite a valid main-cache data line.
  assign ram_wen = state==FILL && span_rsp_valid && span_rsp_ready && allocation_q;
  assign ram_waddr = DA'((32'(way_q)*SETS+32'(set_q))*(LINE_BYTES/4)
                         +((span_addr>>2)&(LINE_BYTES/4-1)));
  conv_sdp_ram #(.DEPTH(DEPTH),.AW(DA),.WRITE_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH)) u_data (
    .clk,.rd_en(ram_ren),.rd_addr(ram_raddr),.rd_data(ram_rdata),
    .wr_en(ram_wen),.wr_addr(ram_waddr),.wr_data(span_data),.wr_strb(span_strb)
  );
  assign span_req_valid = state==FILL_REQ;
  assign span_rsp_ready = state==FILL;
  conv_axi_span_reader #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES),
    .MAX_REQUEST_BYTES(LINE_BYTES)) u_span (
    .clk,.rst_n,.req_valid(span_req_valid),.req_ready(span_req_ready),
    .req_addr(fill_first),.req_bytes(span_request_bytes_wide[15:0]),
    .rsp_valid(span_rsp_valid),.rsp_ready(span_rsp_ready),
    .rsp_word_addr(span_addr),.rsp_data(span_data),.rsp_strb(span_strb),
    .rsp_last(span_last),.rsp_error(span_error),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,.busy(span_busy)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=UNCONFIGURED;base_q<=0;end_q<=0;addr_q<=0;
      clear_set<=0;set_q<=0;way_q<=0;lru_q<=0;bypass_q<=0;geometry_q<=0;
      request_geometry_q<=0;first_q<=0;allocation_q<=0;fill_error<=0;
      hint_seen<=0;hint_q<=INF;hint_pending<=0;pending_set<=0;pending_way<=0;
      transient_valid<=0;transient_tag<=0;
      for (int i=0;i<4;i++) transient_words[i]<=0;
      rsp_data<=0;rsp_error<=0;
    end else begin
      if (hint_pending && hint_valid) begin
        next_use[pending_way][pending_set]<=hint_next;
        hint_pending<=0;
      end
      if (state!=IDLE && request_geometry_q && hint_valid && !hint_seen) begin
        hint_seen<=1;hint_q<=hint_next;
      end
      if (cfg_valid && cfg_ready) begin
        base_q<=cfg_base;end_q<=cfg_base+cfg_bytes;bypass_q<=cfg_bypass;
        geometry_q<=cfg_geometry && !cfg_bypass && CACHE_POLICY!=0 && LINE_BYTES==16;
        clear_set<=0;state<=CLEAR;hint_pending<=0;transient_valid<=0;
        rsp_error<=0;
      end else case (state)
        UNCONFIGURED: ;
        CLEAR: begin
          for (int w=0;w<WAYS;w++) valids[w][clear_set]<=0;
          lru[clear_set]<=0;
          if (clear_set==SI'(SETS-1)) state<=IDLE;
          else clear_set<=clear_set+1'b1;
        end
        IDLE: if (req_valid && req_ready) begin
          addr_q<=req_addr;set_q<=address_set(req_addr,geometry_q);
          request_geometry_q<=geometry_q && req_geometry;
          first_q<=req_event_first;hint_seen<=hint_valid;hint_q<=hint_next;
          rsp_error<=0;
          // Even a main-cache HIT on another line ends the transient lifetime.
          if (transient_valid && transient_tag!=req_addr[31:4]) transient_valid<=0;
          if (req_addr<base_q || req_addr>=end_q) begin
            rsp_data<=0;rsp_error<=1;state<=RESP;
          end else if (bypass_q) begin
            way_q<=0;allocation_q<=1;fill_error<=0;
            state<=FILL_REQ;
          end else if (geometry_q && req_geometry && transient_valid && transient_tag==req_addr[31:4]) begin
            rsp_data<=transient_read(req_addr);
            state<=RESP;
          end else state<=TAG_READ;
        end
        TAG_READ: begin
          for (int w=0;w<WAYS;w++) begin
            tag_q[w]<=tags[w][set_q];valid_q[w]<=valids[w][set_q];
            next_q[w]<=next_use[w][set_q];
          end
          lru_q<=lru[set_q];state<=TAG_EVAL;
        end
        TAG_EVAL, HINT_WAIT: begin
          way_q<=chosen_way;
          if (hit) begin

            if (WAYS==2) lru[set_q]<=!chosen_way[0];
            if (request_geometry_q && first_q) begin
              if (effective_hint_valid) next_use[chosen_way][set_q]<=effective_hint;
              else begin hint_pending<=1;pending_way<=chosen_way;pending_set<=set_q;end
            end
            state<=RAM_READ;
          end else if (request_geometry_q && !has_invalid && !effective_hint_valid) begin
            state<=HINT_WAIT;
          end else begin
            fill_error<=0;
            transient_valid<=0;
            if (request_geometry_q) begin
              for (int i=0;i<4;i++) transient_words[i]<=0;
            end
            if (request_geometry_q && effective_hint_valid &&
                (effective_hint==INF || (!has_invalid && effective_hint>=farthest))) begin
              allocation_q<=0;
            end else begin
              allocation_q<=1;valids[chosen_way][set_q]<=0;
            end
            state<=FILL_REQ;
          end
        end
        FILL_REQ: if (span_req_ready) state<=FILL;
        FILL: if (span_rsp_valid && span_rsp_ready) begin

          fill_error<=fill_error || span_error;
          if (request_geometry_q)
            for (int b=0;b<BUS_WIDTH/8;b++)
              if (span_strb[b]) transient_words[(int'(span_addr[3:0])+b)/4][8*(b%4)+:8]<=span_data[8*b+:8];
          if (span_last) begin
            if (fill_error || span_error) begin
              rsp_error<=1;rsp_data<=0;transient_valid<=0;state<=RESP;
            end else if (request_geometry_q) begin
              state<=COMMIT;
            end else begin
              if (!bypass_q) begin
                tags[way_q][set_q]<=wanted_tag;valids[way_q][set_q]<=1;
                next_use[way_q][set_q]<=INF;
                if (WAYS==2) lru[set_q]<=!way_q[0];
              end
              state<=RAM_READ;
            end
          end
        end
        COMMIT: if (effective_hint_valid) begin
          if (allocation_q && effective_hint!=INF) begin
            tags[way_q][set_q]<=wanted_tag;valids[way_q][set_q]<=1;
            next_use[way_q][set_q]<=effective_hint;
            if (WAYS==2) lru[set_q]<=!way_q[0];
            state<=RAM_READ;
          end else begin
            transient_valid<=1;transient_tag<=addr_q[31:4];state<=STREAM_READ;
          end
        end
        STREAM_READ: begin rsp_data<=transient_read(addr_q);rsp_error<=0;state<=RESP;end
        RAM_READ: state<=RAM_WAIT;
        RAM_WAIT: begin rsp_data<=ram_rdata;rsp_error<=0;state<=RESP;end
        RESP: if (rsp_ready) state<=IDLE;
        default: state<=UNCONFIGURED;
      endcase
    end
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    if (SETS<2 || (SETS&(SETS-1))!=0) $fatal(1,"SETS must be a power of two >=2");
    if (WAYS!=1 && WAYS!=2) $fatal(1,"WAYS must be 1 or 2");
    if (LINE_BYTES<8 || LINE_BYTES>256 || (LINE_BYTES&(LINE_BYTES-1))!=0)
      $fatal(1,"LINE_BYTES must be a power of two in [8,256]");
    if (CACHE_POLICY<0 || CACHE_POLICY>2) $fatal(1,"CACHE_POLICY must be 0, 1, or 2");
  end
`endif
`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk) if (rst_n) begin
    if (cfg_valid && cfg_ready) begin
      assert (cfg_bytes!=0);
      assert ({1'b0,cfg_base}+{1'b0,cfg_bytes}<33'h1_0000_0000);
    end
    if (state==FILL_REQ) assert (!span_busy);
    if (state==FILL) assert (span_busy);
    if (ram_wen) assert (span_addr[31:LB]==addr_q[31:LB]);
    if (state==FILL && !allocation_q) assert (!ram_wen);
    if (hint_pending) assert (geometry_q);
  end
`endif
endmodule

`default_nettype wire
