// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 单路缓存元数据保存有效位、标签与替换信息，读取和同拍写入转发独立于调度状态。
module conv_cache_metadata_way #(
  parameter int p_sets = 32,
  parameter int p_demand_depth = 4,
  parameter int p_set_width = $clog2(p_sets),
  parameter int p_line_shift = 4,
  parameter int p_epoch_width = 17 - p_line_shift
) (
  input wire logic clk, rst_n,
  input wire logic i_cfg_accept, i_configured, i_clearing, i_bypass, i_windowed,
  input wire logic i_metadata_enable, i_metadata_fill, i_metadata_fill_good, i_metadata_hit,
  input wire logic i_fill_active, i_fill_selected, i_hit_selected,
  input wire logic [p_set_width-1:0] i_clear_set, i_fill_set, i_lookup_set, i_candidate_set,
  input wire logic [5:0][p_set_width-1:0] i_read_set,
  input wire logic [1:0][p_set_width-1:0] i_offer_tag_set,
  input wire logic [p_set_width-1:0] i_lookup_snapshot_set,
  input wire logic [3:0][p_set_width-1:0] i_lookup_candidate_set,
  input wire logic [1:0] i_lookup_candidate_select,
  input wire logic i_lookup_saved_fill_match,
  input wire logic [31:p_line_shift] i_fill_tag, i_hint_tag,
  input wire logic [p_epoch_width-1:0] i_fill_epoch, i_hit_epoch,
  input wire logic [31:0] i_fill_rank, i_hit_rank, i_hint_rank,
  input wire logic i_hint_resolved, i_hint_valid, i_select_stage_valid,
`ifndef SYNTHESIS
  input wire logic i_lookup_unknown,
`endif
`ifdef NPU_SIM_ASSERT
  input wire logic [4:0] i_tag_read_valid,
  input wire logic i_select_metadata_busy,
`endif
  output logic [5:0] o_valid,
  output logic [4:0][31:p_line_shift] o_tags,
  output logic [31:p_line_shift] o_lookup_tag_raw,
  output logic [p_epoch_width-1:0] o_epoch,
  output logic [31:0] o_rank
);
  localparam int SETS = p_sets;
  localparam int DEMAND_DEPTH = p_demand_depth;
  localparam int SI = p_set_width;
  localparam int LB = p_line_shift;
  localparam int EPOCH_W = p_epoch_width;

    logic valid_i_wr_en;
    logic [SI-1:0] valid_i_wr_addr;
    logic [0:0] valid_i_wr_data, valid_i_wr_mask;
    localparam int p_valid_read_ports = DEMAND_DEPTH > 1 ? 10 : 6;
    logic [p_valid_read_ports-1:0] valid_i_rd_en;
    logic [p_valid_read_ports-1:0][SI-1:0] valid_i_rd_addr;
    logic [p_valid_read_ports-1:0][0:0] valid_o_rd_data;
    logic [5:0] valid_active;

    // 配置清除和填充结束共用一个写端口，填充期间屏蔽被替换行。
    // 前一行完成与下一行开始可以同周期发生，两行的有效状态独立处理。
    assign valid_i_wr_en = rst_n && i_metadata_enable &&
        (i_clearing || (i_metadata_fill && i_fill_selected));
    assign valid_i_wr_addr = i_clearing ? i_clear_set : i_fill_set;
    assign valid_i_wr_data = !i_clearing && i_metadata_fill_good && !i_bypass;
    assign valid_i_wr_mask = 1'b1;
    assign valid_i_rd_en = '1;
    logic [5:0] valid_read_value;
    logic [5:0][SI-1:0] valid_match_address;
    // 有效位与标签同时准备，同拍写入显式转发到保存结果。
    if (DEMAND_DEPTH == 1) begin : g_saved_lookup_valid
      logic lookup_valid_q;
      assign valid_i_rd_addr[0] = i_read_set[0];
      always_ff @(posedge clk) begin
        if (rst_n && !(i_cfg_accept))
          lookup_valid_q <= valid_i_wr_en && valid_i_wr_addr == i_read_set[0] ?
            valid_i_wr_data[0] : valid_o_rd_data[0][0];
      end
      assign valid_read_value[0] = lookup_valid_q;
    end else begin : g_current_lookup_valid
      logic lookup_valid_q;
      (* keep = "true" *) logic [3:0] lookup_candidate_valid;
      assign valid_i_rd_addr[0] = i_read_set[0];
      for (genvar candidate = 0; candidate < 4; candidate++) begin : g_candidate
        assign valid_i_rd_addr[6+candidate] = i_lookup_candidate_set[candidate];
        always_comb begin
          lookup_candidate_valid[candidate] = valid_o_rd_data[6+candidate][0];
          if (valid_i_wr_en && valid_i_wr_addr == i_lookup_candidate_set[candidate])
            lookup_candidate_valid[candidate] = valid_i_wr_data[0];
        end
      end
      // 每个候选位置独立处理同拍写入，时钟边沿仅保存选择结果。
      always_ff @(posedge clk) begin
        if (!rst_n) begin
        end else if (i_cfg_accept) begin
        end else begin
          lookup_valid_q <= lookup_candidate_valid[i_lookup_candidate_select];
`ifndef SYNTHESIS
          // 未知地址按完整数组索引读取，保持部分未知索引的四态语义。
          if (i_lookup_unknown ||
              ((^{valid_i_wr_en, valid_i_wr_addr, valid_i_wr_data}) === 1'bx)) begin
            if (valid_i_wr_en && valid_i_wr_addr == i_read_set[0])
              lookup_valid_q <= valid_i_wr_data[0];
            else lookup_valid_q <= valid_o_rd_data[0][0];
          end
`endif
        end
      end
      assign valid_read_value[0] = lookup_valid_q;
    end
    assign valid_match_address[0] = i_lookup_snapshot_set;
    for (genvar read_port = 1; read_port < 6; read_port++) begin : g_current_valid
      assign valid_read_value[read_port] = valid_o_rd_data[read_port][0];
      assign valid_match_address[read_port] = valid_i_rd_addr[read_port];
    end
    assign valid_i_rd_addr[1] = i_read_set[1];
    assign valid_i_rd_addr[2] = i_read_set[2];
    assign valid_i_rd_addr[3] = i_read_set[3];
    assign valid_i_rd_addr[4] = i_read_set[4];
    assign valid_i_rd_addr[5] = i_read_set[5];
    for (genvar read_port = 0; read_port < 6; read_port++) begin : g_valid_read
      logic fill_set_matches;
      if (DEMAND_DEPTH == 1 && read_port == 0) begin : g_saved
        assign fill_set_matches = i_lookup_saved_fill_match;
      end else begin : g_current
        localparam int p_set_groups = (SI + 2) / 3;
        (* keep = 1 *) logic [p_set_groups-1:0] fill_set_group_matches;
        // 填充组号按三位并行比较，读取有效位与替换行屏蔽在最后合并。
        for (genvar set_group = 0; set_group < p_set_groups; set_group++) begin : g_set_group
          localparam int p_low = set_group * 3;
          localparam int p_width = (SI - p_low < 3) ? SI - p_low : 3;
          assign fill_set_group_matches[set_group] =
              i_fill_set[p_low +: p_width] == valid_match_address[read_port][p_low +: p_width];
        end
        assign fill_set_matches = &fill_set_group_matches;
      end
      assign valid_active[read_port] = i_configured && !i_clearing && valid_read_value[read_port] &&
          !(i_fill_active && i_fill_selected && fill_set_matches);
    end
    assign o_valid[0] = valid_active[0];
    assign o_valid[1] = valid_active[1];
    assign o_valid[2] = valid_active[2];
    assign o_valid[3] = valid_active[3];
    assign o_valid[4] = valid_active[4];
    assign o_valid[5] = valid_active[5];
    regfile #(
      .p_data_width(1), .p_depth(SETS), .p_addr_width(SI),
      .p_write_unit(1), .p_read_ports(p_valid_read_ports), .p_sync_read(1'b0)
    ) u_valid (
      .clk(clk), .i_wr_en(valid_i_wr_en), .i_wr_addr(valid_i_wr_addr),
      .i_wr_data(valid_i_wr_data), .i_wr_mask(valid_i_wr_mask),
      .i_rd_en(valid_i_rd_en), .i_rd_addr(valid_i_rd_addr), .o_rd_data(valid_o_rd_data)
    );
    localparam int p_tag_width = 32-LB;
    logic [EPOCH_W-1:0] fill_epoch_q, hit_epoch_q;
    logic [31:0] fill_rank_q, hit_rank_q, hint_rank_q;
    logic [1:0] rank_source_q;
    logic rank_source_i_clear_en, rank_source_i_hit_valid, rank_source_i_read_en;
    logic fill_update, hit_update, hint_update;
    logic tags_i_wr_en;
    logic [SI-1:0] tags_i_wr_addr;
    logic [p_tag_width-1:0] tags_i_wr_data;
    logic [0:0] tags_i_wr_mask;
    logic [4:0] tags_i_rd_en;
    logic [4:0][SI-1:0] tags_i_rd_addr;
    logic [4:0][p_tag_width-1:0] tags_o_rd_data, tags_raw_data;
    logic metadata_i_rd_en;
    logic [SI-1:0] metadata_i_rd_addr;
    logic [0:0] metadata_i_wr_mask;
    logic fill_epoch_i_wr_en, fill_epoch_i_rd_en;
    logic [SI-1:0] fill_epoch_i_rd_addr;
    logic [0:0] fill_epoch_i_wr_mask;
    logic [SI-1:0] fill_epoch_i_wr_addr;
    logic [EPOCH_W-1:0] fill_epoch_i_wr_data, fill_epoch_o_rd_data;
    logic hit_epoch_i_wr_en, hit_epoch_i_rd_en;
    logic [SI-1:0] hit_epoch_i_rd_addr;
    logic [0:0] hit_epoch_i_wr_mask;
    logic [SI-1:0] hit_epoch_i_wr_addr;
    logic [EPOCH_W-1:0] hit_epoch_i_wr_data, hit_epoch_o_rd_data;
    logic fill_rank_i_wr_en, fill_rank_i_rd_en;
    logic [SI-1:0] fill_rank_i_rd_addr;
    logic [0:0] fill_rank_i_wr_mask;
    logic [SI-1:0] fill_rank_i_wr_addr;
    logic [31:0] fill_rank_i_wr_data, fill_rank_o_rd_data;
    logic hit_rank_i_wr_en, hit_rank_i_rd_en;
    logic [SI-1:0] hit_rank_i_rd_addr;
    logic [0:0] hit_rank_i_wr_mask;
    logic [SI-1:0] hit_rank_i_wr_addr;
    logic [31:0] hit_rank_i_wr_data, hit_rank_o_rd_data;
    logic hint_rank_i_wr_en, hint_rank_i_rd_en;
    logic [SI-1:0] hint_rank_i_rd_addr;
    logic [0:0] hint_rank_i_wr_mask;
    logic [SI-1:0] hint_rank_i_wr_addr;
    logic [31:0] hint_rank_i_wr_data, hint_rank_o_rd_data;

    assign fill_update = i_metadata_enable && i_metadata_fill_good && i_fill_selected;
    assign hit_update = i_metadata_enable && i_metadata_hit && i_hit_selected;
    assign hint_update = i_metadata_enable && i_hint_resolved && !i_windowed &&
        o_valid[5] && o_tags[4] == i_hint_tag;
    assign tags_i_wr_en = fill_update;
    assign tags_i_wr_addr = i_fill_set;
    assign tags_i_wr_data = i_fill_tag;
    assign tags_i_wr_mask = 1'b1;
    assign tags_i_rd_en = '1;
    assign tags_i_rd_addr[0] = i_read_set[0];
    assign tags_i_rd_addr[1] = i_read_set[1];
    assign tags_i_rd_addr[2] = i_offer_tag_set[0];
    assign tags_i_rd_addr[3] = i_offer_tag_set[1];
    assign tags_i_rd_addr[4] = i_read_set[5];
    assign o_tags[0] = tags_o_rd_data[0];
    assign o_tags[1] = tags_o_rd_data[1];
    assign o_tags[2] = tags_o_rd_data[2];
    assign o_tags[3] = tags_o_rd_data[3];
    assign o_tags[4] = tags_o_rd_data[4];
    assign metadata_i_rd_en = !i_select_stage_valid;
    assign metadata_i_rd_addr = i_candidate_set;
    assign metadata_i_wr_mask = 1'b1;

    // 各标签端口保持原有同步周期，第一个端口的地址匹配与读取一起保存。
    assign o_lookup_tag_raw = tags_raw_data[0];
    always_ff @(posedge clk) tags_o_rd_data <= tags_raw_data;
    regfile #(
      .p_data_width(p_tag_width), .p_depth(SETS), .p_addr_width(SI),
      .p_write_unit(p_tag_width), .p_read_ports(5), .p_sync_read(1'b0),
      .p_ram_style(DEMAND_DEPTH > 1 ? "block" : "auto")
    ) u_tags (
      .clk(clk), .i_wr_en(tags_i_wr_en), .i_wr_addr(tags_i_wr_addr),
      .i_wr_data(tags_i_wr_data), .i_wr_mask(tags_i_wr_mask),
      .i_rd_en(tags_i_rd_en), .i_rd_addr(tags_i_rd_addr), .o_rd_data(tags_raw_data)
    );

    // 填充、命中和提示各自保存替换信息，读取使能由已保存的候选状态控制。
    assign fill_epoch_i_rd_en = metadata_i_rd_en;
    assign fill_epoch_i_rd_addr = metadata_i_rd_addr;
    assign fill_epoch_i_wr_mask = metadata_i_wr_mask;
    assign fill_epoch_i_wr_en = fill_update;
    assign fill_epoch_i_wr_addr = i_fill_set;
    assign fill_epoch_i_wr_data = EPOCH_W'(i_fill_epoch);
    assign fill_epoch_q = fill_epoch_o_rd_data;
    regfile #(
      .p_data_width(EPOCH_W), .p_depth(SETS), .p_addr_width(SI),
      .p_write_unit(EPOCH_W), .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_fill_epoch (
      .clk(clk), .i_wr_en(fill_epoch_i_wr_en), .i_wr_addr(fill_epoch_i_wr_addr),
      .i_wr_data(fill_epoch_i_wr_data), .i_wr_mask(fill_epoch_i_wr_mask),
      .i_rd_en(fill_epoch_i_rd_en), .i_rd_addr(fill_epoch_i_rd_addr), .o_rd_data(fill_epoch_o_rd_data)
    );
    assign hit_epoch_i_rd_en = metadata_i_rd_en;
    assign hit_epoch_i_rd_addr = metadata_i_rd_addr;
    assign hit_epoch_i_wr_mask = metadata_i_wr_mask;
    assign hit_epoch_i_wr_en = hit_update;
    assign hit_epoch_i_wr_addr = i_lookup_set;
    assign hit_epoch_i_wr_data = EPOCH_W'(i_hit_epoch);
    assign hit_epoch_q = hit_epoch_o_rd_data;
    regfile #(
      .p_data_width(EPOCH_W), .p_depth(SETS), .p_addr_width(SI),
      .p_write_unit(EPOCH_W), .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_hit_epoch (
      .clk(clk), .i_wr_en(hit_epoch_i_wr_en), .i_wr_addr(hit_epoch_i_wr_addr),
      .i_wr_data(hit_epoch_i_wr_data), .i_wr_mask(hit_epoch_i_wr_mask),
      .i_rd_en(hit_epoch_i_rd_en), .i_rd_addr(hit_epoch_i_rd_addr), .o_rd_data(hit_epoch_o_rd_data)
    );
    assign fill_rank_i_rd_en = metadata_i_rd_en;
    assign fill_rank_i_rd_addr = metadata_i_rd_addr;
    assign fill_rank_i_wr_mask = metadata_i_wr_mask;
    assign fill_rank_i_wr_en = fill_update;
    assign fill_rank_i_wr_addr = i_fill_set;
    assign fill_rank_i_wr_data = i_fill_rank;
    assign fill_rank_q = fill_rank_o_rd_data;
    regfile #(
      .p_data_width(32), .p_depth(SETS), .p_addr_width(SI),
      .p_write_unit(32), .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_fill_rank (
      .clk(clk), .i_wr_en(fill_rank_i_wr_en), .i_wr_addr(fill_rank_i_wr_addr),
      .i_wr_data(fill_rank_i_wr_data), .i_wr_mask(fill_rank_i_wr_mask),
      .i_rd_en(fill_rank_i_rd_en), .i_rd_addr(fill_rank_i_rd_addr), .o_rd_data(fill_rank_o_rd_data)
    );
    assign hit_rank_i_rd_en = metadata_i_rd_en;
    assign hit_rank_i_rd_addr = metadata_i_rd_addr;
    assign hit_rank_i_wr_mask = metadata_i_wr_mask;
    assign hit_rank_i_wr_en = hit_update && (i_windowed || i_hint_valid);
    assign hit_rank_i_wr_addr = i_lookup_set;
    assign hit_rank_i_wr_data = i_hit_rank;
    assign hit_rank_q = hit_rank_o_rd_data;
    regfile #(
      .p_data_width(32), .p_depth(SETS), .p_addr_width(SI),
      .p_write_unit(32), .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_hit_rank (
      .clk(clk), .i_wr_en(hit_rank_i_wr_en), .i_wr_addr(hit_rank_i_wr_addr),
      .i_wr_data(hit_rank_i_wr_data), .i_wr_mask(hit_rank_i_wr_mask),
      .i_rd_en(hit_rank_i_rd_en), .i_rd_addr(hit_rank_i_rd_addr), .o_rd_data(hit_rank_o_rd_data)
    );
    assign hint_rank_i_rd_en = metadata_i_rd_en;
    assign hint_rank_i_rd_addr = metadata_i_rd_addr;
    assign hint_rank_i_wr_mask = metadata_i_wr_mask;
    assign hint_rank_i_wr_en = hint_update;
    assign hint_rank_i_wr_addr = i_read_set[5];
    assign hint_rank_i_wr_data = i_hint_rank;
    assign hint_rank_q = hint_rank_o_rd_data;
    regfile #(
      .p_data_width(32), .p_depth(SETS), .p_addr_width(SI),
      .p_write_unit(32), .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_hint_rank (
      .clk(clk), .i_wr_en(hint_rank_i_wr_en), .i_wr_addr(hint_rank_i_wr_addr),
      .i_wr_data(hint_rank_i_wr_data), .i_wr_mask(hint_rank_i_wr_mask),
      .i_rd_en(hint_rank_i_rd_en), .i_rd_addr(hint_rank_i_rd_addr), .o_rd_data(hint_rank_o_rd_data)
    );
    // 三个写入来源保留独立端口，同步读取组合后的来源编码。
    assign rank_source_i_clear_en = rst_n && i_metadata_enable && i_clearing;
    assign rank_source_i_hit_valid = hit_update && (i_windowed || i_hint_valid);
    assign rank_source_i_read_en = !i_select_stage_valid;
    conv_cache_rank_table #(.p_depth(SETS), .p_addr_width(SI)) u_rank_source (
      .clk(clk), .i_clear_en(rank_source_i_clear_en), .i_clear_addr(i_clear_set),
      .i_write_en(rst_n), .i_fill_valid(fill_update), .i_fill_addr(i_fill_set),
      .i_hint_valid(hint_update), .i_hint_addr(i_read_set[5]),
      .i_hit_valid(rank_source_i_hit_valid), .i_hit_addr(i_lookup_set),
      .i_read_en(rank_source_i_read_en), .i_read_addr(i_candidate_set), .o_read_data(rank_source_q)
    );
    // 窗口命中同步更新代次与替换顺序，来源标记选择相同一次访问的记录。
    assign o_epoch = rank_source_q == 2'd2 ? hit_epoch_q : fill_epoch_q;
    assign o_rank = rank_source_q == 2'd2 ? hit_rank_q :
        rank_source_q == 2'd1 ? hint_rank_q : fill_rank_q;
`ifdef NPU_SIM_ASSERT
    // 根据逻辑写端口记录元数据，检查范围覆盖全部有效行。
    // 记录数组不依赖存储器内部层次，寄存器和 SRAM 实现使用相同检查。
    logic observed_valid [SETS];
    logic [p_tag_width-1:0] observed_tags [SETS];
    logic [EPOCH_W-1:0] observed_fill_epoch [SETS], observed_hit_epoch [SETS];
    logic [31:0] observed_fill_rank [SETS], observed_hit_rank [SETS], observed_hint_rank [SETS];
    logic [1:0] observed_rank_bank [3][SETS];
    wire [1:0] observed_rank_source [SETS];
    always_ff @(posedge clk) begin
      if (valid_i_wr_en && valid_i_wr_mask[0])
        observed_valid[valid_i_wr_addr] <= valid_i_wr_data[0];
      if (tags_i_wr_en && tags_i_wr_mask[0])
        observed_tags[tags_i_wr_addr] <= tags_i_wr_data;
      if (fill_epoch_i_wr_en && fill_epoch_i_wr_mask[0])
        observed_fill_epoch[fill_epoch_i_wr_addr] <= fill_epoch_i_wr_data;
      if (hit_epoch_i_wr_en && hit_epoch_i_wr_mask[0])
        observed_hit_epoch[hit_epoch_i_wr_addr] <= hit_epoch_i_wr_data;
      if (fill_rank_i_wr_en && fill_rank_i_wr_mask[0])
        observed_fill_rank[fill_rank_i_wr_addr] <= fill_rank_i_wr_data;
      if (hit_rank_i_wr_en && hit_rank_i_wr_mask[0])
        observed_hit_rank[hit_rank_i_wr_addr] <= hit_rank_i_wr_data;
      if (hint_rank_i_wr_en && hint_rank_i_wr_mask[0])
        observed_hint_rank[hint_rank_i_wr_addr] <= hint_rank_i_wr_data;
    end
    for (genvar source_bank=0; source_bank<3; source_bank++) begin : g_observed_source
      always_ff @(posedge clk) begin
        if (u_rank_source.bank_i_wr_en[source_bank] && u_rank_source.bank_i_wr_mask)
          observed_rank_bank[source_bank][u_rank_source.bank_i_wr_addr[source_bank]] <=
              u_rank_source.bank_i_wr_data[source_bank];
      end
    end
    for (genvar metadata_set=0; metadata_set<SETS; metadata_set++) begin : g_metadata_set
      assign observed_rank_source[metadata_set] = observed_rank_bank[0][metadata_set] ^
          observed_rank_bank[1][metadata_set] ^ observed_rank_bank[2][metadata_set];
      initial forever @(posedge clk) if (rst_n && i_configured && !i_clearing &&
          observed_valid[metadata_set] &&
          !(i_fill_active && i_fill_selected && i_fill_set == SI'(metadata_set))) begin
        assert (!$isunknown({observed_tags[metadata_set], observed_rank_source[metadata_set]}));
        assert (!$isunknown(observed_rank_source[metadata_set] == 2'd2 ?
                            observed_hit_epoch[metadata_set] : observed_fill_epoch[metadata_set]));
        assert (!$isunknown(observed_rank_source[metadata_set] == 2'd2 ? observed_hit_rank[metadata_set] :
                            observed_rank_source[metadata_set] == 2'd1 ? observed_hint_rank[metadata_set] :
                            observed_fill_rank[metadata_set]));
      end
    end
    // 消费有效读取结果时同时检查真实输出，覆盖存储器读取与选择逻辑。
    initial forever @(posedge clk) if (rst_n && i_configured && !i_clearing) begin
      if (i_tag_read_valid[0] && o_valid[0])
        assert (!$isunknown(o_tags[0]));
      if (i_tag_read_valid[1] && o_valid[1])
        assert (!$isunknown(o_tags[1]));
      if (i_tag_read_valid[2] && o_valid[2])
        assert (!$isunknown(o_tags[2]));
      if (i_tag_read_valid[3] && o_valid[3])
        assert (!$isunknown(o_tags[3]));
      if (i_tag_read_valid[4] && o_valid[5])
        assert (!$isunknown(o_tags[4]));
      if (i_select_stage_valid && !i_select_metadata_busy && o_valid[4])
        assert (!$isunknown({rank_source_q, o_epoch, o_rank}));
    end
`endif
endmodule

`default_nettype wire
