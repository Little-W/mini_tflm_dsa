// ================================================================
// tb_scoreboard.sv — 输出捕获与 golden 比对（`include 到 tb_ia_loader 内）
// ================================================================
// 依赖：SIZE, DATA_WIDTH, K(=TC_K), N(=TC_N), LHS_ZP 等来自顶层

  // ── golden 矩阵 ──
  logic signed [15:0] golden_ia [TC_K][TC_N];

  initial begin
    for (int r = 0; r < TC_K; r++) begin
      for (int c = 0; c < TC_N; c++) begin
        automatic int raw = r * TC_N + c + 1;
        if (TC_USE_16BITS) begin
          golden_ia[r][c] = 16'(raw & 16'hFFFF);
        end else begin
          // s8 模式：按 8 位截断后符号扩展到 s16，与硬件路径一致。
          automatic logic signed [7:0] s8v;
          s8v = $signed(raw[7:0]);
          golden_ia[r][c] = {{8{s8v[7]}}, s8v};
        end
      end
    end
  end

  // ── 统计 ──
  int tile_send_count = 0;
  int error_count     = 0;
  int total_checks    = 0;

  // ── L1 组输出捕获缓冲（逆对角化后存储，行数最多 TC_K，列数 SIZE）──
  logic signed [DATA_WIDTH-1:0] captured_l1 [TC_K][SIZE];

  // ── 发送序列 ──
  typedef struct packed {
    logic [31:0] tile_r;
    logic [31:0] tile_c;
    logic [31:0] vrows;
    logic        is_first;
    logic        calc_done;
  } tile_info_t;

  tile_info_t send_queue [TC_TOTAL_SENDS];
  int send_queue_size;

  initial begin
    send_queue_size = 0;
    for (int l2 = 0; l2 < TC_G2; l2++) begin
      automatic int r_cur = (l2 == TC_G2-1) ? TC_R_ACT : TC_R;
      for (int l1 = 0; l1 < TC_G1; l1++) begin
        for (int w = 0; w < TC_W; w++) begin
          for (int ia = 0; ia < r_cur; ia++) begin
            automatic int tr = l2 * TC_R + ia;
            automatic int tc = l1;
            send_queue[send_queue_size].tile_r    = tr;
            send_queue[send_queue_size].tile_c    = tc;
            send_queue[send_queue_size].vrows     = (tr == TC_VTN-1) ? (TC_K - tr * SIZE) : SIZE;
            send_queue[send_queue_size].is_first  = (l1 == 0) ? 1'b1 : 1'b0;
            send_queue[send_queue_size].calc_done = (l1 == TC_G1-1) ? 1'b1 : 1'b0;
            send_queue_size++;
          end
        end
      end
    end
    $display("[SCB] Built send_queue: %0d entries", send_queue_size);
  end

  // ── 比对整个 L1 组的输出（ti_start 到 ti_start+r_cur-1 共 r_cur 个 tile）──
  // captured_l1[row][col] 是逆对角化后的平铺行数据
  task automatic check_l1_output(input int ti_start, input int r_cur);
    int row_offset = 0;
    for (int t = 0; t < r_cur; t++) begin
      automatic int ti    = ti_start + t;
      automatic int ti_r  = int'(send_queue[ti].tile_r);
      automatic int ti_c  = int'(send_queue[ti].tile_c);
      automatic int vrows = int'(send_queue[ti].vrows);
      automatic int vcols = (ti_c == TC_HTN - 1) ? (TC_N - ti_c * SIZE) : SIZE;
      for (int row = 0; row < vrows; row++) begin
        for (int col = 0; col < vcols; col++) begin
          automatic int mat_r = ti_r * SIZE + row;
          automatic int mat_c = ti_c * SIZE + col;
          automatic logic signed [DATA_WIDTH-1:0] expected;
          expected = DATA_WIDTH'(golden_ia[mat_r][mat_c] + TC_LHS_ZP);
          total_checks++;
          if (captured_l1[row_offset + row][col] !== expected) begin
            if (error_count < 20)
              $display("[SCB] ERROR tile(%0d,%0d) r=%0d c=%0d: got %0d exp %0d",
                       ti_r, ti_c, row, col,
                       captured_l1[row_offset + row][col], expected);
            error_count++;
          end
        end
      end
      row_offset += vrows;
    end
  endtask
